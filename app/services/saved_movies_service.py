from abc import ABC, abstractmethod

from app.schemas.movies import SavedMovie, SavedMovieCreate


class SavedMoviesRepository(ABC):
    @abstractmethod
    def create(self, payload: SavedMovieCreate) -> SavedMovie:
        raise NotImplementedError

    @abstractmethod
    def list(self) -> list[SavedMovie]:
        raise NotImplementedError

    @abstractmethod
    def delete(self, saved_movie_id: str) -> bool:
        raise NotImplementedError


class InMemorySavedMoviesRepository(SavedMoviesRepository):
    def __init__(self):
        self._saved_movies: dict[str, SavedMovie] = {}

    def create(self, payload: SavedMovieCreate) -> SavedMovie:
        existing = self._find_existing(payload)
        if existing:
            return existing

        saved_movie = SavedMovie(
            movie=payload.movie,
            reason=payload.reason,
            match_score=payload.match_score,
        )
        self._saved_movies[saved_movie.id] = saved_movie
        return saved_movie

    def list(self) -> list[SavedMovie]:
        return sorted(
            self._saved_movies.values(),
            key=lambda item: item.created_at,
            reverse=True,
        )

    def delete(self, saved_movie_id: str) -> bool:
        return self._saved_movies.pop(saved_movie_id, None) is not None

    def _find_existing(self, payload: SavedMovieCreate) -> SavedMovie | None:
        for saved_movie in self._saved_movies.values():
            if saved_movie.movie.tmdb_id and saved_movie.movie.tmdb_id == payload.movie.tmdb_id:
                return saved_movie

            if saved_movie.movie.id == payload.movie.id:
                return saved_movie

        return None


class SavedMoviesService:
    def __init__(self, repository: SavedMoviesRepository | None = None):
        self.repository = repository or InMemorySavedMoviesRepository()

    def create(self, payload: SavedMovieCreate) -> SavedMovie:
        return self.repository.create(payload)

    def list(self) -> list[SavedMovie]:
        return self.repository.list()

    def delete(self, saved_movie_id: str) -> bool:
        return self.repository.delete(saved_movie_id)
