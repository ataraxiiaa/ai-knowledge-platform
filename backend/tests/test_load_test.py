import asyncio
import json

import httpx

from scripts.load_test import (
    chat_user,
    memory_bytes,
    percentile,
    research_user,
    summarize,
    summarize_infrastructure,
)


def test_percentiles_and_error_rate_are_measured_from_all_attempts():
    records = [{"latency_ms": value, "error": None} for value in (10, 20, 30, 40)]
    records[-1]["error"] = "http_503"
    result = summarize(records, 2)
    assert result["successes"] == 3 and result["errors"] == 1
    assert result["throughput_per_second"] == 1.5
    assert result["p50_ms"] == 20 and result["p95_ms"] == 40 and result["p99_ms"] == 40
    assert percentile([], .5) is None


def test_chat_user_records_http_failures_and_valid_answers():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"status": "answered", "sources": [{"id": 1}]})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     base_url="http://test") as client:
            return await chat_user(client, "workspace", 1, 0, 3, .2)

    result = asyncio.run(scenario())
    assert [record["error"] for record in result] == [None, "http_503", None]


def test_research_user_tracks_terminal_completion():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if request.method == "POST":
            return httpx.Response(202, headers={"location": "/jobs/one"}, json={})
        return httpx.Response(200, json={"status": "completed"})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     base_url="http://test") as client:
            return await research_user(client, "workspace", 1, 0, 1, 2.5)

    result = asyncio.run(scenario())
    assert calls == 2 and result["error"] is None and result["status"] == "completed"
    assert result["submit_ms"] is not None


def test_infrastructure_samples_preserve_unavailable_metrics():
    samples = [{"database_connections": 3, "research_queue_depth": 2,
                "ingestion_queue_depth": 0, "memory_bytes": {"phase15-load-backend-1": 1024}},
               {"sampling_error": "RuntimeError"}]
    summary = summarize_infrastructure(samples)
    assert summary["sampling_errors"] == 1
    assert summary["database_connections_max"] == 3
    assert summary["research_queue_depth_max"] == 2
    assert summary["memory_bytes_max"]["phase15-load-backend-1"] == 1024
    assert memory_bytes("1.5MiB") == int(1.5 * 1024**2)
    assert json.dumps(summary)
