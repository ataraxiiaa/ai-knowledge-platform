"""Small OpenTelemetry surface shared by API, workers, and dispatcher."""
from contextlib import contextmanager
from functools import wraps
import logging
import os
import time
from typing import Iterator

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

logger = logging.getLogger(__name__)
_initialized = False
_meter = None
_tracer = None
_queue_callback = None


def initialize(service_name: str | None = None) -> None:
    global _initialized, _meter, _tracer
    if _initialized:
        return
    _initialized = True
    if os.getenv("OTEL_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        return
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")
    resource = Resource.create({
        "service.name": service_name or os.getenv("OTEL_SERVICE_NAME", "ai-knowledge-platform"),
        "service.namespace": "ai-knowledge-platform",
        "deployment.environment": os.getenv("OTEL_ENVIRONMENT", "local"),
    })
    try:
        trace_provider = TracerProvider(resource=resource)
        trace_provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")))
        trace.set_tracer_provider(trace_provider)
        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{endpoint.rstrip('/')}/v1/metrics"),
            export_interval_millis=10_000,
        )
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))
        _tracer = trace.get_tracer("ai_knowledge_platform")
        meter = metrics.get_meter("ai_knowledge_platform")
        _meter = {
            "http_requests": meter.create_counter("http.server.request.count", unit="{request}"),
            "http_duration": meter.create_histogram("http.server.request.duration", unit="s"),
            "model_requests": meter.create_counter("llm.request.count", unit="{request}"),
            "model_duration": meter.create_histogram("llm.generation.duration", unit="s"),
            "model_ttft": meter.create_histogram("llm.time_to_first_token", unit="s"),
            "model_tokens": meter.create_counter("llm.tokens", unit="{token}"),
            "embedding_requests": meter.create_counter("embedding.request.count", unit="{request}"),
            "embedding_duration": meter.create_histogram("embedding.duration", unit="s"),
            "embedding_vectors": meter.create_counter("embedding.vectors", unit="{vector}"),
            "retrieval_duration": meter.create_histogram("rag.retrieval.duration", unit="s"),
            "retrieval_chunks": meter.create_histogram("rag.retrieval.chunks", unit="{chunk}"),
            "rerank_duration": meter.create_histogram("rag.reranking.duration", unit="s"),
            "rerank_candidates": meter.create_histogram("rag.reranking.candidates", unit="{chunk}"),
            "jobs": meter.create_counter("worker.jobs.count", unit="{job}"),
            "job_duration": meter.create_histogram("worker.job.duration", unit="s"),
            "research_stage_duration": meter.create_histogram("research.stage.duration", unit="s"),
            "job_retries": meter.create_counter("worker.job.retries", unit="{retry}"),
            "queue_depth": meter.create_observable_gauge("worker.queue.depth", callbacks=[_observe_queues], unit="{job}"),
        }
    except Exception:
        # Telemetry export is best effort and must not break serving work.
        logger.exception("OpenTelemetry setup failed; telemetry is disabled in this process")
        _tracer, _meter = None, None


@contextmanager
def span(name: str, attributes: dict | None = None) -> Iterator:
    initialize()
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name, attributes=attributes or {}) as current:
        yield current


def record_http(method: str, route: str, status: int, duration: float) -> None:
    initialize()
    if _meter is None:
        return
    attrs = {"http.request.method": method, "http.route": route, "http.response.status_code": status}
    _meter["http_requests"].add(1, attrs)
    _meter["http_duration"].record(duration, attrs)


def record_model(provider: str, model: str, task: str, duration: float, *,
                 usage=None, error: str | None = None, ttft: float | None = None) -> None:
    initialize()
    if _meter is None:
        return
    attrs = {"gen_ai.provider.name": provider, "gen_ai.request.model": model, "app.model.task": task,
             "outcome": "error" if error else "success"}
    _meter["model_requests"].add(1, attrs)
    _meter["model_duration"].record(duration, attrs)
    if ttft is not None:
        _meter["model_ttft"].record(ttft, attrs)
    if usage:
        for kind, count in (("input", usage.input_tokens), ("output", usage.output_tokens)):
            if count is not None:
                _meter["model_tokens"].add(count, {**attrs, "token.type": kind})


def record_retrieval(method: str, duration: float, chunk_count: int) -> None:
    initialize()
    if _meter is not None:
        attrs = {"rag.retrieval.method": method}
        _meter["retrieval_duration"].record(duration, attrs)
        _meter["retrieval_chunks"].record(chunk_count, attrs)


def record_embedding(duration: float, vector_count: int, *, outcome: str) -> None:
    initialize()
    if _meter is not None:
        attrs = {"provider": "fastembed", "model": "BAAI/bge-small-en-v1.5", "outcome": outcome}
        _meter["embedding_requests"].add(1, attrs)
        _meter["embedding_duration"].record(duration, attrs)
        if vector_count:
            _meter["embedding_vectors"].add(vector_count, attrs)


def record_reranking(duration: float, candidates: int, *, outcome: str) -> None:
    initialize()
    if _meter is not None:
        attrs = {"outcome": outcome}
        _meter["rerank_duration"].record(duration, attrs)
        _meter["rerank_candidates"].record(candidates, attrs)


def record_job(queue: str, job_type: str, status: str, duration: float) -> None:
    initialize()
    if _meter is not None:
        attrs = {"messaging.destination.name": queue, "worker.job.type": job_type, "outcome": status}
        _meter["jobs"].add(1, attrs)
        _meter["job_duration"].record(duration, attrs)


def job_span(queue: str, job_type: str):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with span("worker.job", {"messaging.system": "rq",
                    "messaging.destination.name": queue, "worker.job.type": job_type}) as current:
                try:
                    result = function(*args, **kwargs)
                    if current is not None:
                        current.set_attribute("worker.job.processed", True)
                    return result
                except Exception as exc:
                    if current is not None:
                        current.set_attribute("worker.job.processed", False)
                        current.set_attribute("error.type", type(exc).__name__)
                    raise
        return wrapped
    return decorate


def record_retry(queue: str, job_type: str) -> None:
    initialize()
    if _meter is not None:
        _meter["job_retries"].add(1, {"messaging.destination.name": queue, "worker.job.type": job_type})


@contextmanager
def research_stage(name: str) -> Iterator:
    started = time.perf_counter()
    outcome = "success"
    try:
        with span("research.stage", {"research.stage": name}) as current:
            yield current
    except Exception:
        outcome = "error"
        raise
    finally:
        initialize()
        if _meter is not None:
            _meter["research_stage_duration"].record(
                time.perf_counter() - started, {"research.stage": name, "outcome": outcome})


def set_queue_depth_callback(callback) -> None:
    global _queue_callback
    initialize()
    if _meter is None:
        return
    _queue_callback = callback


def observe_rq_queues(connection, ingestion_name: str, research_name: str) -> None:
    from rq import Queue

    set_queue_depth_callback(lambda: {
        ingestion_name: Queue(ingestion_name, connection=connection).count,
        research_name: Queue(research_name, connection=connection).count,
    })


def _observe_queues(_options):
    if _queue_callback is None:
        return
    try:
        for name, value in _queue_callback().items():
            yield metrics.Observation(max(0, int(value)), {"messaging.destination.name": name})
    except Exception:
        logger.debug("Queue depth collection failed", exc_info=True)


def elapsed(started: float) -> float:
    return max(0.0, time.perf_counter() - started)
