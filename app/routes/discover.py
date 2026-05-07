import logging
from typing import Literal

from fastapi import APIRouter, Query

from app.services import get_tmdb_service

router = APIRouter(prefix="/discover", tags=["discover"])
logger = logging.getLogger(__name__)


@router.get("/trending")
async def trending(
    country: str = Query(default="IN", max_length=2),
):
    """Trending movies this week from TMDB."""
    tmdb = get_tmdb_service()
    movies = await tmdb.fetch_trending(limit=20)
    return {"results": [_movie_dict(m, country) for m in movies]}


@router.get("/new-releases")
async def new_releases(
    country: str = Query(default="IN", max_length=2),
):
    """Movies released in the past 90 days, sorted by popularity."""
    tmdb = get_tmdb_service()
    movies = await tmdb.fetch_new_releases(limit=20)
    return {"results": [_movie_dict(m, country) for m in movies]}


@router.get("/top-rated")
async def top_rated(
    country: str = Query(default="IN", max_length=2),
):
    """All-time top rated movies."""
    tmdb = get_tmdb_service()
    movies = await tmdb.fetch_top_rated(limit=20)
    return {"results": [_movie_dict(m, country) for m in movies]}


@router.get("/genre/{genre_name}")
async def by_genre(
    genre_name: str,
    country: str = Query(default="IN", max_length=2),
):
    """Movies for a specific genre (used for personalized rows)."""
    tmdb = get_tmdb_service()
    movies = await tmdb.discover_movies_by_genre(genre_name, limit=20)
    return {"results": [_movie_dict(m, country) for m in movies]}


def _movie_dict(movie, country: str) -> dict:
    return {
        "id":              movie.id,
        "tmdbId":          movie.tmdb_id,
        "title":           movie.title,
        "year":            movie.year,
        "posterUrl":       movie.poster_url,
        "backdropUrl":     movie.backdrop_url,
        "genres":          movie.genres,
        "language":        movie.language,
        "rating":          movie.rating,
        "synopsis":        movie.synopsis,
        "trailerKey":      movie.trailer_key,
        "trailerUrl":      movie.trailer_url,
        "runtimeMinutes":  movie.runtime_minutes,
    }