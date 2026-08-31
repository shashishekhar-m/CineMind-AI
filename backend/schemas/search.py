from __future__ import annotations

from pydantic import BaseModel, Field

from backend.schemas.movie import MovieSearchResult


class SemanticSearchRequest(BaseModel):
    query: str = Field(
        min_length=2,
        max_length=500,
    )

    limit: int = Field(
        default=20,
        ge=1,
        le=100,
    )


class SemanticSearchResponse(BaseModel):
    query: str
    results: list[MovieSearchResult]

class RecommendationResponse(BaseModel):
    imdb_id: str
    results: list[MovieSearchResult]