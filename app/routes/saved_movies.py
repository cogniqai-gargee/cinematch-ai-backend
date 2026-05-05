from fastapi import APIRouter, HTTPException, status

from app.schemas import SavedMovie, SavedMovieCreate
from app.services import get_saved_movies_service

router = APIRouter(tags=["saved movies"])


@router.post("/saved-movies", response_model=SavedMovie, status_code=status.HTTP_201_CREATED)
async def create_saved_movie(payload: SavedMovieCreate) -> SavedMovie:
    return get_saved_movies_service().create(payload)


@router.get("/saved-movies", response_model=list[SavedMovie])
async def list_saved_movies() -> list[SavedMovie]:
    return get_saved_movies_service().list()


@router.delete("/saved-movies/{id}")
async def delete_saved_movie(id: str) -> dict[str, object]:
    deleted = get_saved_movies_service().delete(id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved movie not found",
        )

    return {"deleted": True, "id": id}
