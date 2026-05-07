import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services import get_tmdb_service

router = APIRouter(prefix="/movies", tags=["movies"])
logger = logging.getLogger(__name__)


@router.get("/{tmdb_id}/watch-providers")
async def watch_providers(
    tmdb_id: int,
    country: str = Query(default="IN", max_length=2),
):
    """
    Returns streaming/rental/purchase providers for a movie in the given country.
    Uses TMDB Watch Providers API.
    """
    tmdb = get_tmdb_service()
    providers = await tmdb.fetch_watch_providers(tmdb_id, country=country)
    return {"tmdbId": tmdb_id, "country": country, "providers": providers}