"""
Root-level conftest.py — runs before any test file is imported.

Sets dummy environment variables so modules that guard against missing keys
at import time (like GBIF.py checking OPENAI_API_KEY) don't raise during
the test suite.  Real integration tests that need live keys should be marked
with @pytest.mark.integration and skipped in CI unless secrets are present.
"""
import os

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-ci")
os.environ.setdefault("MAX_SPECIES_FOR_AI", "3")
os.environ.setdefault("TURNSTILE_SECRET_KEY", "test-turnstile-key")
os.environ.setdefault("MAPTILER_API_KEY", "test-maptiler-key")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:5173")
