"""
Test configuration — sets required env vars before any imports.
"""

import os

# Set dummy env vars so Settings() doesn't fail during test collection.
# These are never used for real calls — all external services are mocked.
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("GOOGLE_AI_API_KEY", "test-google-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
