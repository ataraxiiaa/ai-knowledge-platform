"""Measure repeated chat latency and cache counters against a running API."""
import argparse
import json
import os
from statistics import mean
from time import perf_counter

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="API base URL")
    parser.add_argument("--workspace", required=True, help="Owned workspace UUID")
    parser.add_argument("--query", required=True, help="Question to repeat")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if args.runs < 2 or args.runs > 20:
        parser.error("--runs must be between 2 and 20")
    token = os.environ.get("CACHE_BENCHMARK_TOKEN", "")
    if not token:
        parser.error("Set CACHE_BENCHMARK_TOKEN in the environment")
    base = args.url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}
    prefix = f"{base}/workspaces/{args.workspace}"
    with httpx.Client(timeout=120, headers=headers) as client:
        before = client.get(f"{prefix}/cache-metrics")
        before.raise_for_status()
        elapsed = []
        for _ in range(args.runs):
            started = perf_counter()
            response = client.post(f"{prefix}/chat", json={"message": args.query})
            response.raise_for_status()
            payload = response.json()
            if payload["status"] == "answered" and not payload["sources"]:
                raise RuntimeError("Chat returned an answer without sources")
            elapsed.append(round((perf_counter() - started) * 1000, 1))
        after = client.get(f"{prefix}/cache-metrics")
        after.raise_for_status()
    old, new = before.json().get("layers", {}), after.json().get("layers", {})
    delta = {}
    for layer in ("embedding", "retrieval", "chat"):
        delta[layer] = {field: new.get(layer, {}).get(field, 0) - old.get(layer, {}).get(field, 0)
                        for field in ("hits", "misses", "input_tokens_saved", "output_tokens_saved",
                                      "latency_saved_ms", "api_cost_saved_micro_usd")}
    print(json.dumps({"first_request_ms": elapsed[0],
        "repeat_mean_ms": round(mean(elapsed[1:]), 1), "all_request_ms": elapsed,
        "cache_counter_delta": delta}, indent=2))


if __name__ == "__main__":
    main()
