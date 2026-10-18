"""Bounded Phase 15 virtual-user ladder for disposable chat and research fixtures."""
import argparse
import asyncio
import json
import math
import os
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import httpx
import psycopg
import redis

LEVELS = (1, 5, 10, 25, 50, 100)
QUESTIONS = (
    "How does KV cache compression reduce inference memory?",
    "How does weight quantization reduce inference memory?",
    "Compare cache compression with weight quantization for inference memory.",
)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def summarize(records: list[dict], seconds: float) -> dict:
    latencies = [record["latency_ms"] for record in records]
    errors = [record for record in records if record["error"]]
    return {"requests": len(records), "successes": len(records) - len(errors),
            "errors": len(errors), "error_types": dict(Counter(record["error"] for record in errors)),
            "wall_seconds": seconds,
            "throughput_per_second": (len(records) - len(errors)) / seconds if seconds else None,
            "p50_ms": percentile(latencies, .5), "p95_ms": percentile(latencies, .95),
            "p99_ms": percentile(latencies, .99), "max_ms": max(latencies, default=None)}


async def chat_user(client: httpx.AsyncClient, workspace_id: str, level: int, user: int,
                    requests_per_user: int, repeat_fraction: float) -> list[dict]:
    records = []
    for index in range(requests_per_user):
        serial = user * requests_per_user + index
        question = QUESTIONS[serial % len(QUESTIONS)]
        if serial / (level * requests_per_user) >= repeat_fraction:
            question += f" Case {level}-{serial}."
        started = perf_counter()
        error = None
        try:
            response = await client.post(f"/workspaces/{workspace_id}/chat", json={"message": question})
            if response.status_code != 200:
                error = f"http_{response.status_code}"
            else:
                body = response.json()
                if body.get("status") != "answered" or not body.get("sources"):
                    error = "invalid_answer"
        except (httpx.HTTPError, ValueError) as exc:
            error = type(exc).__name__
        records.append({"latency_ms": (perf_counter() - started) * 1000, "error": error})
    return records


async def research_user(client: httpx.AsyncClient, workspace_id: str, level: int, user: int,
                        timeout: float, poll_interval: float) -> dict:
    started = perf_counter()
    error = None
    submit_ms = None
    status = None
    try:
        response = await client.post(f"/workspaces/{workspace_id}/research-jobs", json={
            "query": f"Compare how the papers reduce LLM inference memory. Case {level}-{user}."})
        submit_ms = (perf_counter() - started) * 1000
        if response.status_code != 202:
            error = f"submit_http_{response.status_code}"
        else:
            location = response.headers["location"]
            deadline = perf_counter() + timeout
            while perf_counter() < deadline:
                response = await client.get(location)
                if response.status_code != 200:
                    error = f"poll_http_{response.status_code}"
                    break
                status = response.json().get("status")
                if status == "completed":
                    break
                if status == "failed":
                    error = "job_failed"
                    break
                await asyncio.sleep(poll_interval)
            else:
                error = "job_timeout"
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        error = type(exc).__name__
    return {"latency_ms": (perf_counter() - started) * 1000,
            "submit_ms": submit_ms, "status": status, "error": error}


def memory_bytes(value: str) -> int | None:
    match = re.match(r"^([\d.]+)(B|KiB|MiB|GiB|kB|MB|GB)$", value.strip())
    if not match:
        return None
    scale = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3,
             "kB": 1000, "MB": 1000**2, "GB": 1000**3}
    return int(float(match[1]) * scale[match[2]])


def sample_infrastructure(project: str) -> dict:
    sample = {"database_connections": None, "research_queue_depth": None,
              "ingestion_queue_depth": None, "memory_bytes": {}}
    database_url = os.environ.get("PHASE15_DATABASE_URL")
    redis_url = os.environ.get("PHASE15_REDIS_URL")
    if database_url:
        with psycopg.connect(database_url, connect_timeout=2) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()")
            sample["database_connections"] = cursor.fetchone()[0]
    if redis_url:
        connection = redis.Redis.from_url(redis_url, socket_timeout=2)
        sample["research_queue_depth"] = connection.llen("rq:queue:research")
        sample["ingestion_queue_depth"] = connection.llen("rq:queue:ingestion")
    output = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.MemUsage}}"],
                            capture_output=True, text=True, timeout=10, check=True).stdout
    for line in output.splitlines():
        name, _, usage = line.partition("|")
        if name.startswith(f"{project}-"):
            amount = memory_bytes(usage.split("/", 1)[0])
            if amount is not None:
                sample["memory_bytes"][name] = amount
    return sample


async def monitor(project: str, stop: asyncio.Event, samples: list[dict]) -> None:
    while not stop.is_set():
        try:
            samples.append(await asyncio.to_thread(sample_infrastructure, project))
        except (psycopg.Error, redis.RedisError, subprocess.SubprocessError,
                OSError, ValueError) as exc:
            samples.append({"sampling_error": type(exc).__name__})
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            pass


