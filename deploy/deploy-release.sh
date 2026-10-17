#!/bin/sh
set -eu

: "${IMAGE_TAG:?Set IMAGE_TAG to a tested sha-* tag}"
: "${GHCR_REPOSITORY:?Set GHCR_REPOSITORY}"
case "$IMAGE_TAG" in
  sha-[0-9a-f]*) ;;
  *) echo "IMAGE_TAG must be a sha-* image tag" >&2; exit 2 ;;
esac
test -f .env.production
test -d deploy/secrets

compose() {
  docker compose --env-file .env.production \
    -f docker-compose.production.yml -f docker-compose.production.images.yml "$@"
}

previous=""
if test -f .deployed-image-tag; then
  previous="$(cat .deployed-image-tag)"
fi

rollback() {
  if test -n "$previous"; then
    echo "Rolling application images back to $previous" >&2
    IMAGE_TAG="$previous"; export IMAGE_TAG
    compose up -d --no-build --wait backend frontend worker research_worker dispatcher caddy || true
  else
    echo "No previous release is recorded; inspect services and restore the pre-migration backup if needed" >&2
  fi
}

echo "Pulling $IMAGE_TAG"
compose pull backend frontend worker research_worker dispatcher migrate backup
compose up -d --no-build --wait db redis
echo "Backing up the current database before migration"
compose --profile backup run --rm backup
echo "Applying migrations"
compose run --rm migrate
echo "Starting tested images"
if ! compose up -d --no-build --wait backend frontend worker research_worker dispatcher caddy; then
  rollback
  exit 1
fi

domain="$(sed -n 's/^APP_DOMAIN=//p' .env.production | tail -n 1)"
test -n "$domain"
attempt=0
until curl --fail --silent --show-error --max-time 10 "https://$domain/api/ready" >/dev/null; do
  attempt=$((attempt + 1))
  if test "$attempt" -ge 12; then
    echo "Production health check failed after deployment" >&2
    rollback
    exit 1
  fi
  sleep 5
done
printf '%s\n' "$IMAGE_TAG" > .deployed-image-tag
echo "Deployment healthy: $IMAGE_TAG"
