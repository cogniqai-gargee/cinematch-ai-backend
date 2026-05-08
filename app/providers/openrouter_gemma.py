import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Any

import httpx

from app.config import Settings
from app.providers.base import BaseLLMProvider, LLMFormatError, LLMRateLimitedError, LLMUnavailableError
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

        # Cap the LLM ranking at 3 for reliability; we still receive more candidates
        # from TMDB so the deterministic fallback has options.
        effective_limit = min(limit, 3)
        candidates_data = [self._serialize_candidate(m) for m in candidates]

        system_prompt = (
            "You are a JSON-only response generator. "
            "You must output exactly one valid JSON object and nothing else. "
            "Do not include any explanation, analysis, bullet points, markdown, or text. "
            "Do not restate the input. If you cannot produce valid JSON, output {\"recommendations\": []}."
        )

        user_content = json.dumps(
            {
                "task": "rank_movies",
                "preferences": preferences,
                "candidate_movies": candidates_data,
                "limit": effective_limit,
                "output_format": {
                    "recommendations": [
                        {
                            "id": "string",
                            "tmdb_id": "number or null",
                            "rank": "integer 1-3",
                            "match_score": "integer 0-100",
                            "reason": "string",
                        }
                    ]
                },
                "instructions": (
                    "Output EXACTLY one valid JSON object with a single key named 'recommendations'."
                    f" Return exactly {effective_limit} movies. No markdown, no commentary, no text outside the JSON."
                ),
            },
            ensure_ascii=True,
        )

        payload = self._build_payload(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=0.0,
        )

        # ── Attempt chain: LLM parse → retry → fallback model → deterministic ──
        parsed: dict[str, Any] | None = None

        cache_key = self._make_cache_key(payload)
        cached_content = self._get_cached(cache_key)
        if cached_content:
            try:
                parsed = self._parse_json_content(cached_content, candidates)
            except LLMFormatError:
                parsed = None

        if parsed is None:
            try:
                content = await self._post_and_get_content(payload, session_key)
                parsed = self._parse_json_content(content, candidates)
                self._set_cached(cache_key, content)
            except LLMFormatError:
                logger.warning(
                    "[LLM] First ranking response invalid; retrying with stricter JSON-only prompt"
                )
                try:
                    retry_user_content = json.dumps(
                        {
                            "task": "rank_movies_retry",
                            "error": "Previous response was not valid JSON.",
                            "preferences": preferences,
                            "candidate_movies": candidates_data,
                            "limit": effective_limit,
                            "output_format": {
                                "recommendations": [
                                    {
                                        "id": "string",
                                        "tmdb_id": "number or null",
                                        "rank": "integer",
                                        "match_score": "integer 0-100",
                                        "reason": "string",
                                    }
                                ]
                            },
                            "instructions": (
                                "Respond with EXACTLY one valid JSON object and nothing else. "
                                "Do not include any text, markdown, bullet points, or explanation. "
                                f"Return exactly {effective_limit} movies."
                            ),
                        },
                        ensure_ascii=True,
                    )
                    retry_payload = self._build_payload(
                        system_prompt=system_prompt,
                        user_content=retry_user_content,
                        temperature=0.0,
                    )
                    retry_content = await self._post_and_get_content(retry_payload, session_key)
                    parsed = self._parse_json_content(retry_content, candidates)
                    self._set_cached(cache_key, retry_content)
                except LLMFormatError:
                    logger.warning(
                        "[LLM] Retry response invalid; trying fallback model"
                    )
                    try:
                        fallback_content = await self._post_and_get_content(
                            retry_payload,
                            session_key,
                            fallback_only=True,
                        )
                        parsed = self._parse_json_content(fallback_content, candidates)
                        self._set_cached(cache_key, fallback_content)
                    except (LLMFormatError, LLMUnavailableError):
                        logger.warning(
                            "[LLM] All LLM attempts failed format validation; "
                            "falling through to deterministic ranking"
                        )
                        parsed = None
                except LLMUnavailableError:
                    # Provider itself is down — still fall through to deterministic
                    logger.warning(
                        "[LLM] Provider unavailable on retry; "
                        "falling through to deterministic ranking"
                    )
                    parsed = None
            except LLMUnavailableError:
                # Provider itself is down on first attempt
                logger.warning(
                    "[LLM] Provider unavailable; falling through to deterministic ranking"
                )
                parsed = None
            except Exception as exc:
                logger.warning(
                    "[LLM] Unexpected ranking exception; falling through to deterministic ranking: %s",
                    exc,
                )
                parsed = None

        # ── Extract recommendations from parsed JSON ──
        if parsed is not None:
            recommendations = self._recommendations_from_json(parsed, candidates, effective_limit)
            if recommendations:
                logger.info("[LLM] Ranked %s recommendations via LLM", len(recommendations))
                return recommendations

        # ── Deterministic fallback — user always gets results ──
        logger.info("[LLM] Using deterministic fallback ranker")
        return self._deterministic_rank(candidates, preferences, effective_limit)

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
        display_titles = titles[:3]
        listed = ", ".join(f'"{t}"' for t in display_titles)

        return (
            f"Here are my top {len(display_titles)} picks for {context}: {listed}. "
            "Tap any movie to view the trailer, save it, mark it watched, or check where to watch."
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
        fallback_only: bool = False,
    ) -> str:
        """
        Try primary model with primary API key first.
        On 429 or error, fall back to secondary model with secondary API key.
        This way we use two completely separate Google AI Studio projects,
        doubling the effective free quota.
        """
        await self._respect_cooldown(session_key)

        if fallback_only:
            models_to_try = [
                (LLM_FALLBACK_MODEL, self.settings.gemma_fallback_api_key, 2),
            ]
        else:
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
    def _parse_json_content(
        self,
        content: str,
        candidates: list[MovieCandidate] | None = None,
    ) -> dict[str, Any]:
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
                        json_candidate = cleaned[start_idx:end_idx]
                        try:
                            parsed = json.loads(json_candidate)
                            if isinstance(parsed, dict):
                                logger.info("[LLM] JSON extracted from position %d", start_idx)
                                return parsed
                        except json.JSONDecodeError:
                            continue
                break

        # Try to extract a JSON array (model might return [...] without wrapper)
        array_match = re.search(r'\[\s*\{.*?\}\s*(?:,\s*\{.*?\}\s*)*\]', cleaned, re.DOTALL)
        if array_match:
            try:
                arr = json.loads(array_match.group())
                if isinstance(arr, list) and arr:
                    logger.info("[LLM] JSON array extracted from prose, wrapping as recommendations")
                    return {"recommendations": arr}
            except json.JSONDecodeError:
                pass

        # Last resort: try to build recommendations from prose by matching candidate titles
        if candidates:
            extracted = self._extract_ranking_from_prose(cleaned, candidates)
            if extracted:
                logger.info("[LLM] Built %d recommendations from prose extraction", len(extracted))
                return {"recommendations": extracted}

        logger.error("[LLM] Could not parse JSON. Raw[:300]: %s", cleaned[:300])
        raise LLMFormatError(raw_snippet=cleaned[:300])

    def _extract_ranking_from_prose(
        self,
        text: str,
        candidates: list[MovieCandidate],
    ) -> list[dict[str, Any]]:
        """
        Attempt to find candidate movie titles in a prose/markdown response
        and build a synthetic recommendations list from the order they appear.
        """
        text_lower = text.lower()
        found: list[tuple[int, MovieCandidate]] = []

        for movie in candidates:
            title_lower = movie.title.lower()
            # Match exact title or title in quotes
            pos = text_lower.find(f'"{title_lower}"')
            if pos == -1:
                pos = text_lower.find(title_lower)
            if pos >= 0 and movie.id not in {m.id for _, m in found}:
                found.append((pos, movie))

        if not found:
            return []

        # Sort by position in text (first mentioned = highest rank)
        found.sort(key=lambda x: x[0])

        results: list[dict[str, Any]] = []
        for rank, (_, movie) in enumerate(found[:3], start=1):
            results.append({
                "id": movie.id,
                "tmdb_id": movie.tmdb_id,
                "rank": rank,
                "match_score": max(95 - (rank - 1) * 8, 70),
                "reason": f"{movie.title} matches your preferences.",
                "watch_context": "Great pick for tonight.",
            })
        return results

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

    def _deterministic_rank(
        self,
        candidates: list[MovieCandidate],
        preferences: dict[str, Any],
        limit: int,
    ) -> list[Recommendation]:
        """
        Rank candidates without any LLM call using a weighted scoring formula.
        This ensures the user always gets recommendations even when the model
        returns unusable output.
        """
        preferred_genres: set[str] = set()
        for g in (preferences.get("genres") or []):
            if isinstance(g, str):
                preferred_genres.add(g.lower())
        genre_str = preferences.get("genre")
        if isinstance(genre_str, str) and not preferred_genres:
            preferred_genres.update(
                g.strip().lower() for g in genre_str.split("+")
            )

        prefer_recent = preferences.get("era") == "recent" or preferences.get("popularity_preference") == "new"

        scored: list[tuple[float, int, MovieCandidate]] = []
        for position, movie in enumerate(candidates):
            # Genre match: fraction of preferred genres present (0-1)
            movie_genres_lower = {g.lower() for g in movie.genres}
            if preferred_genres:
                genre_overlap = len(preferred_genres & movie_genres_lower) / len(preferred_genres)
            else:
                genre_overlap = 0.5  # neutral if no preference

            # Rating: normalized 0-1
            rating_score = (movie.rating or 5.0) / 10.0

            # Position: TMDB discover returns by popularity; earlier = better
            total = max(len(candidates), 1)
            position_score = 1.0 - (position / total)

            # Recency bonus
            recency_score = 0.5
            if prefer_recent and movie.year:
                if movie.year >= 2020:
                    recency_score = 1.0
                elif movie.year >= 2015:
                    recency_score = 0.7

            # Weighted composite
            composite = (
                genre_overlap   * 40 +
                rating_score    * 30 +
                position_score  * 20 +
                recency_score   * 10
            )
            scored.append((composite, position, movie))

        scored.sort(key=lambda x: -x[0])

        results: list[Recommendation] = []
        for rank, (score, _, movie) in enumerate(scored[:limit], start=1):
            match_pct = min(int(score), 100)
            genre_list = ", ".join(movie.genres[:2]) if movie.genres else "your taste"
            results.append(Recommendation(
                movie=movie,
                rank=rank,
                match_score=match_pct,
                reason=f"{movie.title} is a strong {genre_list} pick.",
                watch_context="Great choice for tonight.",
                provider=f"{self.name}-deterministic",
                model="deterministic",
            ))

        logger.info(
            "[LLM] Deterministic fallback produced %d recommendations",
            len(results),
        )
        return results

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
