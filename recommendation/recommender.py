from __future__ import annotations

import os
from typing import Any

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector


load_dotenv()


# ============================================================
# Recommendation configuration
# ============================================================

MODEL_ID = 1
MODEL_VERSION = "1.0.0"

SEMANTIC_WEIGHT = 0.60
GENRE_WEIGHT = 0.25
POPULARITY_WEIGHT = 0.15

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# Retrieve more candidates than the final requested amount.
# This gives the hybrid ranking enough candidates to work with.
CANDIDATE_MULTIPLIER = 5
MIN_CANDIDATES = 100


# ============================================================
# Database
# ============================================================

def get_database_url() -> str:
    """
    Return the configured PostgreSQL connection URL.
    """

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    return database_url


# ============================================================
# Recommendation engine
# ============================================================

def semantic_recommendations(
    imdb_id: str,
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """
    Generate hybrid movie recommendations.

    Ranking:

        60% semantic similarity
        25% genre similarity
        15% popularity

    Semantic similarity is generated from the movie embedding.

    Genre similarity is calculated from the overlap between
    the source movie's genres and candidate movie's genres.

    Popularity uses ranking_score when available, followed by
    weighted_rating and IMDb rating as fallbacks.

    TF-IDF is intentionally not used yet because the current
    dataset does not have sufficient descriptive-text coverage.
    """

    # --------------------------------------------------------
    # Validate limit
    # --------------------------------------------------------

    if limit < 1:
        limit = DEFAULT_LIMIT

    limit = min(limit, MAX_LIMIT)

    candidate_limit = max(
        limit * CANDIDATE_MULTIPLIER,
        MIN_CANDIDATES,
    )

    database_url = get_database_url()

    conn = psycopg.connect(database_url)

    # Register PostgreSQL vector support.
    register_vector(conn)

    try:

        with conn.cursor() as cur:

            # =================================================
            # 1. Find source movie + embedding
            # =================================================

            cur.execute(
                """
                SELECT
                    m.movie_id,
                    m.imdb_id,
                    m.title,
                    me.embedding_vector
                FROM cinemind.movies AS m

                INNER JOIN cinemind.movie_embeddings AS me
                    ON me.movie_id = m.movie_id

                WHERE m.imdb_id = %s
                  AND m.deleted_at IS NULL

                  AND me.model_id = %s
                  AND me.embedding_version = %s
                  AND me.is_active = TRUE

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

            (
                source_movie_id,
                source_imdb_id,
                source_title,
                query_vector,
            ) = source

            # =================================================
            # 2. Find source movie genres
            # =================================================

            cur.execute(
                """
                SELECT
                    mg.genre_id
                FROM cinemind.movie_genres AS mg

                WHERE mg.movie_id = %s
                """,
                (source_movie_id,),
            )

            source_genres = {
                row[0]
                for row in cur.fetchall()
                if row[0] is not None
            }

            # =================================================
            # 3. Retrieve semantic candidates
            #
            # HNSW is used here through the vector ORDER BY.
            # We retrieve more movies than requested so that
            # hybrid ranking has enough candidates.
            # =================================================

            cur.execute(
                """
                WITH semantic_candidates AS (

                    SELECT
                        me.movie_id,
                        me.embedding_vector,

                        (
                            1 - (
                                me.embedding_vector
                                <=> %s
                            )
                        ) AS semantic_similarity

                    FROM cinemind.movie_embeddings AS me

                    WHERE me.model_id = %s
                      AND me.embedding_version = %s
                      AND me.is_active = TRUE

                    ORDER BY
                        me.embedding_vector <=> %s

                    LIMIT %s
                )

                SELECT
                    m.movie_id,
                    m.imdb_id,
                    m.title,
                    m.release_year,
                    m.poster_url,
                    m.overview,

                    sc.semantic_similarity,

                    mr.imdb_rating,
                    mr.imdb_vote_count,
                    mr.popularity_score,
                    mr.weighted_rating,
                    mr.trending_score,
                    mr.ranking_score,

                    COUNT(
                        DISTINCT
                        CASE
                            WHEN mg.genre_id = ANY(%s)
                            THEN mg.genre_id
                        END
                    ) AS matching_genres,

                    COUNT(
                        DISTINCT mg.genre_id
                    ) AS candidate_genres

                FROM semantic_candidates AS sc

                INNER JOIN cinemind.movies AS m
                    ON m.movie_id = sc.movie_id

                LEFT JOIN cinemind.movie_ratings AS mr
                    ON mr.movie_id = m.movie_id

                LEFT JOIN cinemind.movie_genres AS mg
                    ON mg.movie_id = m.movie_id

                WHERE m.deleted_at IS NULL
                  AND m.title_type = 'movie'

                  AND m.movie_id <> %s

                  AND m.title IS NOT NULL
                  AND BTRIM(m.title) <> ''

                GROUP BY
                    m.movie_id,
                    m.imdb_id,
                    m.title,
                    m.release_year,
                    m.poster_url,
                    m.overview,
                    sc.semantic_similarity,
                    mr.imdb_rating,
                    mr.imdb_vote_count,
                    mr.popularity_score,
                    mr.weighted_rating,
                    mr.trending_score,
                    mr.ranking_score

                ORDER BY
                    sc.semantic_similarity DESC
                """,
                (
                    query_vector,
                    MODEL_ID,
                    MODEL_VERSION,
                    query_vector,
                    candidate_limit,
                    list(source_genres),
                    source_movie_id,
                ),
            )

            candidates = cur.fetchall()

        # =====================================================
        # 4. Calculate hybrid ranking
        # =====================================================

        recommendations: list[dict[str, Any]] = []

        source_genre_count = len(source_genres)

        for row in candidates:

            (
                movie_id,
                candidate_imdb_id,
                title,
                release_year,
                poster_url,
                overview,
                semantic_similarity,
                imdb_rating,
                imdb_vote_count,
                popularity_score,
                weighted_rating,
                trending_score,
                ranking_score,
                matching_genres,
                candidate_genres,
            ) = row

            # -------------------------------------------------
            # Semantic score
            # -------------------------------------------------

            semantic_score = float(
                semantic_similarity or 0.0
            )

            semantic_score = min(
                max(semantic_score, 0.0),
                1.0,
            )

            # -------------------------------------------------
            # Genre score
            #
            # If the source movie has:
            #
            # Drama
            #
            # and the candidate also has Drama:
            #
            # matching = 1
            # source genres = 1
            # score = 1.0
            #
            # For multiple source genres, this represents the
            # percentage of source genres shared by candidate.
            # -------------------------------------------------

            if (
                source_genre_count > 0
                and matching_genres is not None
            ):
                genre_score = (
                    float(matching_genres)
                    / float(source_genre_count)
                )

                genre_score = min(
                    max(genre_score, 0.0),
                    1.0,
                )

            else:
                genre_score = 0.0

            # -------------------------------------------------
            # Popularity score
            #
            # ranking_score is preferred.
            #
            # weighted_rating is the second fallback.
            #
            # IMDb rating is the final fallback.
            # -------------------------------------------------

            if ranking_score is not None:

                popularity_score_normalized = min(
                    max(
                        float(ranking_score),
                        0.0,
                    ),
                    1.0,
                )

            elif weighted_rating is not None:

                popularity_score_normalized = min(
                    max(
                        float(weighted_rating) / 10.0,
                        0.0,
                    ),
                    1.0,
                )

            elif imdb_rating is not None:

                popularity_score_normalized = min(
                    max(
                        float(imdb_rating) / 10.0,
                        0.0,
                    ),
                    1.0,
                )

            else:

                popularity_score_normalized = 0.0

            # -------------------------------------------------
            # Hybrid score
            # -------------------------------------------------

            hybrid_score = (
                SEMANTIC_WEIGHT
                * semantic_score
                +
                GENRE_WEIGHT
                * genre_score
                +
                POPULARITY_WEIGHT
                * popularity_score_normalized
            )

            # -------------------------------------------------
            # Store recommendation
            # -------------------------------------------------

            recommendations.append(
                {
                    "movie_id": movie_id,
                    "imdb_id": candidate_imdb_id,
                    "title": title,
                    "release_year": release_year,
                    "poster_url": poster_url,
                    "overview": overview,

                    "similarity": round(
                        semantic_score,
                        6,
                    ),

                    "genre_score": round(
                        genre_score,
                        6,
                    ),

                    "popularity_score": round(
                        popularity_score_normalized,
                        6,
                    ),

                    "hybrid_score": round(
                        hybrid_score,
                        6,
                    ),
                }
            )

        # =====================================================
        # 5. Final ranking
        # =====================================================

        recommendations.sort(
            key=lambda item: (
                item["hybrid_score"],
                item["similarity"],
            ),
            reverse=True,
        )

        return recommendations[:limit]

    finally:

        conn.close()