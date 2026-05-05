from abc import ABC, abstractmethod
from typing import Any

from app.schemas.chat import ChatMessage
from app.schemas.movies import MovieCandidate, Recommendation


class LLMUnavailableError(RuntimeError):
    def __init__(
        self,
        message: str = "AI recommendation engine is currently unavailable",
        error: str = "LLM_UNAVAILABLE",
    ):
        super().__init__(message)
        self.error = error
        self.message = message


class LLMRateLimitedError(LLMUnavailableError):
    def __init__(
        self,
        message: str = "The recommendation engine is busy right now. Please try again in a few seconds.",
    ):
        super().__init__(message=message, error="RATE_LIMITED")


class BaseLLMProvider(ABC):
    name: str

    @abstractmethod
    async def chat(
        self,
        message: str,
        preferences: dict[str, Any],
        history: list[ChatMessage] | None = None,
        session_key: str | None = None,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    async def rank_recommendations(
        self,
        preferences: dict[str, Any],
        candidates: list[MovieCandidate],
        limit: int,
        history: list[ChatMessage] | None = None,
        session_key: str | None = None,
    ) -> list[Recommendation]:
        raise NotImplementedError


LLMProvider = BaseLLMProvider
