from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import Settings
from app.schemas.movies import MovieCandidate


TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w780"
YOUTUBE_WATCH_BASE_URL = "https://www.youtube.com/watch"
logger = logging.getLogger(__name__)


GENRE_IDS: dict[str, int] = {
    "action": 28,
    "adventure": 12,
    "animation": 16,
    "comedy": 35,
    "crime": 80,
    "documentary": 99,
    "drama": 18,
    "family": 10751,
    "fantasy": 14,
    "history": 36,
    "horror": 27,
    "music": 10402,
    "mystery": 9648,
    "romance": 10749,
    "sci-fi": 878,
    "science fiction": 878,
    "thriller": 53,
    "war": 10752,
    "western": 37,
    # TMDB does not expose "noir" as a top-level genre. Crime is the closest MVP fit.
    "noir": 80,
    "romantic comedy": 10749,
}


GENRE_NAMES: dict[int, str] = {
    value: key.title().replace("Sci-Fi", "Sci-Fi")
    for key, value in GENRE_IDS.items()
    if key not in {"science fiction", "noir"}
}
GENRE_NAMES[35] = "Comedy"
GENRE_NAMES[10749] = "Romance"


LANGUAGE_CODES: dict[str, str] = {
    "english": "en",
    "hindi": "hi",
    "japanese": "ja",
    "korean": "ko",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "tamil": "ta",
    "telugu": "te",
    "malayalam": "ml",
}


