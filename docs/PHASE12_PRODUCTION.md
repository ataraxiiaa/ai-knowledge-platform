# Production deployment

This deployment targets one Linux VPS with Docker Compose, Caddy, PostgreSQL, Redis, Next.js, FastAPI, and separate ingestion/research workers. It is separate from the local `docker-compose.yml`. Only Caddy publishes ports. PDFs and database backups require **off-server S3-compatible buckets**. Provision those buckets before startup, enable versioning and retention on the backup bucket, and use credentials scoped to the necessary objects. The local model service is optional; use a reachable external model API otherwise.

## Prepare the host

Install Docker Engine and its Compose plugin. Point `APP_DOMAIN`'s DNS record at the host, and allow inbound TCP 80/443 plus UDP 443. Reserve enough RAM for embedding/reranking workloads; adjust Compose memory limits to the VPS. Keep the repository at `/opt/ai-knowledge-platform` if using the sample systemd timer. Create a dedicated deployment user with Docker access. Secure and patch the host through your normal operating process.

Copy `.env.production.example` to `.env.production` and set domain, buckets, region, endpoint, model URL/model names, and providers. Create `deploy/secrets/` with files `db_password`, `redis_password`, `secret_key`, `aws_access_key_id`, `aws_secret_access_key`, `llm_api_key`, `gemini_api_key`. The two model key files may be empty when unused. Generate unique high-entropy DB, Redis, and JWT secrets; set file permissions to owner-only. Never put these values in the env file or commit them. Compose secrets are mounted in each container as files. For an external provider, set its corresponding model key file. The same S3 credential currently serves PDF and backup buckets; grant it only the required bucket permissions.

```sh
docker compose --env-file .env.production -f docker-compose.production.yml config --quiet
docker compose --env-file .env.production -f docker-compose.production.yml build
docker compose --env-file .env.production -f docker-compose.production.yml up -d
curl -fsS "https://$APP_DOMAIN/api/ready"
```

If using local Ollama, add `--profile local-model` to `up`, pull the configured model into the Ollama volume, and set `LLM_MODEL`/routing options. The server needs suitable CPU, RAM, and (if configured) GPU resources. For an external model set `LLM_BASE_URL` to the provider's OpenAI-compatible endpoint or configure Gemini routing. Production frontend calls `/api`; the proxy strips that prefix before forwarding to FastAPI. `GET /api/ready` checks schema and DB connectivity. Caddy obtains and renews TLS certificates with persistent `caddy_data`.

Inspect status and logs with `docker compose --env-file .env.production -f docker-compose.production.yml ps` and `... logs --tail=100 SERVICE`. Logging uses Docker's rotating local driver. Workers/dispatcher have health checks and restart policies. The one-shot migration runs before application services. Set `OTEL_ENABLED=true` and a reachable collector endpoint when connecting the Phase 11 observability stack; its local stack is not exposed by this production file.

## Backups and restore rehearsal

Run a first backup and confirm the printed object key and size verification:

```sh
docker compose --env-file .env.production -f docker-compose.production.yml --profile backup run --rm backup
```

The backup service makes a custom-format `pg_dump`, uploads it to `BACKUP_BUCKET`, and verifies the uploaded object size. This does not by itself prove restoreability. Install the sample service/timer from `deploy/systemd/`, update its `WorkingDirectory` if needed, then `systemctl enable --now ai-knowledge-backup.timer`. Monitor timer failures and configure bucket lifecycle/retention independently. Back up `.env.production` and secret material securely outside the VPS; database archives cannot recover JWT signing keys or S3 PDF objects. Protect the PDF bucket with independent versioning/replication policy.

For a restore rehearsal, **use a disposable PostgreSQL 16 database**, not the live container. Download a chosen archive from the backup bucket with your S3 client and run:

```sh
pg_restore --list database.dump
createdb -h RESTORE_HOST -U RESTORE_USER knowledge_restore
pg_restore --exit-on-error --no-owner -h RESTORE_HOST -U RESTORE_USER -d knowledge_restore database.dump
psql -h RESTORE_HOST -U RESTORE_USER -d knowledge_restore -c 'SELECT count(*) FROM documents;'
```

Rehearse periodically, checking representative documents and PDF objects, before relying on backups. For a real disaster, provision a fresh deployment, restore the selected archive into an empty DB, restore secrets and PDF objects, then start application services. Avoid starting workers against an incomplete restore.

## Updating

Back up first. Review DB migrations, build new images, then run `up -d`. Check `/api/ready`, worker health, and an upload/chat/research flow. Rollback of application images may require DB migration compatibility; restore rehearsals are the recovery path for incompatible migrations. Docker Compose `down -v` destroys local persistent volumes and must never be used on production.
