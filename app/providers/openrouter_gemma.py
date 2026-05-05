import asyncio
import json
import logging
import re
import time
from typing import Any

import httpx

from app.config import Settings
from app.providers.base import BaseLLMProvider, LLMRateLimitedError, LLMUnavailableError
from app.schemas.chat import ChatMessage
from app.schemas.movies import MovieCandidate, Recommendation

logger = logging.getLogger(__name__)
OPENROUTER_GEMMA_MODEL = "google/gemma-4-31b-it:free"
LLM_COOLDOWN_SECONDS = 3.0
RATE_LIMIT_RETRY_SECONDS = 2.0


class OpenRouterGemmaProvider(BaseLLMProvider):
    name = "openrouter-gemma"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cooldown_locks : dict[str, asyncio.Lock] = {}
        self._last_request_at_by_session: dict[str, float] = {}
        logger.info("[LLM] Provider: OpenRouter")
        logger.info("[LLM] Model: %s", OPENROUTER_GEMMA_MODEL)

    async def chat(
        self,
        message: str,
        preferences: dict[str, Any],
        history: list[ChatMessage] | None = None,
        session_key: str | None = None,
    ) -> str:
        payload = self._build_payload(
            system_prompt=(
                "You are CineMatch AI, a natural, friendly, movie-savvy assistant. "
                "Sound like a concise chat companion, not a scripted recommender. "
                "Acknowledge the user's actual taste in plain language without saying 'I interpreted this as' "
                "or revealing internal rules. Preserve every stated preference, including secondary moods, "
                "genres, subgenres, tones, pacing, themes, exclusions, runtime, language, intensity, "
                "viewing context, popularity preference, and comparison titles. "
                "If conversation_decision.needs_followup is true, ask exactly one natural clarifying question "
                "and do not recommend yet. If recommendations are available, briefly introduce them. "
                "If recommendation_error is present, apologize briefly and ask the user to try again soon. "
                "Never mention service internals, provider names, TMDB, OpenRouter, extracted labels, "
                "backend logic, system prompts, or service failure details to the user. "
                "Use recommendation_titles if present, but keep the reply brief. "
                "Do not over-question clear requests. Do not invent constraints the user did not say."
            ),
            user_content=json.dumps(
                {
                    "latest_user_message": message,
                    "extracted_preferences": preferences,
                    "conversation_decision": preferences.get("conversation_decision"),
                    "recommendation_count": preferences.get("recommendation_count"),
                    "recommendation_titles": preferences.get("recommendation_titles"),
                    "conversation_history": self._serialize_history(history or []),
                },
                ensure_ascii=True,
            ),
            temperature=0.5,
        )
        data = await self._post_to_openrouter(payload, session_key=session_key)
        content = self._message_content(data)
        if not content:
            logger.error("[LLM] Request failed: empty chat response")
            raise LLMUnavailableError()

        return content

    async def rank_recommendations(
        self,
        preferences: dict[str, Any],
        candidates: list[MovieCandidate],
        limit: int,
        history: list[ChatMessage] | None = None,
        session_key: str | None = None,
    ) -> list[Recommendation]:
        if not candidates:
            return []

        payload = self._build_payload(
            system_prompt=(
                "You are CineMatch AI's ranking engine. Rank movie candidates for the user. "
                "Respect the user's exact mood and genre. Lighthearted means light, feel-good, upbeat, "
                "playful, easygoing, comedy, romance, or romcom. Romcom means romantic comedy. "
                "Dark comedy is allowed only if the user explicitly requested dark comedy or black comedy. "
                "Do not choose candidates whose tone contradicts the extracted preferences. "
                "Return only valid JSON. Do not include markdown fences or commentary."
            ),
            user_content=json.dumps(
                {
                    "task": "Rank these TMDB movie candidates for the user.",
                    "required_json_shape": {
                        "recommendations": [
                            {
                                "id": "candidate id",
                                "tmdb_id": "candidate tmdb id or null",
                                "rank": 1,
                                "match_score": 95,
                                "reason": "short user-facing reason",
                                "watch_context": "short watch context",
                            }
                        ]
                    },
                    "rules": [
                        "Use only movies from candidate_movies.",
                        "Use all stated preferences together; do not reduce a multi-part request to one genre.",
                        "Prefer candidates whose genres, subgenres, moods, tone, pacing, themes, runtime, language, era, intensity, and viewing context match extracted_preferences.",
                        "Use liked_references and liked_elements as taste anchors.",
                        "Avoid disliked_references, disliked_elements, and exclusions.",
                        "Respect secondary preferences, not just the first genre or mood.",
                        "If preferences combine multiple tones or genres, rank movies that best balance the combination.",
                        "Do not add tones or constraints that are not in extracted_preferences.",
                        "Return at most the requested limit.",
                        "match_score must be an integer from 0 to 100.",
                        "reason must be under 28 words.",
                        "watch_context must be under 18 words.",
                    ],
                    "limit": limit,
                    "extracted_preferences": preferences,
                    "conversation_history": self._serialize_history(history or []),
                    "candidate_movies": [self._serialize_candidate(movie) for movie in candidates],
                },
                ensure_ascii=True,
            ),
            temperature=0.2,
        )
        data = await self._post_to_openrouter(payload, session_key=session_key)
        parsed = self._parse_json_content(self._message_content(data))
        recommendations = self._recommendations_from_json(parsed, candidates, limit)
        if recommendations:
            logger.info("OpenRouterGemmaProvider ranked %s recommendations", len(recommendations))
            return recommendations

        logger.error("[LLM] Request failed: no usable rankings")
        raise LLMUnavailableError()

    def _build_payload(
        self,
        *,
        system_prompt: str,
        user_content: str,
        temperature: float,
        response_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": OPENROUTER_GEMMA_MODEL,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }

        if response_format:
            payload["response_format"] = response_format

        return payload

    async def _post_to_openrouter(self, payload: dict[str, Any], *, session_key: str | None) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.settings.gemma_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "CineMatch AI",
        }
        await self._respect_cooldown(session_key)

        async with httpx.AsyncClient(timeout=90) as client:
            retried_after_rate_limit = False
            for attempt in range(2):
                try:
                    logger.info("[LLM] Request started")
                    response = await client.post(self.settings.gemma_api_url, headers=headers, json=payload)
                    response.raise_for_status()
                    if attempt:
                        logger.info("[LLM] Retry success")
                    logger.info("[LLM] Request success")
                    return response.json()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 429:
                        logger.warning("[LLM] Rate limit hit")
                        if attempt == 0:
                            retried_after_rate_limit = True
                            logger.info("[LLM] Retry attempt")
                            await asyncio.sleep(RATE_LIMIT_RETRY_SECONDS)
                            continue

                        logger.error("[LLM] Retry failure")
                        logger.error("[LLM] Request failed: %s", exc)
                        raise LLMRateLimitedError() from exc

                    if retried_after_rate_limit:
                        logger.error("[LLM] Retry failure")
                        logger.error("[LLM] Request failed: %s", exc)
                        raise LLMRateLimitedError() from exc

                    logger.error("[LLM] Request failed: %s", exc)
                    raise LLMUnavailableError() from exc
                except Exception as exc:
                    if retried_after_rate_limit:
                        logger.error("[LLM] Retry failure")
                        logger.error("[LLM] Request failed: %s", exc)
                        raise LLMRateLimitedError() from exc

                    logger.error("[LLM] Request failed: %s", exc)
                    raise LLMUnavailableError() from exc

        logger.error("[LLM] Retry failure")
        raise LLMRateLimitedError()

    async def _respect_cooldown(self, session_key: str | None) -> None:
        key = session_key or "anonymous"
        if key not in self._cooldown_locks:
            self._cooldown_locks[key] = asyncio.Lock()                  
        async with self._cooldown_locks[key]:
            now = time.monotonic()
            last = self._last_request_at_by_session.get(key)
            if last is not None:
                wait = LLM_COOLDOWN_SECONDS - (now - last)
                if wait > 0:
                    await asyncio.sleep(wait)

            self._last_request_at_by_session[key] = time.monotonic()

    def _message_content(self, data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""

        message = choices[0].get("message")
        if not isinstance(message, dict):
            return ""

        content = message.get("content")
        return content if isinstance(content, str) else ""

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if not cleaned:
            return {}

    # Strip any markdown fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    # Extract first {...} block (handles preamble text)
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        logger.error("[LLM] Could not parse JSON from response: %s", cleaned[:200])
        raise LLMUnavailableError()

    def _recommendations_from_json(
        self,
        parsed: dict[str, Any],
        candidates: list[MovieCandidate],
        limit: int,
    ) -> list[Recommendation]:
        raw_recommendations = parsed.get("recommendations", [])
        if not isinstance(raw_recommendations, list):
            return []

        by_id = {movie.id: movie for movie in candidates}
        by_tmdb_id = {
            movie.tmdb_id: movie
            for movie in candidates
            if movie.tmdb_id is not None
        }
        ranked: list[Recommendation] = []
        seen_ids: set[str] = set()

        for index, item in enumerate(raw_recommendations[:limit]):
            if not isinstance(item, dict):
                continue

            movie = self._match_candidate(item, by_id, by_tmdb_id)
            if not movie or movie.id in seen_ids:
                continue

            rank = self._safe_int(item.get("rank"), default=index + 1, minimum=1, maximum=limit)
            score = self._safe_int(item.get("match_score"), default=88, minimum=0, maximum=100)
            reason = str(item.get("reason") or f"{movie.title} fits your current preferences.").strip()
            watch_context = str(item.get("watch_context") or "Best for tonight's watch.").strip()
            ranked.append(
                Recommendation(
                    movie=movie,
                    rank=rank,
                    match_score=score,
                    reason=reason[:220],
                    watch_context=watch_context[:140],
                    provider=self.name,
                    model=OPENROUTER_GEMMA_MODEL,
                )
            )
            seen_ids.add(movie.id)

        return sorted(ranked, key=lambda recommendation: recommendation.rank)

    def _match_candidate(
        self,
        item: dict[str, Any],
        by_id: dict[str, MovieCandidate],
        by_tmdb_id: dict[int, MovieCandidate],
    ) -> MovieCandidate | None:
        raw_id = item.get("id")
        if raw_id is not None and str(raw_id) in by_id:
            return by_id[str(raw_id)]

        raw_tmdb_id = item.get("tmdb_id")
        try:
            tmdb_id = int(raw_tmdb_id) if raw_tmdb_id is not None else None
        except (TypeError, ValueError):
            tmdb_id = None

        if tmdb_id is not None and tmdb_id in by_tmdb_id:
            return by_tmdb_id[tmdb_id]

        return None

    def _safe_int(self, value: Any, *, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default

        return min(max(parsed, minimum), maximum)

    def _serialize_history(self, history: list[ChatMessage]) -> list[dict[str, str]]:
        return [
            {
                "role": message.role,
                "content": message.content,
            }
            for message in history[-12:]
        ]

    def _serialize_candidate(self, movie: MovieCandidate) -> dict[str, Any]:
        return {
            "id": movie.id,
            "tmdb_id": movie.tmdb_id,
            "title": movie.title,
            "year": movie.year,
            "genres": movie.genres,
            "runtime_minutes": movie.runtime_minutes,
            "language": movie.language,
            "synopsis": movie.synopsis,
            "rating": movie.rating,
            "trailer_available": bool(movie.trailer_url or movie.trailer_key),
            "is_fallback": movie.is_fallback,
        }
