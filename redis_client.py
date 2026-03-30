"""
redis_client.py

Thin wrapper around the Redis client providing a lazy singleton connection
and simple get/set/delete helpers with JSON serialization.

All public functions swallow exceptions and return a safe default (None / False)
so that a Redis outage degrades gracefully to a no-cache state rather than
taking down the application.
"""

import json
import logging
import os

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    """Return the module-level Redis client, creating it on first call."""
    global _client
    if _client is None:
        _client = redis.from_url(REDIS_URL, decode_responses=True)
    return _client


def cache_get(key: str):
    """
    Return the deserialized value stored at *key*, or None on a cache miss
    or any Redis / network error.
    """
    try:
        raw = get_client().get(key)
        return json.loads(raw) if raw is not None else None
    except Exception as exc:
        logger.error("cache_get(%r) failed: %s", key, exc)
        return None


def cache_set(key: str, value, ttl: int) -> bool:
    """
    Serialize *value* as JSON and store it under *key* with a TTL in seconds.
    Returns True on success, False on any error.
    """
    try:
        get_client().setex(key, ttl, json.dumps(value))
        return True
    except Exception as exc:
        logger.error("cache_set(%r) failed: %s", key, exc)
        return False


def cache_delete(key: str) -> bool:
    """Delete *key*. Returns True on success, False on any error."""
    try:
        get_client().delete(key)
        return True
    except Exception as exc:
        logger.error("cache_delete(%r) failed: %s", key, exc)
        return False