def summarize_infrastructure(samples: list[dict]) -> dict:
    result = {"samples": len(samples), "sampling_errors": sum("sampling_error" in sample for sample in samples)}
    for key in ("database_connections", "research_queue_depth", "ingestion_queue_depth"):
        values = [sample[key] for sample in samples if sample.get(key) is not None]
        result[f"{key}_max"] = max(values, default=None)
    names = {name for sample in samples for name in sample.get("memory_bytes", {})}
    result["memory_bytes_max"] = {name: max(sample.get("memory_bytes", {}).get(name, 0)
                                             for sample in samples) for name in sorted(names)}
    return result


async def run_level(client: httpx.AsyncClient, mode: str, workspace_id: str, level: int,
                    requests_per_user: int, repeat_fraction: float, job_timeout: float,
                    poll_interval: float,
                    project: str | None) -> dict:
    samples = []
    stop = asyncio.Event()
    sampler = asyncio.create_task(monitor(project, stop, samples)) if project else None
    started = perf_counter()
    try:
        if mode == "chat":
            groups = await asyncio.gather(*(chat_user(client, workspace_id, level, user,
                requests_per_user, repeat_fraction) for user in range(level)))
            records = [record for group in groups for record in group]
        else:
            records = await asyncio.gather(*(research_user(client, workspace_id, level, user,
                job_timeout, poll_interval) for user in range(level)))
    finally:
        if sampler:
            stop.set()
            await sampler
    result = {"concurrent_users": level, **summarize(records, perf_counter() - started)}
    if mode == "research":
        result["submission_p95_ms"] = percentile([record["submit_ms"] for record in records
                                                    if record["submit_ms"] is not None], .95)
    if project:
        result["infrastructure"] = summarize_infrastructure(samples)
    return result


async def run(fixture: dict, mode: str, levels: tuple[int, ...], requests_per_user: int,
              repeat_fraction: float, job_timeout: float, poll_interval: float,
              project: str | None) -> dict:
    headers = {"Authorization": f"Bearer {fixture['token']}"}
    result = {"recorded_at": datetime.now(UTC).isoformat(), "mode": mode,
              "base_url": fixture["base_url"], "workspace_id": fixture["workspace_id"],
              "model": "disposable deterministic provider", "concurrency_levels": levels,
              "requests_per_user": requests_per_user if mode == "chat" else 1,
              "repeat_fraction": repeat_fraction if mode == "chat" else None,
              "poll_interval_seconds": poll_interval if mode == "research" else None,
              "rungs": []}
    limits = httpx.Limits(max_connections=max(levels) * 2 + 10,
                          max_keepalive_connections=max(levels) + 10)
    async with httpx.AsyncClient(base_url=fixture["base_url"], headers=headers,
                                 timeout=httpx.Timeout(60), limits=limits) as client:
        for level in levels:
            rung = await run_level(client, mode, fixture["workspace_id"], level,
                                   requests_per_user, repeat_fraction, job_timeout,
                                   poll_interval, project)
            result["rungs"].append(rung)
            print(f"{mode} users={level} throughput={rung['throughput_per_second']:.2f}/s "
                  f"p95={rung['p95_ms']:.1f}ms errors={rung['errors']}", flush=True)
            await asyncio.sleep(2)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--mode", choices=("chat", "research"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--levels", default="1,5,10,25,50,100")
    parser.add_argument("--requests-per-user", type=int, default=3)
    parser.add_argument("--repeat-fraction", type=float, default=.2)
    parser.add_argument("--job-timeout", type=float, default=300)
    parser.add_argument("--poll-interval", type=float, default=2.5,
                        help="Research status polling interval; matches the frontend by default")
    parser.add_argument("--docker-project", help="Sample Docker memory, PostgreSQL connections, and Redis queues")
    args = parser.parse_args()
    try:
        levels = tuple(int(value) for value in args.levels.split(","))
    except ValueError as exc:
        parser.error(f"Invalid --levels: {exc}")
    if not levels or any(level < 1 or level > 100 for level in levels) or sorted(set(levels)) != list(levels):
        parser.error("Levels must be increasing, unique integers between 1 and 100")
    if (args.requests_per_user < 1 or not 0 <= args.repeat_fraction <= 1
            or args.job_timeout <= 0 or args.poll_interval <= 0):
        parser.error("Invalid request count, repeat fraction, job timeout, or poll interval")
    if args.output.exists():
        parser.error("Output already exists; use a new path")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    result = asyncio.run(run(fixture, args.mode, levels, args.requests_per_user,
                             args.repeat_fraction, args.job_timeout, args.poll_interval,
                             args.docker_project))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
