from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    tmdb_api_key: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    gemma_api_url: str = "https://openrouter.ai/api/v1/chat/completions"
    gemma_api_key: str = ""
    gemma_model: str = "google/gemma-4-31b-it:free"

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def has_gemma_credentials(self) -> bool:
        return bool(self.gemma_api_key and self.gemma_api_url and self.gemma_model)

    @property
    def has_supabase_credentials(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def has_tmdb_credentials(self) -> bool:
        return bool(self.tmdb_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
