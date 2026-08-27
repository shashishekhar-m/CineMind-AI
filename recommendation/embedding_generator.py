# recommendation/embedding_generator.py

from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import datetime, timezone

import psycopg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from pgvector.psycopg import register_vector


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# EMBEDDING CONFIGURATION
# ============================================================

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_VERSION = "1.0.0"

EMBEDDING_DIMENSION = 384

# Number of database records fetched per iteration.
BATCH_SIZE = 128

# Number of texts encoded together by SentenceTransformer.
ENCODE_BATCH_SIZE = 32


# ============================================================
# DATASET FILTERING POLICY
# ============================================================

# CineMind currently generates semantic embeddings for
# movie/TV content released from this year onward.
#
# IMPORTANT:
# Existing embeddings for older titles are NOT deleted.
# They remain available in movie_embeddings.
EMBEDDING_START_YEAR = 2000


# These are the content types we currently want to expose
# through CineMind's semantic movie/series experience.
SUPPORTED_TITLE_TYPES = (
    "movie",
    "tv_series",
    "tv_movie",
    "tv_mini_series",
    "tv_special",
)


# ============================================================
# DATABASE
# ============================================================

def get_database_url() -> str:
    """
    Read DATABASE_URL from the environment.
    """

    url = os.getenv("DATABASE_URL")

    if not url:
        raise RuntimeError(
            "DATABASE_URL is not configured in the environment."
        )

    return url


# ============================================================
# MOVIE TEXT REPRESENTATION
# ============================================================

def build_movie_text(row: dict) -> str:
    """
    Build the semantic text representation used by
    SentenceTransformer.

    The same representation is used when calculating
    the checksum.
    """

    parts: list[str] = []

    title = row.get("title")
    original_title = row.get("original_title")
    overview = row.get("overview")
    tagline = row.get("tagline")
    release_year = row.get("release_year")
    genres = row.get("genres")
    keywords = row.get("keywords")

    if title:
        parts.append(f"Title: {title}")

    if original_title and original_title != title:
        parts.append(f"Original title: {original_title}")

    if release_year:
        parts.append(f"Year: {release_year}")

    if overview:
        parts.append(f"Overview: {overview}")

    if tagline:
        parts.append(f"Tagline: {tagline}")

    if genres:
        parts.append(f"Genres: {genres}")

    if keywords:
        parts.append(f"Keywords: {keywords}")

    return "\n".join(parts).strip()


# ============================================================
# CHECKSUM
# ============================================================

def checksum(text: str) -> str:
    """
    Generate a deterministic SHA-256 checksum for
    the semantic text representation.
    """

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


# ============================================================
# FETCH MOVIES
# ============================================================

def fetch_movies(
    conn,
    limit: int,
    last_movie_id: int,
    model_id:int,
):
    """
    Fetch the next batch of movies/series that require
    embeddings.

    IMPORTANT DESIGN:

    1. Only content from EMBEDDING_START_YEAR onward is selected.
    2. Only supported title types are selected.
    3. Existing active embeddings are skipped.
    4. movie_id > last_movie_id provides keyset pagination.
    5. PostgreSQL remains the source of truth for resume state.

    This means the process can safely be stopped and restarted.
    """

    query = """
        SELECT
            m.movie_id,
            m.title,
            m.original_title,
            m.release_year,
            m.overview,
            m.tagline,

            COALESCE(
                STRING_AGG(
                    DISTINCT g.genre_name::text,
                    ', '
                    ORDER BY g.genre_name::text
                ),
                ''
            ) AS genres,

            COALESCE(
                STRING_AGG(
                    DISTINCT k.keyword_name::text,
                    ', '
                    ORDER BY k.keyword_name::text
                ),
                ''
            ) AS keywords

        FROM cinemind.movies AS m

        LEFT JOIN cinemind.movie_genres AS mg
            ON mg.movie_id = m.movie_id

        LEFT JOIN cinemind.genres AS g
            ON g.genre_id = mg.genre_id

        LEFT JOIN cinemind.movie_keywords AS mk
            ON mk.movie_id = m.movie_id

        LEFT JOIN cinemind.keywords AS k
            ON k.keyword_id = mk.keyword_id

        WHERE m.movie_id > %s
          AND m.release_year >= %s

          AND m.title_type::text IN (
              'movie',
              'tv_series',
              'tv_movie',
              'tv_mini_series',
              'tv_special'
          )

          AND m.title IS NOT NULL
          AND m.deleted_at IS NULL

          AND NOT EXISTS (
              SELECT 1
              FROM cinemind.movie_embeddings AS me
              WHERE me.movie_id = m.movie_id
                AND me.model_id = %s
                AND me.embedding_version = %s
                AND me.is_active = TRUE
          )

        GROUP BY
            m.movie_id,
            m.title,
            m.original_title,
            m.release_year,
            m.overview,
            m.tagline

        ORDER BY m.movie_id

        LIMIT %s
    """

    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                last_movie_id,
                EMBEDDING_START_YEAR,
                model_id,
                MODEL_VERSION,
                limit,
            ),
        )

        columns = [desc.name for desc in cur.description]

        return [
            dict(zip(columns, row))
            for row in cur.fetchall()
        ]


# ============================================================
# MODEL REGISTRATION LOOKUP
# ============================================================

