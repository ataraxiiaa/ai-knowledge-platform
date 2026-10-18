# Phase 15: load testing and production hardening

The benchmark uses a disposable Compose project (`phase15-load`) with local PostgreSQL/pgvector, Redis, one ingestion worker, a research dispatcher, a deterministic OpenAI-compatible model stub with 150 ms response delay, and two small PDFs indexed through the normal API/worker path. Host ports bind to loopback. Never point these scripts at production: they create accounts, documents, and research jobs. The fixture JSON contains a bearer token and is ignored by Git.

From the repository root, with Docker Desktop and `uv` available:

```powershell
docker compose -p phase15-load -f docker-compose.load-test.yml up -d --build
$env:UV_CACHE_DIR = "$PWD\backend\.uv-cache"
cd backend
uv run --locked python scripts/prepare_load_fixture.py --output .test-tmp-phase15/fixture.json
$env:PHASE15_DATABASE_URL = 'postgresql://postgres:phase15-only@127.0.0.1:15432/load_test'
$env:PHASE15_REDIS_URL = 'redis://127.0.0.1:16379/0'
uv run --locked python scripts/load_test.py --fixture .test-tmp-phase15/fixture.json --mode chat --output .test-tmp-phase15/chat.json --docker-project phase15-load
uv run --locked python scripts/load_test.py --fixture .test-tmp-phase15/fixture.json --mode research --job-timeout 600 --output .test-tmp-phase15/research.json --docker-project phase15-load
```

The default ladder is 1, 5, 10, 25, 50, 100 concurrent clients. Each chat client sends three sequential questions; 20% repeat and 80% include a unique suffix. Each research client submits one unique job and polls to terminal status every 2.5 seconds, matching the current frontend. Output paths must be new; the script will not overwrite an earlier run. For a single rung, pass `--levels 100`. To vary research capacity in the disposable stack, run `docker compose -p phase15-load -f docker-compose.load-test.yml up -d --scale research_worker=4 --no-recreate research_worker`. Restore the original scale with `--scale research_worker=1`. The Compose file currently starts four API processes; change its `backend.command` to one process for a controlled baseline, rebuild, and restore it afterward. Stop and remove this **disposable** project with `docker compose -p phase15-load -f docker-compose.load-test.yml down -v --remove-orphans` once results are saved.

The harness reports successful operations per wall-clock second, nearest-rank P50/P95/P99 of **all attempts** (including errors), error type counts, and sampled maximum PostgreSQL connections, Redis queue depth, and container memory. Sampling is every two seconds and can miss shorter peaks. CPU and GPU utilization are not captured; this fixture does not run a real LLM or GPU. Virtual clients share one authenticated workspace and fixture, so they do not model 100 independent tenants or production-sized documents. Results depend on local Docker resources, warm models, and the deterministic stub.

## Recorded local measurements

These runs used one API process and one research worker for the initial chat baseline, then the same topology after the chat transaction fix. The two 100-client chat rungs each attempted 300 requests.

| Chat clients | Baseline throughput/s | Baseline P50/P95/P99 (ms) | Baseline errors | After fix throughput/s | After fix P50/P95/P99 (ms) | After errors |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2.41 | 178 / 218 / 218 | 0 | 1.41 | 176 / 1,079 / 1,079 | 0 |
| 5 | 6.94 | 190 / 290 / 290 | 0 | 6.89 | 189 / 236 / 236 | 0 |
| 10 | 13.93 | 185 / 283 / 295 | 0 | 13.79 | 206 / 299 / 308 | 0 |
| 25 | 35.12 | 312 / 491 / 529 | 0 | 34.89 | 312 / 547 / 578 | 0 |
| 50 | 53.82 | 558 / 1,763 / 2,066 | 0 | 51.84 | 521 / 1,982 / 2,207 | 0 |
| 100 | 7.45 | 921 / 32,942 / 33,247 | 41 | 46.01 | 940 / 4,726 / 5,436 | 0 |

At 100 clients, the baseline had 31 HTTP 500s and 10 connection failures. Backend logs showed SQLAlchemy pool timeout (`size 5`, `overflow 10`, `timeout 30s`). The chat route held a database connection through the model call. It now captures the retrieved evidence and corpus revision, rolls back the read-only transaction, then generates the answer. The maximum sampled database connections at that rung fell from 17 to 7; maximum sampled backend memory fell from about 366 MB to 350 MB. The 1-client after run had a cold-start outlier, so single-rung latency is not a reliable regression signal.

Research was first measured with one API process, one research worker, and **0.5-second polling**. The final run used four API processes, four research workers, and the frontend's **2.5-second polling**. Those differences mean the rows show capacity under each setup, not a controlled estimate of worker-only speedup.

| Research clients | Initial throughput/s | Initial P50/P95/P99 (ms) | Final throughput/s | Final P50/P95/P99 (ms) | Final errors |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.16 | 6,325 / 6,325 / 6,325 | 0.13 | 7,647 / 7,647 / 7,647 | 0 |
| 5 | 0.48 | 6,410 / 10,019 / 10,019 | 0.79 | 5,186 / 5,195 / 5,195 | 0 |
| 10 | 0.45 | 12,783 / 21,551 / 21,551 | 0.97 | 7,740 / 10,326 / 10,326 | 0 |
| 25 | 0.49 | 28,769 / 49,214 / 51,298 | 1.13 | 15,542 / 20,585 / 20,611 | 0 |
| 50 | 0.52 | 50,356 / 92,229 / 95,458 | 1.59 | 18,158 / 28,955 / 31,493 | 0 |
| 100 | 0.43 | 104,678 / 224,495 / 232,121 | 1.59 | 34,114 / 58,036 / 60,694 | 0 |

Initial research had zero failed jobs but a large backlog and a 224-second P95 at 100 clients. Four research workers reduced the final run's P95 to 58 seconds. With four workers but one API process, the 100-client run had API submission and polling failures under database pool pressure; four API processes completed the full ladder without errors. At the final 100-client rung, sampled maxima were 60 queued research entries, 22 PostgreSQL connections, 388 MB in the API container, and about 331 MB in each research worker container. The high queue depth shows that workers remain the throughput limit. Scaling them further would increase database connections, memory, and model-provider demand. Capacity must be sized against the actual host and provider limits before production changes.

The chat fix is included in the application. Production exposes `BACKEND_WORKERS` and `RESEARCH_WORKER_REPLICAS` with defaults of one each; the four/four disposable result is a sizing reference, not a production default. Re-run the ladder after changing prompts, retrieval method, model provider, worker count, or database pool sizing. Compare runs made with the **same** fixture, poll interval, and resource allocation before claiming a speedup.
