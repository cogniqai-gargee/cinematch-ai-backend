from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.providers import LLMRateLimitedError, LLMUnavailableError
from app.schemas import Recommendation, RecommendationRequest, RecommendationResponse
from app.services import get_recommendation_service

router = APIRouter(tags=["recommendations"])


def llm_error_response(exc: LLMUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error": exc.error, "message": exc.message})


@router.post("/recommendations", response_model=RecommendationResponse)
async def create_recommendations(payload: RecommendationRequest) -> RecommendationResponse | JSONResponse:
    try:
        return await get_recommendation_service().create_from_preferences(
            preferences=payload.preferences,
            conversation_id=payload.conversation_id,
            message=payload.message,
            limit=payload.limit,
        )
    except (LLMRateLimitedError, LLMUnavailableError) as exc:
        return llm_error_response(exc)


@router.get("/recommendations", response_model=list[Recommendation])
async def list_recommendations() -> list[Recommendation]:
    return get_recommendation_service().list_recent()
