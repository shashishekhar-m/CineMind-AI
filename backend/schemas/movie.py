from __future__ import annotations

from pydantic import BaseModel


class MovieResult(BaseModel):
    movie_id: int
    imdb_id: str | None
    title: str
    release_year: int | None
    poster_url: str | None
    overview: str | None


class MovieSearchResult(MovieResult):
    similarity: float | None = None