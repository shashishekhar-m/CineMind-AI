from __future__ import annotations

from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from pgvector import Vector
from sentence_transformers import SentenceTransformer


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_ID = 1
MODEL_VERSION = "1.0.0"
EMBEDDING_DIMENSION = 384


_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model

    if _model is None:
        print("Loading semantic search model...")
        _model = SentenceTransformer(MODEL_NAME)
        print("Semantic search model loaded.")

    return _model


def semantic_search(
    conn: psycopg.Connection,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:

    model = get_model()

    query_embedding = model.encode(
        query,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )

    if len(query_embedding) != EMBEDDING_DIMENSION:
        raise RuntimeError(
            "Unexpected embedding dimension."
        )

    query_vector = Vector(
        query_embedding.tolist()
    )

    register_vector(conn)

    sql = """
        SELECT
            m.movie_id,
            m.imdb_id,
            m.title,
            m.release_year,
            m.poster_url,
            m.overview,
            (
                1 - (
                    me.embedding_vector
                    <=> %(query_vector)s
                )
            )::numeric AS similarity

        FROM cinemind.movie_embeddings AS me

        JOIN cinemind.movies AS m
            ON m.movie_id = me.movie_id

        WHERE me.model_id = %(model_id)s
          AND me.embedding_version = %(model_version)s
          AND me.is_active = TRUE
          AND m.deleted_at IS NULL

        ORDER BY
            me.embedding_vector
            <=> %(query_vector)s

        LIMIT %(limit)s;
    """

    params = {
        "query_vector": query_vector,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "limit": limit,
    }

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {
            "movie_id": row[0],
            "imdb_id": row[1],
            "title": row[2],
            "release_year": row[3],
            "poster_url": row[4],
            "overview": row[5],
            "similarity": float(row[6]),
        }
        for row in rows
    ]