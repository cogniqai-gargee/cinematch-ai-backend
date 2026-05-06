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
# Primary model — try this first
LLM_PRIMARY_MODEL   = "google/gemma-3-12b-it:free"
# Fallback model — used automatically if primary hits 429 twice
LLM_FALLBACK_MODEL  = "qwen/qwen-2.5-7b-instruct:free"

OPENROUTER_GEMMA_MODEL = LLM_PRIMARY_MODEL
LLM_COOLDOWN_SECONDS    = 3.0
RATE_LIMIT_RETRY_SECONDS = 12.0   # was 2.0 — needs real breathing room
CACHE_TTL_SECONDS        = 300    # 5 minute response cache
 
 
class OpenRouterGemmaProvider(BaseLLMProvider):
    name = "openrouter-gemma"
 
    def __init__(self, settings: Settings):
        self.settings = settings
        self._cooldown_locks: dict[str, asyncio.Lock] = {}
        self._last_request_at_by_session: dict[str, float] = {}
        self._response_cache: dict[str, tuple[float, str]] = {}
        logger.info("[LLM] Provider: OpenRouter")
        logger.info("[LLM] Model: %s", OPENROUTER_GEMMA_MODEL)
 
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
        """
        When recommendations already exist in preferences, build a reply
        locally without calling the LLM. This eliminates the second API
        call that was causing back-to-back 429 rate limit hits.
        """
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
 
        # Only reaches the LLM for follow-up questions or opening messages
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
 
        payload = self._build_payload(
            system_prompt=(
                "You are CineMatch AI ranking engine. "
                "Return ONLY valid JSON with no markdown fences, no commentary, nothing else. "
                "The JSON must have exactly one key: 'recommendations'."
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
                        "Prefer candidates matching genres, moods, tone, pacing, runtime, language.",
                        "Return at most the requested limit.",
                        "match_score must be integer 0 to 100.",
                        "reason must be under 28 words.",
                        "watch_context must be under 18 words.",
                        "Output ONLY the JSON object. No text before or after.",
                    ],
                    "limit": limit,
                    "extracted_preferences": preferences,
                    "candidate_movies": [self._serialize_candidate(m) for m in candidates],
                },
                ensure_ascii=True,
            ),
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
        payload = self._build_payload(
            system_prompt=(
                "You are CineMatch AI, a natural, friendly, movie-savvy assistant. "
                "Sound like a concise chat companion, not a scripted recommender. "
                "If you need more information, ask exactly one natural clarifying question. "
                "Never mention TMDB, OpenRouter, or backend details. "
                "Keep replies brief and conversational."
            ),
            user_content=json.dumps(
                {
                    "latest_user_message": message,
                    "extracted_preferences": preferences,
                    "conversation_decision": preferences.get("conversation_decision"),
                    "conversation_history": self._serialize_history(history or []),
                },
                ensure_ascii=True,
            ),
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
    #  PRIVATE: HTTP                                                       #
    # ------------------------------------------------------------------ #
    async def _post_and_get_content(
        self,
        payload: dict[str, Any],
        session_key: str | None,
    ) -> str:
        """
        Try the primary model first (2 attempts with retry wait).
        If both fail with 429, automatically switch to the fallback model
        and try once more — instead of raising to the caller.
        """
        await self._respect_cooldown(session_key)

        models_to_try = [
            (LLM_PRIMARY_MODEL, 2),    # primary: 2 attempts
            (LLM_FALLBACK_MODEL, 1),   # fallback: 1 attempt
        ]

        async with httpx.AsyncClient(timeout=90) as client:
            for model, max_attempts in models_to_try:
                current_payload = {**payload, "model": model}

                for attempt in range(max_attempts):
                    try:
                        logger.info(
                            "[LLM] Request started (model=%s attempt=%s)",
                            model, attempt + 1,
                        )
                        response = await client.post(
                            self.settings.gemma_api_url,
                            headers={
                                "Authorization": f"Bearer {self.settings.gemma_api_key}",
                                "Content-Type": "application/json",
                                "HTTP-Referer": "https://cinematch.app",
                                "X-Title": "CineMatch AI",
                            },
                            json=current_payload,
                        )
                        response.raise_for_status()
                        data = response.json()
                        content = self._message_content(data)
                        if content:
                            logger.info("[LLM] Request success (model=%s)", model)
                            return content
                        raise ValueError("Empty content from model")

                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code == 429:
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
                                    "[LLM] Switching to fallback model after %s failed",
                                    model,
                                )
                                break  # try next model
                        else:
                            logger.error(
                                "[LLM] HTTP error %s from model %s",
                                exc.response.status_code, model,
                            )
                            break  # try next model

                    except Exception as exc:
                        logger.error("[LLM] Unexpected error from model %s: %s", model, exc)
                        break  # try next model

        logger.error("[LLM] All models exhausted — raising LLMUnavailableError")
        raise LLMUnavailableError()
 
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
    #  PRIVATE: cooldown (per-session, not global)                        #
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
    #  PRIVATE: payload builder                                            #
    # ------------------------------------------------------------------ #
    def _build_payload(
        self,
        *,
        system_prompt: str,
        user_content: str,
        temperature: float,
    ) -> dict[str, Any]:
        # NOTE: response_format intentionally omitted.
        # Gemma free ignores it and wastes tokens trying to comply.
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
 
        # Strip markdown fences (Gemma often wraps JSON in ```json ... ```)
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r'\s*```\s*$', '', cleaned).strip()
 
        # Direct parse
        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
 
        # Extract first {...} block (handles preamble prose before JSON)
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                pass
 
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
        # Trimmed from 12 → 8 to keep payloads smaller and responses faster
        return [{"role": m.role, "content": m.content} for m in history[-8:]]
 
    def _serialize_candidate(self, movie: MovieCandidate) -> dict[str, Any]:
        return {
            "id":             movie.id,
            "tmdb_id":        movie.tmdb_id,
            "title":          movie.title,
            "year":           movie.year,
            "genres":         movie.genres,
            "runtime_minutes": movie.runtime_minutes,
            "language":       movie.language,
            # Truncated to 200 chars — reduces token count without losing ranking signal
            "synopsis":       (movie.synopsis or "")[:200],
            "rating":         movie.rating,
        }
