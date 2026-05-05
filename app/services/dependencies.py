from functools import lru_cache

from app.config import get_settings
from app.providers import create_llm_provider
from app.services.preference_extraction import PreferenceExtractionService
from app.services.recommendation_service import RecommendationService
from app.services.saved_movies_service import SavedMoviesService
from app.services.supabase_service import SupabaseService
from app.services.tmdb_service import TMDBService


@lru_cache
def get_preference_service() -> PreferenceExtractionService:
    return PreferenceExtractionService()


@lru_cache
def get_tmdb_service() -> TMDBService:
    return TMDBService(get_settings())


@lru_cache
def get_recommendation_service() -> RecommendationService:
    settings = get_settings()
    return RecommendationService(
        llm_provider=create_llm_provider(settings),
        preference_service=get_preference_service(),
        tmdb_service=get_tmdb_service(),
    )


@lru_cache
def get_saved_movies_service() -> SavedMoviesService:
    return SavedMoviesService()


@lru_cache
def get_supabase_service() -> SupabaseService:
    return SupabaseService(get_settings())
