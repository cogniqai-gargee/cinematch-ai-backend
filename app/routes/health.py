from fastapi import APIRouter

from app.config import get_settings
from app.services import get_supabase_service

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    supabase_status = get_supabase_service().status()

    return {
        "status": "ok",
        "service": "cinematch-ai-backend",
        "integrations": {
            "tmdb_configured": settings.has_tmdb_credentials,
            "gemma_configured": settings.has_gemma_credentials,
            "supabase": supabase_status,
        },
    }
