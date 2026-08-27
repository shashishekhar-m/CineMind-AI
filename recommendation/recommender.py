from __future__ import annotations

import os
from typing import Any

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

load_dotenv()


def semantic_recommendations(
    imdb_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:

    conn = psycopg.connect(
        os.environ["DATABASE_URL"]
    )

    register_vector(conn)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT me.embedding_vector
            FROM cinemind.movie_embeddings me
            JOIN cinemind.movies m
                ON m.movie_id = me.movie_id
            WHERE m.imdb_id = %s
              AND me.is_active = TRUE
            LIMIT 1
            """,
            (imdb_id,),
        )

        source = cur.fetchone()

        if not source:
            conn.close()
            return []

        query_vector = source[0]

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

            FROM cinemind.movie_embeddings me

            JOIN cinemind.movies m
                ON m.movie_id = me.movie_id

            WHERE me.is_active = TRUE
              AND m.title_type = 'movie'
              AND m.imdb_id <> %s

            ORDER BY
                me.embedding_vector <=> %s

            LIMIT %s
            """,
            (
                query_vector,
                imdb_id,
                query_vector,
                limit,
            ),
        )

        rows = cur.fetchall()

    conn.close()

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