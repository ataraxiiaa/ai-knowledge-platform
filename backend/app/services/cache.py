"""Workspace-scoped, fail-open Redis cache and daily savings counters."""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import hmac
import json
import logging
import math
from time import monotonic, perf_counter
from typing import Any
import uuid

from redis import Redis, RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)
_unavailable_until = 0.0
LAYERS = ("embedding", "retrieval", "chat")


@lru_cache(maxsize=1)
def _redis() -> Redis:
    return Redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.2,
                          socket_timeout=0.2)


def _client() -> Redis | None:
    if not settings.CACHE_ENABLED or monotonic() < _unavailable_until:
        return None
    try:
        return _redis()
    except RedisError as exc:
        _offline(exc)
        return None


def _offline(exc: Exception) -> None:
    global _unavailable_until
    _unavailable_until = monotonic() + 5
    logger.warning("Cache unavailable (%s); continuing without cache", type(exc).__name__)


def key(layer: str, workspace_id: uuid.UUID, *parts: Any) -> str:
    digest = hmac.new(settings.SECRET_KEY.encode(),
        json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str).encode(),
        hashlib.sha256).hexdigest()
    return f"cache:v1:{layer}:{workspace_id}:{digest}"


def _metric_key(layer: str, workspace_id: uuid.UUID) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"cache:v1:metrics:{workspace_id}:{day}:{layer}"


def _prices(provider: str | None, model: str | None) -> tuple[float, float] | None:
    try:
        mapping = json.loads(settings.CACHE_MODEL_PRICES_JSON)
        price = mapping.get(f"{provider}:{model}")
        if not isinstance(price, dict):
            return None
        values = float(price["input"]), float(price["output"])
        return values if all(math.isfinite(value) and value >= 0 for value in values) else None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def _record(client: Redis, layer: str, workspace_id: uuid.UUID, values: dict[str, int]) -> None:
    try:
        metric_key = _metric_key(layer, workspace_id)
        pipe = client.pipeline(transaction=False)
        for field, amount in values.items():
            if amount:
                pipe.hincrby(metric_key, field, amount)
        pipe.expire(metric_key, 172800)
        pipe.execute()
    except RedisError as exc:
        _offline(exc)


def get(layer: str, workspace_id: uuid.UUID, cache_key: str) -> dict | None:
    client = _client()
    if client is None:
        return None
    started = perf_counter()
    try:
        raw = client.get(cache_key)
        if raw is None:
            _record(client, layer, workspace_id, {"misses": 1})
            return None
        if len(raw) > settings.CACHE_MAX_VALUE_BYTES:
            client.delete(cache_key)
            _record(client, layer, workspace_id, {"misses": 1})
            return None
        entry = json.loads(raw)
        if not isinstance(entry, dict) or "data" not in entry:
            raise ValueError("invalid cache entry")
        read_ms = (perf_counter() - started) * 1000
        values = {"hits": 1, "latency_saved_ms": max(0, round(entry.get("miss_ms", 0) - read_ms))}
        if layer == "embedding":
            values["embedding_calls_saved"] = 1
        if layer == "chat":
            usage = entry.get("usage") or {}
            input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
            if isinstance(input_tokens, int) and isinstance(output_tokens, int):
                values["input_tokens_saved"] = input_tokens
                values["output_tokens_saved"] = output_tokens
                prices = _prices(entry.get("provider"), entry.get("model"))
                if prices:
                    values["api_cost_saved_micro_usd"] = round(
                        input_tokens * prices[0] + output_tokens * prices[1])
                    values["cost_known_hits"] = 1
                else:
                    values["cost_unknown_hits"] = 1
            else:
                values["cost_unknown_hits"] = 1
        _record(client, layer, workspace_id, values)
        return entry
    except (RedisError, ValueError, TypeError, AttributeError) as exc:
        if isinstance(exc, RedisError):
            _offline(exc)
        else:
            try:
                client.delete(cache_key)
            except RedisError as delete_exc:
                _offline(delete_exc)
        return None


def put(layer: str, workspace_id: uuid.UUID, cache_key: str, data: Any,
        ttl: int, miss_ms: float, *, usage: dict | None = None,
        provider: str | None = None, model: str | None = None) -> None:
    client = _client()
    if client is None:
        return
    entry = {"data": data, "miss_ms": miss_ms, "usage": usage,
             "provider": provider, "model": model}
    try:
        encoded = json.dumps(entry, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError):
        return
    if len(encoded) > settings.CACHE_MAX_VALUE_BYTES:
        return
    try:
        client.set(cache_key, encoded, ex=ttl)
    except RedisError as exc:
        _offline(exc)


def discard(cache_key: str) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.delete(cache_key)
    except RedisError as exc:
        _offline(exc)


def metrics(workspace_id: uuid.UUID) -> dict:
    client = _client()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if client is None:
        return {"date_utc": day, "available": False, "layers": {}}
    try:
        layers = {}
        for layer in LAYERS:
            raw = client.hgetall(_metric_key(layer, workspace_id))
            counts = {key.decode(): int(value) for key, value in raw.items()}
            hits, misses = counts.get("hits", 0), counts.get("misses", 0)
            counts["hit_rate"] = hits / (hits + misses) if hits + misses else 0.0
            counts["estimated_api_cost_saved_usd"] = (
                counts.get("api_cost_saved_micro_usd", 0) / 1_000_000
                if counts.get("cost_known_hits", 0) else None)
            layers[layer] = counts
        return {"date_utc": day, "available": True, "layers": layers}
    except RedisError as exc:
        _offline(exc)
        return {"date_utc": day, "available": False, "layers": {}}

