"""
Root-level conftest.py — runs before any test file is imported.

Sets dummy environment variables so modules that guard against missing keys
at import time (like GBIF.py checking OPENAI_API_KEY) don't raise during
the test suite.  Real integration tests that need live keys should be marked
with @pytest.mark.integration and skipped in CI unless secrets are present.

Also provides a `fake_redis` autouse fixture that replaces the Redis client
with an in-memory FakeRedis instance for every test, so no real Redis server
is required in CI or local development.
"""
import os

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-ci")
os.environ.setdefault("MAX_SPECIES_FOR_AI", "3")
os.environ.setdefault("TURNSTILE_SECRET_KEY", "test-turnstile-key")
os.environ.setdefault("MAPTILER_API_KEY", "test-maptiler-key")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:5173")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

import fakeredis
import pytest
import redis_client


@pytest.fixture(autouse=True)
def fake_redis():
    """
    Replace the module-level Redis client with a FakeRedis instance before
    each test and flush + reset it afterwards.  This means:
      - No real Redis server is needed in CI or local dev.
      - Each test starts with a clean cache.
      - All redis_client helpers (cache_get, cache_set, …) work normally.
    """
    fake = fakeredis.FakeRedis(decode_responses=True)
    redis_client._client = fake
    yield fake
    fake.flushall()
    redis_client._client = None
