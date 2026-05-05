from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.schemas.movies import Recommendation


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    conversation_id: str
    messages: list[ChatMessage]
    extracted_preferences: dict[str, Any]
    ai_message: ChatMessage
    assistant_message: ChatMessage
    recommendations: list[Recommendation] = Field(default_factory=list)
