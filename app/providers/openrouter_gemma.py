import asyncio
import hashlib
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

# ------------------------------------------------------------------ #
#  Model configuration — Google AI Studio                             #
# ------------------------------------------------------------------ #
# Verify these names in aistudio.google.com model dropdown
AI_STUDIO_BASE_URL   = "https://generativelanguage.googleapis.com/v1beta/models"
LLM_PRIMARY_MODEL    = "gemma-4-31b-it"
LLM_FALLBACK_MODEL   = "gemma-4-26b-a4b-it"

LLM_COOLDOWN_SECONDS      = 3.0
RATE_LIMIT_RETRY_SECONDS  = 20.0
CACHE_TTL_SECONDS         = 300

# Keep this alias so nothing else breaks
OPENROUTER_GEMMA_MODEL = LLM_PRIMARY_MODEL


class OpenRouterGemmaProvider(BaseLLMProvider):
    """
    LLM provider backed by Google AI Studio (Gemma 4 31B primary,
    Gemma 4 26B A4B fallback). The class keeps the original name so
    no other files need to change their imports.
    """
    name = "aistudio-gemma"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cooldown_locks: dict[str, asyncio.Lock] = {}
        self._last_request_at_by_session: dict[str, float] = {}
        self._response_cache: dict[str, tuple[float, str]] = {}
        logger.info("[LLM] Provider: Google AI Studio")
        logger.info("[LLM] Primary model: %s (key project 1)", LLM_PRIMARY_MODEL)
        logger.info("[LLM] Fallback model: %s (key project 2)", LLM_FALLBACK_MODEL)

    # ------------------------------------------------------------------ #
    #  PUBLIC: chat                                                        #
    # ------------------------------------------------------------------ #
    async def chat(
        self,
        message: str,
        preferences: dict[str, Any],
        history: list[ChatMessage] | None = None,
        session_key: str | None = None,
    ) -> str:
        rec_error = preferences.get("recommendation_error")
        if rec_error:
            return (
                "I'm sorry, movie results are temporarily unavailable. "
                "Please try again in a moment."
            )

        titles = preferences.get("recommendation_titles")
        if titles and isinstance(titles, list) and titles:
            decision = preferences.get("conversation_decision") or {}
            if not (isinstance(decision, dict) and decision.get("needs_followup")):
                return self._build_recommendation_reply(titles, preferences)

        return await self._llm_chat(message, preferences, history, session_key)

    # ------------------------------------------------------------------ #
    #  PUBLIC: rank_recommendations                                        #
    # ------------------------------------------------------------------ #
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

        system_prompt = (
            "You are a JSON-only response engine. "
            "CRITICAL: You MUST respond with ONLY valid JSON, nothing else. "
            "No markdown, no explanation, no text before or after. "
            "Invalid: markdown fences, bullet points, text, numbers. "
            "Valid: only raw JSON object with key 'recommendations' containing an array. "
            "If you cannot respond with valid JSON only, return empty array."
        )
        
        # Format user message with clear INPUT/OUTPUT separation to prevent model confusion
        user_content = f"""INPUTS:
User Preferences: {json.dumps(preferences, ensure_ascii=True)}
Candidate Movies: {json.dumps([self._serialize_candidate(m) for m in candidates], ensure_ascii=True)}
Limit: {limit}

TASK: Rank the candidate movies based on user preferences. Select up to {limit} movies.

OUTPUT REQUIREMENTS:
- Must be ONLY a valid JSON object
- Key: "recommendations" (array)
- Each item: {{"id": candidate_id, "tmdb_id": tmdb_id_or_null, "rank": 1-{limit}, "match_score": 0-100, "reason": "under 28 words", "watch_context": "under 18 words"}}
- match_score: integer 0-100 based on genre/mood/tone/runtime match
- Only use candidates from the input list
- No text, no markdown, no explanation—ONLY JSON"""
        
        user_content_json = user_content

        payload = self._build_payload(
            system_prompt=system_prompt,
            user_content=user_content_json,
            temperature=0.2,
        )

        cache_key = self._make_cache_key(payload)
        cached_content = self._get_cached(cache_key)
        if cached_content:
            parsed = self._parse_json_content(cached_content)
        else:
            content = await self._post_and_get_content(payload, session_key)
            self._set_cached(cache_key, content)
            parsed = self._parse_json_content(content)

        recommendations = self._recommendations_from_json(parsed, candidates, limit)
        if recommendations:
            logger.info("[LLM] Ranked %s recommendations", len(recommendations))
            return recommendations

        logger.error("[LLM] No usable rankings from response")
        raise LLMUnavailableError()

    # ------------------------------------------------------------------ #
    #  PRIVATE: local reply builder (no LLM call)                         #
    # ------------------------------------------------------------------ #
    def _build_recommendation_reply(
        self,
        titles: list[str],
        preferences: dict[str, Any],
    ) -> str:
        count = preferences.get("recommendation_count", len(titles))
        genres = preferences.get("genres") or []
        moods  = preferences.get("moods")  or []
        language = preferences.get("language") or preferences.get("languages")

        context_parts: list[str] = []
        if genres:
            g = genres if isinstance(genres, str) else ", ".join(genres[:2])
            context_parts.append(g)
        if moods:
            m = moods if isinstance(moods, str) else moods[0]
            context_parts.append(m)
        if language and language not in ("en", "en-US", "English", "english"):
            lang = language if isinstance(language, str) else language[0]
            context_parts.append(f"{lang}-language")
        context = " ".join(context_parts) if context_parts else "your vibe"

        if len(titles) == 1:
            return (
                f"Based on {context}, here's my top pick: {titles[0]}. "
                "Want more options or a different direction?"
            )

        listed = ", ".join(f'"{t}"' for t in titles[:3])
        extra  = f" and {count - 3} more" if count > 3 else ""
        return (
            f"Here are {count} matches for {context}: {listed}{extra}. "
            "The top pick is your best fit — want details on any, or shall I adjust the vibe?"
        )

    # ------------------------------------------------------------------ #
    #  PRIVATE: actual LLM chat call (follow-ups only)                    #
    # ------------------------------------------------------------------ #
    async def _llm_chat(
        self,
        message: str,
        preferences: dict[str, Any],
        history: list[ChatMessage] | None,
        session_key: str | None,
    ) -> str:
        system_prompt = (
            "You are CineMatch AI, a natural, friendly, movie-savvy assistant. "
            "Sound like a concise chat companion, not a scripted recommender. "
            "IMPORTANT: Consider the ENTIRE conversation history when responding. "
            "The user's latest message is your primary focus, but NEVER ignore prior context "
            "unless the user explicitly asks you to start fresh. "
            "If you need more information, ask exactly one natural clarifying question. "
            "Never mention TMDB, Google AI Studio, or any backend details. "
            "Keep replies brief and conversational — 2-4 sentences max."
        )
        user_content = json.dumps(
            {
                "latest_user_message": message,
                "extracted_preferences": preferences,
                "conversation_decision": preferences.get("conversation_decision"),
                "full_conversation_history": self._serialize_history(history or []),
                "instruction": (
                    "Respond to the latest message, keeping in mind everything in "
                    "full_conversation_history. The latest message is most important, "
                    "but do not forget what the user told you earlier."
                ),
            },
            ensure_ascii=True,
        )

        payload = self._build_payload(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=0.5,
        )

        cache_key = self._make_cache_key(payload)
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        content = await self._post_and_get_content(payload, session_key)
        self._set_cached(cache_key, content)
        return content

    # ------------------------------------------------------------------ #
    #  PRIVATE: HTTP (Google AI Studio format)                            #
    # ------------------------------------------------------------------ #
    async def _post_and_get_content(
        self,
        payload: dict[str, Any],
        session_key: str | None,
    ) -> str:
        """
        Try primary model with primary API key first.
        On 429 or error, fall back to secondary model with secondary API key.
        This way we use two completely separate Google AI Studio projects,
        doubling the effective free quota.
        """
        await self._respect_cooldown(session_key)

        # Each tuple: (model_name, api_key, max_attempts)
        models_to_try = [
            (LLM_PRIMARY_MODEL,  self.settings.gemma_primary_api_key,  2),
            (LLM_FALLBACK_MODEL, self.settings.gemma_fallback_api_key, 1),
        ]

        async with httpx.AsyncClient(timeout=90) as client:
            for model, api_key, max_attempts in models_to_try:
                if not api_key:
                    logger.warning("[LLM] No API key for model %s — skipping", model)
                    continue

                url = f"{AI_STUDIO_BASE_URL}/{model}:generateContent?key={api_key}"
                request_body = self._build_aistudio_request(payload)

                for attempt in range(max_attempts):
                    try:
                        logger.info(
                            "[LLM] Request started (model=%s attempt=%s)",
                            model, attempt + 1,
                        )
                        response = await client.post(
                            url,
                            headers={"Content-Type": "application/json"},
                            json=request_body,
                        )
                        response.raise_for_status()
                        data = response.json()
                        content = self._extract_aistudio_content(data)
                        if content:
                            logger.info("[LLM] Request success (model=%s)", model)
                            return content
                        raise ValueError("Empty content from AI Studio response")

                    except httpx.HTTPStatusError as exc:
                        status = exc.response.status_code
                        if status == 404:
                            logger.error(
                                "[LLM] Model not found (404): %s — verify name in AI Studio",
                                model,
                            )
                            break  # skip immediately, don't retry
                        elif status == 429:
                            logger.warning(
                                "[LLM] Rate limit hit (model=%s attempt=%s)",
                                model, attempt + 1,
                            )
                            if attempt < max_attempts - 1:
                                logger.info(
                                    "[LLM] Waiting %ss before retry",
                                    RATE_LIMIT_RETRY_SECONDS,
                                )
                                await asyncio.sleep(RATE_LIMIT_RETRY_SECONDS)
                            else:
                                logger.warning(
                                    "[LLM] Switching to fallback model",
                                )
                                break
                        else:
                            logger.error(
                                "[LLM] HTTP %s from model %s — %s",
                                status, model, exc.response.text[:300],
                            )
                            break

                    except Exception as exc:
                        logger.error(
                            "[LLM] Unexpected error (model=%s): %s", model, exc
                        )
                        break

        logger.error("[LLM] All models exhausted — raising LLMUnavailableError")
        raise LLMUnavailableError()

    def _build_aistudio_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Convert our internal payload format to Google AI Studio's request format.
        AI Studio uses system_instruction + contents (not messages array).
        """
        messages = payload.get("messages", [])
        system_text = ""
        contents = []

        for msg in messages:
            role = msg.get("role", "user")
            text = msg.get("content", "")
            if role == "system":
                system_text = text
            else:
                # AI Studio uses "model" not "assistant"
                ai_studio_role = "model" if role == "assistant" else "user"
                contents.append({
                    "role": ai_studio_role,
                    "parts": [{"text": text}],
                })

        request: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": payload.get("temperature", 0.5),
                "maxOutputTokens": payload.get("max_tokens", 600),
            },
        }

        if system_text:
            request["system_instruction"] = {
                "parts": [{"text": system_text}]
            }

        return request

    def _extract_aistudio_content(self, data: dict[str, Any]) -> str:
        """
        Extract text from Google AI Studio response format:
        data.candidates[0].content.parts[0].text
        """
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return ""
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            return ""
        text = parts[0].get("text", "")
        return text if isinstance(text, str) else ""

    # ------------------------------------------------------------------ #
    #  PRIVATE: cache                                                      #
    # ------------------------------------------------------------------ #
    def _make_cache_key(self, payload: dict) -> str:
        key_str = json.dumps(
            payload.get("messages", []), sort_keys=True, ensure_ascii=True
        )
        return hashlib.sha256(key_str.encode()).hexdigest()[:20]

    def _get_cached(self, key: str) -> str | None:
        entry = self._response_cache.get(key)
        if not entry:
            return None
        cached_at, content = entry
        if time.monotonic() - cached_at > CACHE_TTL_SECONDS:
            del self._response_cache[key]
            return None
        logger.info("[LLM] Cache hit — skipping API call")
        return content

    def _set_cached(self, key: str, content: str) -> None:
        if len(self._response_cache) >= 100:
            oldest = min(
                self._response_cache,
                key=lambda k: self._response_cache[k][0]
            )
            del self._response_cache[oldest]
        self._response_cache[key] = (time.monotonic(), content)

    # ------------------------------------------------------------------ #
    #  PRIVATE: cooldown (per-session)                                    #
    # ------------------------------------------------------------------ #
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
                    logger.info("[LLM] Cooldown wait: %.1fs", wait)
                    await asyncio.sleep(wait)
            self._last_request_at_by_session[key] = time.monotonic()

    # ------------------------------------------------------------------ #
    #  PRIVATE: payload builder (internal format, converted before send)  #
    # ------------------------------------------------------------------ #
    def _build_payload(
        self,
        *,
        system_prompt: str,
        user_content: str,
        temperature: float,
    ) -> dict[str, Any]:
        return {
            "model": OPENROUTER_GEMMA_MODEL,
            "max_tokens": 600,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_content},
            ],
        }

    # ------------------------------------------------------------------ #
    #  PRIVATE: response parsing                                           #
    # ------------------------------------------------------------------ #
    def _parse_json_content(self, content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if not cleaned:
            return {}

        # Remove markdown code fences if present
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r'\s*```\s*$', '', cleaned).strip()

        # Try direct JSON parse first
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                logger.info("[LLM] JSON parsed successfully")
                return parsed
        except json.JSONDecodeError:
            pass

        # Try to extract JSON object from content (handles cases where model adds text before/after)
        # Look for the first { and last } that form valid JSON
        for start_idx in range(len(cleaned)):
            if cleaned[start_idx] == '{':
                for end_idx in range(len(cleaned), start_idx, -1):
                    if cleaned[end_idx - 1] == '}':
                        candidate = cleaned[start_idx:end_idx]
                        try:
                            parsed = json.loads(candidate)
                            if isinstance(parsed, dict):
                                logger.info("[LLM] JSON extracted from position %d", start_idx)
                                return parsed
                        except json.JSONDecodeError:
                            continue
                break

        logger.error("[LLM] Could not parse JSON. Raw[:300]: %s", cleaned[:300])
        raise LLMUnavailableError()

    def _recommendations_from_json(
        self,
        parsed: dict[str, Any],
        candidates: list[MovieCandidate],
        limit: int,
    ) -> list[Recommendation]:
        raw = parsed.get("recommendations", [])
        if not isinstance(raw, list):
            return []

        by_id   = {m.id: m for m in candidates}
        by_tmdb = {m.tmdb_id: m for m in candidates if m.tmdb_id is not None}
        ranked: list[Recommendation] = []
        seen: set[str] = set()

        for i, item in enumerate(raw[:limit]):
            if not isinstance(item, dict):
                continue
            movie = self._match_candidate(item, by_id, by_tmdb)
            if not movie or movie.id in seen:
                continue
            rank  = self._safe_int(item.get("rank"),        default=i+1, minimum=1,   maximum=limit)
            score = self._safe_int(item.get("match_score"), default=88,  minimum=0,   maximum=100)
            reason    = str(item.get("reason")        or f"{movie.title} fits your preferences.").strip()
            watch_ctx = str(item.get("watch_context") or "Best for tonight.").strip()
            ranked.append(Recommendation(
                movie=movie,
                rank=rank,
                match_score=score,
                reason=reason[:220],
                watch_context=watch_ctx[:140],
                provider=self.name,
                model=OPENROUTER_GEMMA_MODEL,
            ))
            seen.add(movie.id)

        return sorted(ranked, key=lambda r: r.rank)

    def _match_candidate(
        self,
        item: dict[str, Any],
        by_id:   dict[str, MovieCandidate],
        by_tmdb: dict[int, MovieCandidate],
    ) -> MovieCandidate | None:
        raw_id = item.get("id")
        if raw_id is not None and str(raw_id) in by_id:
            return by_id[str(raw_id)]
        raw_tmdb = item.get("tmdb_id")
        try:
            tmdb_id = int(raw_tmdb) if raw_tmdb is not None else None
        except (TypeError, ValueError):
            tmdb_id = None
        return by_tmdb.get(tmdb_id) if tmdb_id is not None else None

    def _safe_int(self, value: Any, *, default: int, minimum: int, maximum: int) -> int:
        try:
            return min(max(int(value), minimum), maximum)
        except (TypeError, ValueError):
            return default

    def _serialize_history(self, history: list[ChatMessage]) -> list[dict[str, str]]:
        # Include full history (up to 12 messages) so AI considers everything
        return [{"role": m.role, "content": m.content} for m in history[-12:]]

    def _serialize_candidate(self, movie: MovieCandidate) -> dict[str, Any]:
        return {
            "id":              movie.id,
            "tmdb_id":         movie.tmdb_id,
            "title":           movie.title,
            "year":            movie.year,
            "genres":          movie.genres,
            "runtime_minutes": movie.runtime_minutes,
            "language":        movie.language,
            "synopsis":        (movie.synopsis or "")[:200],
            "rating":          movie.rating,
        }
