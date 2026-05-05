import logging
from typing import Any
from uuid import uuid4

from app.providers.base import LLMProvider
from app.schemas.chat import ChatMessage
from app.schemas.movies import Recommendation, RecommendationResponse
from app.services.preference_extraction import PreferenceExtractionService
from app.services.tmdb_service import TMDBService

logger = logging.getLogger(__name__)


class RecommendationService:
    def __init__(
        self,
        llm_provider: LLMProvider,
        preference_service: PreferenceExtractionService,
        tmdb_service: TMDBService,
    ):
        self.llm_provider = llm_provider
        self.preference_service = preference_service
        self.tmdb_service = tmdb_service
        self._history: list[Recommendation] = []

    async def create_from_preferences(
        self,
        preferences: dict[str, Any],
        conversation_id: str | None = None,
        message: str | None = None,
        limit: int = 5,
        history: list[ChatMessage] | None = None,
    ) -> RecommendationResponse:
        response_conversation_id = conversation_id or str(uuid4())
        merged_preferences = dict(preferences)
        if message:
            merged_preferences.update(self.preference_service.extract([message]))

        candidates = await self.tmdb_service.fetch_candidates(merged_preferences, limit=max(limit, 5))

        logger.info("Extracted preferences: %s", merged_preferences)
        logger.info("TMDB query used: %s", self.tmdb_service.last_query)
        logger.info("TMDB candidates count: %s", len(candidates))
        if not candidates:
            merged_preferences["recommendation_error"] = (
                "Movie results are temporarily unavailable. Please try again in a moment."
            )
            logger.warning("No TMDB candidates available; skipping LLM ranking")
            return RecommendationResponse(
                conversation_id=response_conversation_id,
                preferences=merged_preferences,
                recommendations=[],
            )

        recommendations = await self.llm_provider.rank_recommendations(
            merged_preferences,
            candidates,
            limit,
            history,
            session_key=response_conversation_id,
        )
        provider_used = recommendations[0].provider if recommendations else self.llm_provider.name
        logger.info("Recommendation provider used: %s", provider_used)
        self._history = recommendations + self._history

        return RecommendationResponse(
            conversation_id=response_conversation_id,
            preferences=merged_preferences,
            recommendations=recommendations,
        )

    async def create_from_chat(
        self,
        message: str,
        history: list[ChatMessage],
        conversation_id: str | None,
        limit: int = 5,
    ) -> RecommendationResponse:
        texts = [item.content for item in history if item.role == "user"] + [message]
        preferences = self.preference_service.extract(texts)
        ranking_history = [*history, ChatMessage(role="user", content=message)]
        session_key = conversation_id or str(uuid4())
        return await self.create_from_preferences(
            preferences=preferences,
            conversation_id=session_key,
            message=message,
            limit=limit,
            history=ranking_history,
        )

    def list_recent(self) -> list[Recommendation]:
        return self._history[:20]
