"""
Kin Spark Configuration

All environment variables and settings for the Spark AI Rep system.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ==========================================================================
    # APP
    # ==========================================================================
    app_name: str = "Kin Spark"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # ==========================================================================
    # SUPABASE (Spark's own Supabase instance)
    # ==========================================================================
    supabase_url: str
    supabase_service_key: str

    # ==========================================================================
    # ADMIN PORTAL
    # ==========================================================================
    admin_cors_origins: str = "https://app.trykin.ai"
    admin_rate_limit_rpm: int = 60

    # ==========================================================================
    # LLM
    # ==========================================================================
    google_ai_api_key: str  # Gemini 3 Flash
    moonshot_api_key: str | None = None  # Fallback — Kimi K2.5
    groq_api_key: str | None = None  # Pre-flight — Groq Llama

    # Model identifiers (LiteLLM format)
    spark_primary_model: str = "gemini/gemini-3-flash-preview"
    spark_fallback_model: str = "moonshot/kimi-k2.5"
    spark_preflight_model: str = "groq/llama-3.1-8b-instant"

    # ==========================================================================
    # EMBEDDINGS (OpenAI)
    # ==========================================================================
    openai_api_key: str
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 2000

    # ==========================================================================
    # SPARK BEHAVIOR
    # ==========================================================================
    spark_max_turns_default: int = 20
    spark_wind_down_turns: int = 3
    spark_min_turns_before_winddown: int = 5
    spark_context_turns: int = 8
    spark_rate_limit_rpm: int = 30
    spark_max_doc_chunks: int = 5
    spark_doc_match_threshold: float = 0.3
    spark_session_timeout_minutes: int = 30

    # ==========================================================================
    # CORS
    # ==========================================================================
    # Spark uses wildcard CORS (publishable key auth, widget embeds anywhere)
    cors_origins: str = "*"

    # ==========================================================================
    # SERVER
    # ==========================================================================
    host: str = "0.0.0.0"
    port: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
