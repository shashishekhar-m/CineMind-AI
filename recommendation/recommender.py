from __future__ import annotations

import os
from typing import Any

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

load_dotenv()

MODEL_ID = 1
MODEL_VERSION = "1.0.0"


def semantic_recommendations(
    imdb_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    conn = psycopg.connect(database_url)

    register_vector(conn)

    try:
        with conn.cursor() as cur:

            # Find the source movie embedding.
            cur.execute(
                """
                SELECT
                    me.embedding_vector
                FROM cinemind.movie_embeddings AS me
                JOIN cinemind.movies AS m
                    ON m.movie_id = me.movie_id
                WHERE m.imdb_id = %s
                  AND me.model_id = %s
                  AND me.embedding_version = %s
                  AND me.is_active = TRUE
                  AND m.deleted_at IS NULL
                LIMIT 1
                """,
                (
                    imdb_id,
                    MODEL_ID,
                    MODEL_VERSION,
                ),
            )

            source = cur.fetchone()

            if not source:
                return []

            query_vector = source[0]

            # Find similar movies.
            cur.execute(
                """
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
                            <=> %s
                        )
                    )::numeric AS similarity

                FROM cinemind.movie_embeddings AS me

                JOIN cinemind.movies AS m
                    ON m.movie_id = me.movie_id

                WHERE me.model_id = %s
                  AND me.embedding_version = %s
                  AND me.is_active = TRUE
                  AND m.deleted_at IS NULL
                  AND m.title_type = 'movie'
                  AND m.imdb_id <> %s
                  AND m.title IS NOT NULL
                  AND BTRIM(m.title) <> ''

                ORDER BY
                    me.embedding_vector <=> %s

                LIMIT %s
                """,
                (
                    query_vector,
                    MODEL_ID,
                    MODEL_VERSION,
                    imdb_id,
                    query_vector,
                    limit,
                ),
            )

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

    finally:
        conn.close()