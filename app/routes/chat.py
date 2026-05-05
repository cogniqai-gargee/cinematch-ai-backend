import logging

from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.providers import LLMRateLimitedError, LLMUnavailableError
from app.schemas import ChatMessage, ChatRequest, ChatResponse
from app.schemas.movies import RecommendationResponse
from app.services import get_preference_service, get_recommendation_service

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


def llm_error_response(exc: LLMUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error": exc.error, "message": exc.message})


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse | JSONResponse:
    conversation_id = payload.conversation_id or str(uuid4())
    try:
        recommendation_service = get_recommendation_service()
    except (LLMRateLimitedError, LLMUnavailableError) as exc:
        return llm_error_response(exc)

    preference_service = get_preference_service()

    user_message = ChatMessage(role="user", content=payload.message)
    appended_history = [*payload.history, user_message]
    user_texts = [item.content for item in payload.history if item.role == "user"] + [payload.message]
    extracted_preferences = preference_service.extract(user_texts)
    decision = preference_service.assess(payload.message, extracted_preferences)
    extracted_preferences["conversation_decision"] = decision
    logger.info("Conversation decision: %s", decision)

    if decision["ready"]:
        try:
            response = await recommendation_service.create_from_preferences(
                preferences=extracted_preferences,
                conversation_id=conversation_id,
                limit=5,
                history=appended_history,
            )
        except (LLMRateLimitedError, LLMUnavailableError) as exc:
            return llm_error_response(exc)
        extracted_preferences = response.preferences
        extracted_preferences["recommendation_count"] = len(response.recommendations)
        extracted_preferences["recommendation_titles"] = [
            recommendation.movie.title for recommendation in response.recommendations[:5]
        ]
    else:
        logger.info("Skipping TMDB fetch until follow-up is answered")
        response = RecommendationResponse(
            conversation_id=conversation_id,
            preferences=extracted_preferences,
            recommendations=[],
        )

    try:
        assistant_text = await recommendation_service.llm_provider.chat(
            payload.message,
            response.preferences,
            appended_history,
            session_key=response.conversation_id,
        )
    except (LLMRateLimitedError, LLMUnavailableError) as exc:
        return llm_error_response(exc)
    assistant_message = ChatMessage(role="assistant", content=assistant_text)

    return ChatResponse(
        conversation_id=response.conversation_id,
        messages=[*appended_history, assistant_message],
        extracted_preferences=extracted_preferences,
        ai_message=assistant_message,
        assistant_message=assistant_message,
        recommendations=response.recommendations,
    )
