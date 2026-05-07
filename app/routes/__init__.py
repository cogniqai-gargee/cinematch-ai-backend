from .chat          import router as chat_router
from .discover      import router as discover_router
from .health        import router as health_router
from .movies        import router as movies_router
from .recommendations import router as recommendations_router
from .saved_movies  import router as saved_movies_router

__all__ = [
    "chat_router",
    "discover_router",
    "health_router",
    "movies_router",
    "recommendations_router",
    "saved_movies_router",
]