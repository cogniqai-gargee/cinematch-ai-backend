from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # TMDB
    tmdb_api_key: str = ""

    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""

    # Google AI Studio — two separate project keys for doubled free quota
    gemma_primary_api_key: str = ""    # reads GEMMA_PRIMARY_API_KEY from env
    gemma_fallback_api_key: str = ""   # reads GEMMA_FALLBACK_API_KEY from env

    # Legacy fields kept for backwards compat (no longer used for LLM calls)
    gemma_api_url: str = "https://generativelanguage.googleapis.com/v1beta/models"
    gemma_api_key: str = ""
    gemma_model: str = "gemma-4-31b-it"

    @property
    def has_tmdb_credentials(self) -> bool:
        return bool(self.tmdb_api_key)

    @property
    def has_ai_credentials(self) -> bool:
        return bool(self.gemma_primary_api_key)
    
@lru_cache
def get_settings() -> Settings:
    return Settings()