def get_model_id(conn) -> int:
    """
    Retrieve the active CineMind semantic model ID.
    """

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT model_id
            FROM cinemind.recommendation_models
            WHERE model_name = %s
              AND is_active = TRUE
            """,
            ("cinemind-semantic-v1",),
        )

        row = cur.fetchone()

        if not row:
            raise RuntimeError(
                "cinemind-semantic-v1 is not registered."
            )

        return row[0]


# ============================================================
# INSERT EMBEDDINGS
# ============================================================

def insert_embeddings(
    conn,
    rows,
    embeddings,
    model_id: int,
) -> int:
    """
    Insert generated embeddings into movie_embeddings.

    Existing records are protected by the unique constraint:

        (movie_id, model_id, embedding_version)

    ON CONFLICT keeps the operation idempotent.
    """

    now = datetime.now(timezone.utc)

    data = []

    for row, embedding in zip(rows, embeddings):

        text = build_movie_text(row)

        data.append(
            (
                row["movie_id"],
                model_id,
                embedding.tolist(),
                EMBEDDING_DIMENSION,
                "sentence-transformers",
                checksum(text),
                MODEL_VERSION,
                now,
                True,
                now,
                now,
            )
        )

    if not data:
        return 0

    query = """
        INSERT INTO cinemind.movie_embeddings (
            movie_id,
            model_id,
            embedding_vector,
            embedding_dimension,
            embedding_provider,
            embedding_checksum,
            embedding_version,
            generated_at,
            is_active,
            created_at,
            updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s
        )

        ON CONFLICT (
            movie_id,
            model_id,
            embedding_version
        )
        DO UPDATE SET
            embedding_vector = EXCLUDED.embedding_vector,
            embedding_dimension = EXCLUDED.embedding_dimension,
            embedding_provider = EXCLUDED.embedding_provider,
            embedding_checksum = EXCLUDED.embedding_checksum,
            generated_at = EXCLUDED.generated_at,
            is_active = TRUE,
            updated_at = EXCLUDED.updated_at
    """

    with conn.cursor() as cur:
        cur.executemany(query, data)

    conn.commit()

    return len(data)


# ============================================================
# MAIN
# ============================================================

def main():


    # --------------------------------------------------------
    # DATABASE URL
    # --------------------------------------------------------

    database_url = get_database_url()

    logger.info(
        "Embedding policy: release_year >= %s",
        EMBEDDING_START_YEAR,
    )

    logger.info(
        "Supported title types: %s",
        ", ".join(SUPPORTED_TITLE_TYPES),
    )

    # --------------------------------------------------------
    # LOAD MODEL
    # --------------------------------------------------------

    logger.info(
        "Loading embedding model: %s",
        MODEL_NAME,
    )

    model = SentenceTransformer(MODEL_NAME)

    dimension = model.get_sentence_embedding_dimension()

    logger.info(
        "Embedding dimension: %s",
        dimension,
    )

    if dimension != EMBEDDING_DIMENSION:
        raise RuntimeError(
            f"Unexpected embedding dimension: "
            f"{dimension}. Expected {EMBEDDING_DIMENSION}."
        )

    # --------------------------------------------------------
    # CONNECT DATABASE
    # --------------------------------------------------------

    conn = psycopg.connect(database_url)

    register_vector(conn)

    # --------------------------------------------------------
    # GET MODEL ID
    # --------------------------------------------------------

    model_id = get_model_id(conn)

    logger.info(
        "Using model_id=%s",
        model_id,
    )

    # --------------------------------------------------------
    # KEYSET PAGINATION
    # --------------------------------------------------------

    last_movie_id = 0

    total_processed = 0

    started = time.perf_counter()

    # --------------------------------------------------------
    # PROCESS LOOP
    # --------------------------------------------------------

    while True:

        rows = fetch_movies(
            conn,
            limit=BATCH_SIZE,
            last_movie_id=last_movie_id,
            model_id=model_id,
        )

        if not rows:
            break

        # ----------------------------------------------------
        # BUILD SEMANTIC TEXT
        # ----------------------------------------------------

        texts = [
            build_movie_text(row)
            for row in rows
        ]

        # ----------------------------------------------------
        # GENERATE EMBEDDINGS
        # ----------------------------------------------------

        embeddings = model.encode(
            texts,
            batch_size=ENCODE_BATCH_SIZE,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

        # ----------------------------------------------------
        # STORE EMBEDDINGS
        # ----------------------------------------------------

        inserted = insert_embeddings(
            conn,
            rows,
            embeddings,
            model_id,
        )

        total_processed += inserted

        # ----------------------------------------------------
        # ADVANCE KEYSET
        # ----------------------------------------------------

        last_movie_id = rows[-1]["movie_id"]

        # ----------------------------------------------------
        # LOG PROGRESS
        # ----------------------------------------------------

        elapsed = time.perf_counter() - started

        rate = (
            total_processed / elapsed
            if elapsed > 0
            else 0
        )

        logger.info(
            "Processed=%d | batch=%d | last_movie_id=%d | "
            "rate=%.2f movies/sec | elapsed=%.2fs",
            total_processed,
            len(rows),
            last_movie_id,
            rate,
            elapsed,
        )

    # --------------------------------------------------------
    # CLOSE DATABASE
    # --------------------------------------------------------

    conn.close()

    elapsed = time.perf_counter() - started

    rate = (
        total_processed / elapsed
        if elapsed > 0
        else 0
    )

    logger.info(
        "Embedding generation complete. "
        "total=%d | elapsed=%.2fs | rate=%.2f movies/sec",
        total_processed,
        elapsed,
        rate,
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
