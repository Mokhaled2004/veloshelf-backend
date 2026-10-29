"""
Redis cache utility for VeloShelf.

Usage
-----
from app.core.cache import get_cached, set_cached, build_key

key = build_key("osa_summary", country="Lebanon", channel="MT")
cached = get_cached(key)
if cached is not None:
    return cached

result = expensive_db_query()
set_cached(key, result)
return result
"""

import json
import hashlib
import logging
from typing import Any, Optional

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis client — lazy singleton, connection pool-backed
# ---------------------------------------------------------------------------
_redis_client: Optional[redis.Redis] = None


def get_redis() -> Optional[redis.Redis]:
    """
    Return a Redis client, or None if Redis is unavailable.
    Never raises — cache failures are always silent so the API keeps working.
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()
        _redis_client = client
        logger.info("Redis connected at %s", settings.REDIS_URL)
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — caching disabled.", exc)
        _redis_client = None
    return _redis_client


# ---------------------------------------------------------------------------
# Key builder
# ---------------------------------------------------------------------------

def build_key(endpoint: str, **kwargs: Any) -> str:
    """
    Build a stable, collision-resistant cache key.

    The kwargs are sorted so that build_key("x", a=1, b=2) and
    build_key("x", b=2, a=1) produce the same key.

    The key is prefixed with "vs:avail:" so it's easy to flush just the
    availability namespace:  SCAN 0 MATCH vs:avail:* / DEL ...
    """
    # Normalise list/None values so the same filter set always maps to the same hash
    normalised = {
        k: sorted(v) if isinstance(v, list) else v
        for k, v in sorted(kwargs.items())
        if v is not None and v != [] and v != ""
    }
    payload = json.dumps(normalised, sort_keys=True, default=str)
    digest = hashlib.sha1(payload.encode()).hexdigest()[:16]
    return f"vs:avail:{endpoint}:{digest}"


# ---------------------------------------------------------------------------
# Get / set helpers
# ---------------------------------------------------------------------------

def get_cached(key: str) -> Optional[Any]:
    """Return deserialised value or None on miss / error."""
    client = get_redis()
    if client is None:
        return None
    try:
        raw = client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.debug("Cache GET error for key %s: %s", key, exc)
        return None


def set_cached(key: str, value: Any, ttl: Optional[int] = None) -> None:
    """Serialise and store value with TTL (defaults to AVAILABILITY_CACHE_TTL)."""
    client = get_redis()
    if client is None:
        return
    try:
        ttl = ttl if ttl is not None else settings.AVAILABILITY_CACHE_TTL
        client.setex(key, ttl, json.dumps(value, default=str))
    except Exception as exc:
        logger.debug("Cache SET error for key %s: %s", key, exc)


def invalidate_availability() -> None:
    """
    Flush all availability cache keys.
    Call this after an ETL refresh so users see fresh data immediately.
    """
    client = get_redis()
    if client is None:
        return
    try:
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor, match="vs:avail:*", count=200)
            if keys:
                client.delete(*keys)
            if cursor == 0:
                break
        logger.info("Availability cache flushed.")
    except Exception as exc:
        logger.warning("Cache flush error: %s", exc)
