# Phase 11: observability

FastAPI, RQ workers, and the dispatcher emit OpenTelemetry metrics and traces.
The Collector receives OTLP over HTTP, exposes metrics for Prometheus, and sends
traces to Tempo. Grafana provisions both data sources and the AI Knowledge
Platform dashboard.

The dashboard includes request throughput and P95 latency, HTTP and model
failure rates, model generation latency and token usage, streaming TTFT when a
stream is consumed, retrieval and reranking latency, research stage durations,
worker job durations and retries, queue depth, container CPU and memory. GPU
utilization and VRAM panels become active when Docker has NVIDIA GPU support and
the optional `gpu` Compose profile is enabled. CPU and memory figures describe
containers; they are not host-wide measurements.

## Start locally

Add these settings to the root `.env` file (also configure `SECRET_KEY`):

```dotenv
OTEL_ENABLED=true
OTEL_ENVIRONMENT=local
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=<generate-a-long-unique-password>
```

Then start the stack with `docker compose up --build -d`. Open Grafana at
`http://localhost:3001` and sign in with the configured admin credentials. The
dashboard is provisioned as **AI Knowledge Platform**. Prometheus is available
at `http://localhost:9090`; Tempo's query API is available on the Compose
network. Collector OTLP endpoints are bound to localhost ports 4317 and 4318.

For NVIDIA GPU metrics, start with `docker compose --profile gpu up --build -d`.
This requires an NVIDIA GPU and a working NVIDIA Container Toolkit installation.
Without it, GPU panels remain empty; CPU and memory panels still work.

## Signals and limits

HTTP metrics use route templates and methods, never raw paths or query strings.
Model metrics have bounded task/outcome labels and configured provider/model
labels. No prompt, document passage, answer, workspace identifier, or user ID
is attached to telemetry. The model failure rate counts provider attempts,
including retries and fallback attempts. Token counters reflect provider usage
when the provider returns it. TTFT is recorded only for internal streaming calls
and measures time until the first non-empty text chunk reaches the caller.

RQ queue depth is the waiting Redis queue count. Durable dispatch intents are
not added because they coexist with published RQ jobs and would double count.
Worker job metrics distinguish completed, failed, retrying, and abandoned
attempts. Container stats come from cAdvisor. The GPU exporter is optional.

Compose enables telemetry by default. For a native API or worker process, set
`OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT` to a reachable collector;
set `OTEL_ENABLED=false` to disable SDK initialization. The application does
not need a collector to serve requests; when export is unavailable, telemetry
is best effort. Prometheus retains seven days of metrics and the local Tempo setup
retains one day of traces. These local defaults are intended for development,
not a multi-host production deployment. See [the Compose stack](../docker-compose.yml)
and [collector configuration](../observability/otel-collector.yml).
