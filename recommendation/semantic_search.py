from __future__ import annotations

import os

import psycopg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from pgvector.psycopg import register_vector
from pgvector import Vector


load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_ID = 1
MODEL_VERSION = "1.0.0"
RESULT_LIMIT = 20


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")

    if not url:
        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    return url


def main() -> None:
    database_url = get_database_url()

    print("Loading embedding model...")

    model = SentenceTransformer(MODEL_NAME)

    print("Model loaded.")

    query_text = (
        "A wrongly imprisoned man survives years in prison "
        "and forms a deep friendship while hoping for freedom."
    )

    print("\nQuery:")
    print(query_text)

    query_embedding = model.encode(
        query_text,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )

    # Convert NumPy embedding into pgvector's Vector type.
    query_vector = Vector(
        query_embedding.tolist()
    )

    conn = psycopg.connect(database_url)

    register_vector(conn)

    sql = """
        SELECT
            m.movie_id,
            m.imdb_id,
            m.title,
            m.release_year,
            1 - (me.embedding_vector <=> %s) AS similarity
        FROM cinemind.movie_embeddings AS me
        JOIN cinemind.movies AS m
            ON m.movie_id = me.movie_id
        WHERE me.model_id = %s
          AND me.embedding_version = %s
          AND me.is_active = TRUE
          AND m.deleted_at IS NULL
        ORDER BY me.embedding_vector <=> %s
        LIMIT %s;
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                query_vector,
                MODEL_ID,
                MODEL_VERSION,
                query_vector,
                RESULT_LIMIT,
            ),
        )

        rows = cur.fetchall()

    conn.close()

    print("\nSemantic Search Results")
    print("=" * 80)

    if not rows:
        print("No results found.")
        return

    for rank, row in enumerate(rows, start=1):
        movie_id, imdb_id, title, year, similarity = row

        print(
            f"{rank:2}. "
            f"{title} "
            f"({year}) "
            f"| similarity={similarity:.4f}"
        )


if __name__ == "__main__":
    main()