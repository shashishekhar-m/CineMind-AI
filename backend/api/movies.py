from __future__ import annotations

import psycopg

from fastapi import APIRouter, Depends, Query

from backend.schemas.movie import MovieResult
from backend.schemas.search import (
    RecommendationResponse,
    SemanticSearchResponse,
)
from recommendation.recommender import (
    semantic_recommendations,
)
from backend.services.database import get_db
from backend.services.movie_service import search_movies
from backend.services.semantic_service import semantic_search


router = APIRouter(
    prefix="/movies",
    tags=["Movies"],
)


@router.get(
    "/search",
    response_model=list[MovieResult],
)
def movie_search(
    q: str = Query(
        min_length=1,
        max_length=200,
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    conn: psycopg.Connection = Depends(get_db),
) -> list[MovieResult]:

    return search_movies(
        conn=conn,
        query=q,
        limit=limit,
    )


@router.get(
    "/semantic-search",
    response_model=SemanticSearchResponse,
)
def movie_semantic_search(
    q: str = Query(
        min_length=2,
        max_length=500,
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    conn: psycopg.Connection = Depends(get_db),
) -> SemanticSearchResponse:

    results = semantic_search(
        conn=conn,
        query=q,
        limit=limit,
    )

    return SemanticSearchResponse(
        query=q,
        results=results,
    )

@router.get(
    "/{imdb_id}/recommendations",
    response_model=RecommendationResponse,
)
def movie_recommendations(
    imdb_id: str,
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
) -> RecommendationResponse:

    results = semantic_recommendations(
        imdb_id=imdb_id,
        limit=limit,
    )

    return RecommendationResponse(
        imdb_id=imdb_id,
        results=results,
    )