class TMDBService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = "https://api.themoviedb.org/3"
        self.last_query: dict[str, Any] = {}

    async def search_movies(
        self,
        query: str,
        *,
        year: int | None = None,
        language: str = "en-US",
        page: int = 1,
    ) -> list[MovieCandidate]:
        if not query.strip():
            return []

        data = await self._get(
            "/search/movie",
            {
                "query": query,
                "include_adult": "false",
                "language": language,
                "page": page,
                **({"year": year} if year else {}),
            },
        )
        return await self._with_trailers(self._normalize_results(data.get("results", [])))

    async def fetch_movie_details(self, movie_id: int | str, *, language: str = "en-US") -> MovieCandidate:
        data = await self._get(
            f"/movie/{movie_id}",
            {"language": language, "append_to_response": "videos"},
        )
        movie = self.normalize_movie(data)
        if movie.trailer_url:
            return movie

        return (await self._with_trailers([movie]))[0]

    async def discover_movies_by_genre(
        self,
        genre: str | int,
        *,
        limit: int = 10,
        language: str = "en-US",
    ) -> list[MovieCandidate]:
        genre_id = self._genre_id(genre)
        if genre_id is None:
            logger.info("Unknown TMDB genre requested genre=%s", genre)
            return []

        return await self._discover(
            {"with_genres": genre_id, "language": language, "sort_by": "popularity.desc"},
            limit=limit,
        )

    async def discover_movies_by_language(
        self,
        language: str,
        *,
        limit: int = 10,
    ) -> list[MovieCandidate]:
        language_code = self._language_code(language)
        return await self._discover(
            {"with_original_language": language_code, "sort_by": "popularity.desc"},
            limit=limit,
        )

    async def discover_movies_by_year(
        self,
        year: int,
        *,
        limit: int = 10,
    ) -> list[MovieCandidate]:
        return await self._discover(
            {"primary_release_year": year, "sort_by": "popularity.desc"},
            limit=limit,
        )

    async def discover_movies_by_rating(
        self,
        minimum_rating: float = 7.0,
        *,
        limit: int = 10,
    ) -> list[MovieCandidate]:
        return await self._discover(
            {
                "vote_average.gte": minimum_rating,
                "vote_count.gte": 100,
                "sort_by": "vote_average.desc",
            },
            limit=limit,
        )

    async def discover_movies_by_popularity(
        self,
        *,
        limit: int = 10,
    ) -> list[MovieCandidate]:
        return await self._discover({"sort_by": "popularity.desc"}, limit=limit)

    async def fetch_videos_for_movie(
        self,
        movie_id: int | str,
        *,
        language: str = "en-US",
    ) -> list[dict[str, Any]]:
        try:
            data = await self._get(f"/movie/{movie_id}/videos", {"language": language})
            results = data.get("results", [])
            if isinstance(results, list) and results:
                return results

            fallback_data = await self._get(f"/movie/{movie_id}/videos", {})
            fallback_results = fallback_data.get("results", [])
            return fallback_results if isinstance(fallback_results, list) else []
        except Exception as exc:
            logger.info("TMDB videos unavailable movie_id=%s error=%s", movie_id, exc)
            return []

    async def fetch_trailer_for_movie(self, movie_id: int | str) -> dict[str, str] | None:
        videos = await self.fetch_videos_for_movie(movie_id)
        trailer = self._select_best_trailer(videos)
        if trailer:
            logger.info(
                "TMDB trailer selected movie_id=%s source=%s key=%s",
                movie_id,
                trailer["source"],
                trailer["key"],
            )
        else:
            logger.info("TMDB trailer unavailable movie_id=%s", movie_id)
        return trailer

    async def fetch_candidates(self, preferences: dict[str, Any], limit: int = 8) -> list[MovieCandidate]:
        params = self._build_discover_params(preferences)
        logger.info("TMDB credentials configured=%s", self.settings.has_tmdb_credentials)

        try:
            return await self._discover(params, limit=limit)
        except Exception as exc:
            logger.warning("TMDB candidate fetch failed preferences=%s error=%s", preferences, exc)
            return []

    def normalize_movie(self, raw_movie: dict[str, Any]) -> MovieCandidate:
        release_date = raw_movie.get("release_date") or ""
        release_year = int(release_date[:4]) if release_date[:4].isdigit() else None
        genres = self._normalize_genres(raw_movie)
        trailer = self._select_best_trailer(self._extract_embedded_videos(raw_movie))

        return MovieCandidate(
            id=str(raw_movie.get("id") or raw_movie.get("title") or raw_movie.get("original_title")),
            tmdb_id=raw_movie.get("id"),
            title=raw_movie.get("title") or raw_movie.get("original_title") or "Untitled Movie",
            year=release_year,
            genres=genres,
            runtime_minutes=raw_movie.get("runtime"),
            language=raw_movie.get("original_language"),
            poster_url=self._image_url(raw_movie.get("poster_path")),
            backdrop_url=self._image_url(raw_movie.get("backdrop_path")),
            synopsis=raw_movie.get("overview") or None,
            overview=raw_movie.get("overview") or None,
            rating=raw_movie.get("vote_average"),
            trailer_key=trailer["key"] if trailer else None,
            trailer_url=trailer["url"] if trailer else None,
            trailer_source=trailer["source"] if trailer else None,
        )

    async def _discover(self, params: dict[str, Any], *, limit: int) -> list[MovieCandidate]:
        query_params = {
            "include_adult": "false",
            "include_video": "false",
            "language": "en-US",
            "page": 1,
            "vote_count.gte": 80,
            **params,
        }
        self.last_query = {"endpoint": "/discover/movie", "params": query_params}

        for attempt, attempt_params in enumerate(self._broadened_queries(query_params), start=1):
            self.last_query = {
                "endpoint": "/discover/movie",
                "attempt": attempt,
                "params": self._sanitize_params(attempt_params),
            }
            data = await self._get("/discover/movie", attempt_params)
            movies = self._normalize_results(data.get("results", []))
            if movies:
                logger.info(
                    "TMDB discover returned candidates attempt=%s count=%s",
                    attempt,
                    len(movies),
                )
                return await self._with_trailers(movies[:limit])

            logger.info("TMDB discover returned no candidates attempt=%s query=%s", attempt, self.last_query)

        return []

    def _build_discover_params(self, preferences: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {"sort_by": "popularity.desc"}
        genre_values = preferences.get("genres")
        genres = genre_values if isinstance(genre_values, list) else []
        genre_ids = [
            genre_id
            for genre in genres
            if isinstance(genre, str) and (genre_id := self._genre_id(genre)) is not None
        ]

        genre = preferences.get("genre")
        if not genre_ids and isinstance(genre, str) and genre:
            if genre.lower() == "romantic comedy":
                genre_ids = [GENRE_IDS["comedy"], GENRE_IDS["romance"]]
            elif genre_id := self._genre_id(genre):
                genre_ids = [genre_id]

        if genre_ids:
            unique_genre_ids = list(dict.fromkeys(genre_ids))
            params["with_genres"] = ",".join(str(genre_id) for genre_id in unique_genre_ids)

        avoid_values = preferences.get("avoid_genres")
        avoid_genres = avoid_values if isinstance(avoid_values, list) else []
        avoid_ids = [
            genre_id
            for genre in avoid_genres
            if isinstance(genre, str) and (genre_id := self._genre_id(genre)) is not None
        ]
        if avoid_ids:
            params["without_genres"] = ",".join(str(genre_id) for genre_id in dict.fromkeys(avoid_ids))

        language = preferences.get("language")
        if isinstance(language, str) and language:
            params["with_original_language"] = self._language_code(language)

        year = preferences.get("year")
        if isinstance(year, int):
            params["primary_release_year"] = year

        year_start = preferences.get("year_start")
        year_end = preferences.get("year_end")
        if isinstance(year_start, int):
            params["primary_release_date.gte"] = f"{year_start}-01-01"
        if isinstance(year_end, int):
            params["primary_release_date.lte"] = f"{year_end}-12-31"

        rating = preferences.get("rating") or preferences.get("minimum_rating")
        if isinstance(rating, (int, float)):
            params["vote_average.gte"] = float(rating)

        runtime = preferences.get("runtime")
        max_runtime = preferences.get("max_runtime_minutes")
        min_runtime = preferences.get("min_runtime_minutes")
        target_runtime = preferences.get("target_runtime_minutes")
        if isinstance(max_runtime, int):
            params["with_runtime.lte"] = max_runtime
        elif runtime == "under 2 hours":
            params["with_runtime.lte"] = 120

        if isinstance(min_runtime, int):
            params["with_runtime.gte"] = min_runtime
        elif isinstance(target_runtime, int):
            params["with_runtime.gte"] = max(target_runtime - 20, 1)
            params["with_runtime.lte"] = target_runtime + 20

        mood = str(preferences.get("mood") or "").lower()
        if mood in {"lighthearted", "fun", "comfort", "comforting"}:
            params.setdefault("vote_average.gte", 6.0)
            params["sort_by"] = "popularity.desc"

        popularity = str(preferences.get("popularity_preference") or preferences.get("vibe") or "").lower()
        if popularity == "underrated":
            params["sort_by"] = "vote_average.desc"
            params["vote_count.gte"] = 50
            params["vote_count.lte"] = 1500
        elif popularity == "popular":
            params["sort_by"] = "popularity.desc"
            params["vote_count.gte"] = max(int(params.get("vote_count.gte", 80)), 400)
        elif popularity == "new":
            params["sort_by"] = "popularity.desc"
            params.setdefault("primary_release_date.gte", "2020-01-01")
        elif popularity == "classic":
            params.setdefault("primary_release_date.lte", "1999-12-31")

        return params

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.settings.tmdb_api_key:
            raise RuntimeError("TMDB_API_KEY is not configured")

        query_params = {
            "api_key": self.settings.tmdb_api_key,
            **(params or {}),
        }
        safe_params = self._sanitize_params(query_params)
        logger.info("TMDB request endpoint=%s params=%s", path, safe_params)

        async with httpx.AsyncClient(timeout=12) as client:
            try:
                response = await client.get(f"{self.base_url}{path}", params=query_params)
                logger.info(
                    "TMDB response endpoint=%s status=%s params=%s",
                    path,
                    response.status_code,
                    safe_params,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:240].replace(self.settings.tmdb_api_key, "[redacted]")
                logger.warning(
                    "TMDB HTTP error endpoint=%s status=%s params=%s body=%s",
                    path,
                    exc.response.status_code,
                    safe_params,
                    body,
                )
                raise
            except httpx.RequestError as exc:
                logger.warning("TMDB request error endpoint=%s params=%s error=%s", path, safe_params, exc)
                raise

    def _normalize_results(self, results: list[dict[str, Any]]) -> list[MovieCandidate]:
        return [self.normalize_movie(result) for result in results]

    async def _with_trailers(self, movies: list[MovieCandidate]) -> list[MovieCandidate]:
        movies_without_trailers = [
            movie
            for movie in movies
            if movie.tmdb_id is not None and not movie.trailer_url and not movie.is_fallback
        ]
        if not movies_without_trailers:
            return movies

        trailers = await asyncio.gather(
            *(self.fetch_trailer_for_movie(movie.tmdb_id) for movie in movies_without_trailers),
            return_exceptions=True,
        )

        trailer_by_movie_id: dict[int, dict[str, str]] = {}
        for movie, trailer in zip(movies_without_trailers, trailers, strict=False):
            if isinstance(trailer, dict) and movie.tmdb_id is not None:
                trailer_by_movie_id[movie.tmdb_id] = trailer

        enriched: list[MovieCandidate] = []
        for movie in movies:
            trailer = trailer_by_movie_id.get(movie.tmdb_id or -1)
            if not trailer:
                enriched.append(movie)
                continue

            enriched.append(
                movie.model_copy(
                    update={
                        "trailer_key": trailer["key"],
                        "trailer_url": trailer["url"],
                        "trailer_source": trailer["source"],
                    }
                )
            )

        return enriched

    def _normalize_genres(self, raw_movie: dict[str, Any]) -> list[str]:
        detail_genres = raw_movie.get("genres")
        if isinstance(detail_genres, list) and detail_genres:
            return [
                genre.get("name")
                for genre in detail_genres
                if isinstance(genre, dict) and genre.get("name")
            ]

        genre_ids = raw_movie.get("genre_ids")
        if isinstance(genre_ids, list):
            return [GENRE_NAMES.get(genre_id, str(genre_id)) for genre_id in genre_ids]

        return []

    def _genre_id(self, genre: str | int) -> int | None:
        if isinstance(genre, int):
            return genre

        lowered = genre.strip().lower()
        return GENRE_IDS.get(lowered)

    def _language_code(self, language: str) -> str:
        lowered = language.strip().lower()
        return LANGUAGE_CODES.get(lowered, lowered[:2] or "en")

    def _broadened_queries(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        attempts: list[dict[str, Any]] = [params]

        if "," in str(params.get("with_genres", "")):
            attempts.append({**params, "with_genres": str(params["with_genres"]).replace(",", "|")})

        attempts.append({
            **params,
            "vote_count.gte": min(int(params.get("vote_count.gte", 80)), 30),
        })

        without_exclusions = {
            key: value
            for key, value in params.items()
            if key not in {"without_genres", "with_runtime.gte", "with_runtime.lte"}
        }
        attempts.append(without_exclusions)

        without_dates = {
            key: value
            for key, value in without_exclusions.items()
            if key
            not in {
                "primary_release_year",
                "primary_release_date.gte",
                "primary_release_date.lte",
                "vote_average.gte",
            }
        }
        attempts.append(without_dates)

        if "with_genres" in without_dates:
            attempts.append({
                key: value
                for key, value in without_dates.items()
                if key != "with_original_language"
            })

        unique_attempts: list[dict[str, Any]] = []
        seen: set[tuple[tuple[str, str], ...]] = set()
        for attempt in attempts:
            marker = tuple(sorted((key, str(value)) for key, value in attempt.items()))
            if marker not in seen:
                unique_attempts.append(attempt)
                seen.add(marker)

        return unique_attempts

    def _sanitize_params(self, params: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in params.items() if key != "api_key"}

    def _image_url(self, path: str | None) -> str | None:
        if not path:
            return None

        return f"{TMDB_IMAGE_BASE_URL}{path}"

    def _extract_embedded_videos(self, raw_movie: dict[str, Any]) -> list[dict[str, Any]]:
        videos = raw_movie.get("videos")
        if not isinstance(videos, dict):
            return []

        results = videos.get("results")
        return results if isinstance(results, list) else []

    def _select_best_trailer(self, videos: list[dict[str, Any]]) -> dict[str, str] | None:
        candidates = [
            video
            for video in videos
            if isinstance(video, dict)
            and str(video.get("site") or "").lower() == "youtube"
            and video.get("key")
        ]
        if not candidates:
            return None

        def score(video: dict[str, Any]) -> tuple[int, str]:
            video_type = str(video.get("type") or "").lower()
            name = str(video.get("name") or "").lower()
            official = bool(video.get("official"))
            score_value = 0

            if official:
                score_value += 100
            if video_type == "trailer":
                score_value += 80
            elif video_type == "teaser":
                score_value += 35
            elif video_type == "clip":
                score_value += 10
            if "official trailer" in name:
                score_value += 40
            elif "trailer" in name:
                score_value += 20
            if "teaser" in name:
                score_value -= 8
            if "behind" in name or "featurette" in name:
                score_value -= 25

            return score_value, str(video.get("published_at") or "")

        best = max(candidates, key=score)
        key = str(best["key"])
        return {
            "key": key,
            "url": f"{YOUTUBE_WATCH_BASE_URL}?v={key}",
            "source": "YouTube",
        }
    
    async def fetch_trending(self, *, limit: int = 20) -> list[MovieCandidate]:
        """Trending movies this week."""
        data = await self._get("/trending/movie/week", {"language": "en-US"})
        movies = self._normalize_results(data.get("results", []))
        return await self._with_trailers(movies[:limit])

    async def fetch_new_releases(self, *, limit: int = 20) -> list[MovieCandidate]:
        """Movies released in the past 90 days."""
        from datetime import datetime, timedelta
        today = datetime.utcnow().date()
        ninety_days_ago = today - timedelta(days=90)
        return await self._discover(
            {
                "primary_release_date.gte": str(ninety_days_ago),
                "primary_release_date.lte": str(today),
                "sort_by": "popularity.desc",
                "vote_count.gte": 30,
            },
            limit=limit,
        )

    async def fetch_top_rated(self, *, limit: int = 20) -> list[MovieCandidate]:
        """All-time top rated."""
        return await self._discover(
            {
                "sort_by": "vote_average.desc",
                "vote_count.gte": 1000,
                "vote_average.gte": 7.5,
            },
            limit=limit,
        )

    async def fetch_watch_providers(
        self,
        movie_id: int,
        *,
        country: str = "IN",
    ) -> dict:
        """
        Returns watch providers for a movie in the given country.
        Returns a dict with keys: streaming, rent, buy — each a list of provider dicts.
        """
        try:
            data = await self._get(f"/movie/{movie_id}/watch/providers", {})
            results = data.get("results", {})
            country_data = results.get(country.upper(), {})

            def normalize_providers(raw: list) -> list[dict]:
                return [
                    {
                        "id":       p.get("provider_id"),
                        "name":     p.get("provider_name"),
                        "logoUrl":  self._image_url(p.get("logo_path")),
                    }
                    for p in raw
                    if isinstance(p, dict) and p.get("provider_name")
                ]

            return {
                "streaming": normalize_providers(country_data.get("flatrate", [])),
                "rent":      normalize_providers(country_data.get("rent", [])),
                "buy":       normalize_providers(country_data.get("buy", [])),
                "link":      country_data.get("link"),
            }
        except Exception as exc:
            logger.warning("Watch providers fetch failed movie_id=%s error=%s", movie_id, exc)
            return {"streaming": [], "rent": [], "buy": [], "link": None}