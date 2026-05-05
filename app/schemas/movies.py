from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class MovieCandidate(BaseModel):
    id: str
    title: str
    year: int | None = None
    genres: list[str] = Field(default_factory=list)
    runtime_minutes: int | None = None
    language: str | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    synopsis: str | None = None
    overview: str | None = None
    rating: float | None = None
    tmdb_id: int | None = None
    trailer_key: str | None = None
    trailer_url: str | None = None
    trailer_source: str | None = None
    is_fallback: bool = False


class Recommendation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    movie: MovieCandidate
    rank: int
    match_score: int = Field(ge=0, le=100)
    reason: str
    watch_context: str | None = None
    provider: str = "openrouter-gemma"
    model: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RecommendationRequest(BaseModel):
    conversation_id: str | None = None
    message: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=5, ge=1, le=10)


class RecommendationResponse(BaseModel):
    conversation_id: str
    preferences: dict[str, Any]
    recommendations: list[Recommendation]


class SavedMovieCreate(BaseModel):
    movie: MovieCandidate
    reason: str | None = None
    match_score: int | None = Field(default=None, ge=0, le=100)


class SavedMovie(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    movie: MovieCandidate
    reason: str | None = None
    match_score: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
