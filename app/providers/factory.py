import logging

from app.config import Settings
from app.providers.base import LLMProvider, LLMUnavailableError
from app.providers.openrouter_gemma import OpenRouterGemmaProvider

logger = logging.getLogger(__name__)


def create_llm_provider(settings: Settings) -> LLMProvider:
    if settings.has_gemma_credentials:
        logger.info("[LLM] Provider: OpenRouter")
        return OpenRouterGemmaProvider(settings)

    logger.error("[LLM] Request failed: GEMMA_API_KEY is not configured")
    raise LLMUnavailableError()
