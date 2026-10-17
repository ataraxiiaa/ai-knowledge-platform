# Phase 6, step 2: Redis and worker infrastructure

This step adds infrastructure only. Upload still runs ingestion synchronously
and returns 201. No outbox, document jobs, schema migration or polling is enabled
until later approved steps.

## Implemented

- RQ 2.12.0 and redis-py 6.4.0 are locked in `backend/uv.lock`; Docker's generated
  `requirements.txt` is exported from the same lock. Existing dependencies were
  not upgraded. The lock also adds croniter, python-dateutil and six.
- `app.services.queue` creates lazy Redis connections and a JSON-serialized
  `ingestion` queue. Imports do not connect to Redis. Connection attempts have
  bounded timeouts; RQ adjusts the worker's blocking-pop socket timeout itself.
- `python -m app.worker` runs one Linux worker process, which uses RQ's forked
  job execution. It does not preload the embedding model or open database sessions.
  `--burst` drains available work and exits. Native Windows startup explicitly
  directs developers to Docker rather than using an incompatible worker.
- Worker health checks verify that this container's named worker has a recent
  Redis heartbeat. A successful Redis ping alone does not prove worker health.
  Each worker container has its own hostname; run one worker per container.
- Compose adds Redis 7.4 Alpine with AOF persistence and `noeviction`, an internal
  network endpoint with no published Redis port, and the worker using the same
  backend build and `/data` volume as the API. Worker health replaces the image's
  inherited HTTP check. The worker does not run migrations.
- `verify_queue.py` writes a unique synthetic file, enqueues its UUID, and checks
  that another process/container reads matching bytes. The JSON result reports
  hostname/PID and SHA-256. Probe files and completed jobs are cleaned up. There
  is no public enqueue endpoint or exposure of arbitrary function names.

The Redis image tag receives patch updates; it is not digest-pinned. AOF is an
availability measure, not an exactly-once guarantee or substitute for step 3's
durable outbox. No retry scheduler is started at this stage.

## Run with the application stack

Set a generated SECRET_KEY in root `.env`, then from the repository root:

```sh
docker compose up -d --build redis worker
docker compose run --rm --no-deps worker python scripts/verify_queue.py
docker compose exec worker python -m app.worker --healthcheck
docker compose logs --tail 50 worker
```

The probe command overrides the worker command and uses the same volume; it does
not need PostgreSQL or an LLM. It demonstrates the same queue helper future API
dispatch will use, not an already asynchronous upload endpoint.

Configuration: `REDIS_URL` (hidden from Settings repr), `RQ_QUEUE_NAME=ingestion`,
and `RQ_JOB_TIMEOUT=900`. Compose uses `redis://redis:6379/0`. The example local
URL points to localhost but Compose deliberately publishes no Redis port; host
development requires an explicit loopback-only mapping or a separate local Redis.
Redis is internal trusted infrastructure; JSON serialization does not make
unauthorized access to the queue safe.

## Isolated verification

`docker-compose.queue-test.yml` reuses the actual worker and Redis definitions
with separate project volumes, a test-only key and an unused in-memory SQLite URL.
No application database or host port is involved. In PowerShell, set a temporary
test-only SECRET_KEY for Compose interpolation of the referenced base file:

```powershell
$env:SECRET_KEY='queue-smoke-only-not-for-deployment-0123456789'
docker build -t knowledge-phase6-worker-check ./backend
docker compose -p phase6-step2-check -f docker-compose.queue-test.yml up -d redis worker
docker compose -p phase6-step2-check -f docker-compose.queue-test.yml run --rm --no-deps probe
docker compose -p phase6-step2-check -f docker-compose.queue-test.yml exec worker python -m app.worker --healthcheck
```

After verification, remove only this disposable project's resources:

```sh
docker compose -p phase6-step2-check -f docker-compose.queue-test.yml down --volumes
```

Do not use that volume-removal command against the application project.

## Verification results (2026-10-17)

The Linux Python 3.12 backend image built successfully from exported locked
requirements. Both Compose configurations validated. A real JSON probe ran in
a different container/process and verified the SHA-256 of the producer's shared
file. The worker's own heartbeat healthcheck passed.

With the worker stopped, the queue contained one pending probe. A graceful Redis
restart preserved that pending job (queue length remained one); starting the
worker then completed the probe. The first restart exercise exposed a polling
disconnect in the test harness; bounded reconnect polling was added and the
repeat passed. This tests a graceful Redis restart, not loss of Redis data or
recovery of a killed ingestion job. Those cases remain for later steps.

The disposable test containers, network and volumes were removed afterward.
Existing application services and databases were not modified. Dependency-lock
validation passed; frontend files were unchanged, so no frontend checks were run.
All 129 backend tests passed, including five new queue/health tests. The existing
Starlette/httpx deprecation warning remains. `git diff --check` passed.

## Review boundary

Step 3 will add migrations, the durable dispatcher, document worker execution and
202 acceptance. It must also establish migration-before-consumer startup ordering
and preserve atomic ready publication and deletion safety before enabling jobs.
Step 2 stops for approval before that work.
