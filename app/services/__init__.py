from app.services.dependencies import (
    get_preference_service,
    get_recommendation_service,
    get_saved_movies_service,
    get_supabase_service,
    get_tmdb_service,
)
from app.services.preference_extraction import PreferenceExtractionService
from app.services.recommendation_service import RecommendationService
from app.services.saved_movies_service import (
    InMemorySavedMoviesRepository,
    SavedMoviesRepository,
    SavedMoviesService,
)
from app.services.supabase_service import SupabaseService
from app.services.tmdb_service import TMDBService

__all__ = [
    "PreferenceExtractionService",
    "RecommendationService",
    "InMemorySavedMoviesRepository",
    "SavedMoviesRepository",
    "SavedMoviesService",
    "SupabaseService",
    "TMDBService",
    "get_preference_service",
    "get_recommendation_service",
    "get_saved_movies_service",
    "get_supabase_service",
    "get_tmdb_service",
]
