from app.routes.chat import router as chat_router
from app.routes.health import router as health_router
from app.routes.recommendations import router as recommendations_router
from app.routes.saved_movies import router as saved_movies_router

__all__ = [
    "chat_router",
    "health_router",
    "recommendations_router",
    "saved_movies_router",
]
