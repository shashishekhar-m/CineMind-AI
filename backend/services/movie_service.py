from __future__ import annotations

from typing import Any

import psycopg


def search_movies(
    conn: psycopg.Connection,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            m.movie_id,
            m.imdb_id,
            m.title,
            m.release_year,
            m.poster_url,
            m.overview
        FROM cinemind.movies AS m
        WHERE m.deleted_at IS NULL
          AND (
                m.title ILIKE %(query)s
                OR m.original_title ILIKE %(query)s
                OR m.imdb_id ILIKE %(query)s
          )
        ORDER BY
            CASE
                WHEN LOWER(m.title) = LOWER(%(exact_query)s)
                    THEN 0
                WHEN LOWER(m.title) LIKE LOWER(%(prefix_query)s)
                    THEN 1
                ELSE 2
            END,
            m.release_year DESC NULLS LAST,
            m.movie_id
        LIMIT %(limit)s;
    """

    params = {
        "query": f"%{query}%",
        "exact_query": query,
        "prefix_query": f"{query}%",
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
        }
        for row in rows
    ]