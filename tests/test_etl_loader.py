from __future__ import annotations

from sqlalchemy import text

from etl.load_database import DatabaseLoader, build_engine


TEST_MOVIE = {
    "imdb_id": "tt9999991",
    "title": "CineMind Integration Test Movie",
    "original_title": "CineMind Integration Test Movie",
    "title_type": "movie",
    "release_year": 2026,
    "end_year": None,
    "runtime_minutes": 120,
    "original_language": "en",
    "is_adult": False,
}

TEST_PERSON = {
    "imdb_person_id": "nm9999991",
    "full_name": "CineMind Integration Test Person",
    "birth_year": 1980,
    "death_year": None,
    "primary_profession": "actor",
    "known_for_titles": "tt9999991",
}


def cleanup_test_data() -> None:
    engine = build_engine()

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM movie_people
                WHERE movie_id IN (
                    SELECT movie_id
                    FROM movies
                    WHERE imdb_id = :imdb_id
                )
                """
            ),
            {"imdb_id": TEST_MOVIE["imdb_id"]},
        )

        conn.execute(
            text(
                """
                DELETE FROM movie_ratings
                WHERE movie_id IN (
                    SELECT movie_id
                    FROM movies
                    WHERE imdb_id = :imdb_id
                )
                """
            ),
            {"imdb_id": TEST_MOVIE["imdb_id"]},
        )

        conn.execute(
            text(
                """
                DELETE FROM movie_genres
                WHERE movie_id IN (
                    SELECT movie_id
                    FROM movies
                    WHERE imdb_id = :imdb_id
                )
                """
            ),
            {"imdb_id": TEST_MOVIE["imdb_id"]},
        )

        conn.execute(
            text(
                """
                DELETE FROM movie_languages
                WHERE movie_id IN (
                    SELECT movie_id
                    FROM movies
                    WHERE imdb_id = :imdb_id
                )
                """
            ),
            {"imdb_id": TEST_MOVIE["imdb_id"]},
        )

        conn.execute(
            text(
                """
                DELETE FROM movies
                WHERE imdb_id = :imdb_id
                """
            ),
            {"imdb_id": TEST_MOVIE["imdb_id"]},
        )

        conn.execute(
            text(
                """
                DELETE FROM people
                WHERE imdb_person_id = :imdb_person_id
                """
            ),
            {"imdb_person_id": TEST_PERSON["imdb_person_id"]},
        )

    engine.dispose()


def test_database_connection() -> None:
    engine = build_engine()

    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar_one()
        assert result == 1

        database = conn.execute(
            text("SELECT current_database()")
        ).scalar_one()

        schema = conn.execute(
            text("SELECT current_schema()")
        ).scalar_one()

        search_path = conn.execute(
            text("SHOW search_path")
        ).scalar_one()

    engine.dispose()

    assert database == "cinemind"
    assert schema == "cinemind"
    assert "cinemind" in search_path


def test_required_tables_exist() -> None:
    engine = build_engine()

    required_tables = {
        "movies",
        "people",
        "movie_ratings",
        "movie_genres",
        "movie_languages",
        "movie_people",
        "genres",
        "languages",
        "metadata_sources",
        "etl_runs",
    }

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'cinemind'
                """
            )
        ).scalars().all()

    engine.dispose()

    existing_tables = set(rows)

    missing = required_tables - existing_tables

    assert not missing, f"Missing required tables: {sorted(missing)}"


def test_pgvector_available() -> None:
    engine = build_engine()

    with engine.connect() as conn:
        vector_type = conn.execute(
            text(
                """
                SELECT udt_name
                FROM information_schema.columns
                WHERE table_schema = 'cinemind'
                  AND table_name = 'movie_embeddings'
                  AND column_name = 'embedding_vector'
                """
            )
        ).scalar_one_or_none()

    engine.dispose()

    assert vector_type == "vector"


def test_movies_insert() -> None:
    cleanup_test_data()

    loader = DatabaseLoader()

    loader.load_chunk(
        {
            "movies": [TEST_MOVIE],
        }
    )

    stats = loader.summary()

    loader.close()

    assert stats["movies"]["rows_inserted"] == 1
    assert stats["movies"]["rows_failed"] == 0

    engine = build_engine()

    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    imdb_id,
                    title,
                    title_type::text,
                    release_year
                FROM movies
                WHERE imdb_id = :imdb_id
                """
            ),
            {"imdb_id": TEST_MOVIE["imdb_id"]},
        ).mappings().one()

    engine.dispose()

    assert row["imdb_id"] == TEST_MOVIE["imdb_id"]
    assert row["title"] == TEST_MOVIE["title"]
    assert row["title_type"] == "movie"
    assert row["release_year"] == 2026


def test_movies_upsert_is_idempotent() -> None:
    loader = DatabaseLoader()

    loader.load_chunk(
        {
            "movies": [TEST_MOVIE],
        }
    )

    stats = loader.summary()

    loader.close()

    assert stats["movies"]["rows_inserted"] == 0
    assert stats["movies"]["rows_updated"] == 1

    engine = build_engine()

    with engine.connect() as conn:
        count = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM movies
                WHERE imdb_id = :imdb_id
                """
            ),
            {"imdb_id": TEST_MOVIE["imdb_id"]},
        ).scalar_one()

    engine.dispose()

    assert count == 1


def test_people_insert() -> None:
    cleanup_test_data()

    loader = DatabaseLoader()

    loader.load_chunk(
        {
            "people": [TEST_PERSON],
        }
    )

    stats = loader.summary()

    loader.close()

    assert stats["people"]["rows_inserted"] == 1
    assert stats["people"]["rows_failed"] == 0

    engine = build_engine()

    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    imdb_person_id,
                    full_name,
                    birth_year,
                    primary_profession
                FROM people
                WHERE imdb_person_id = :imdb_person_id
                """
            ),
            {"imdb_person_id": TEST_PERSON["imdb_person_id"]},
        ).mappings().one()

    engine.dispose()

    assert row["imdb_person_id"] == TEST_PERSON["imdb_person_id"]
    assert row["full_name"] == TEST_PERSON["full_name"]
    assert row["birth_year"] == 1980
    assert row["primary_profession"] == "actor"


def test_movie_ratings_insert() -> None:
    cleanup_test_data()

    loader = DatabaseLoader()

    loader.load_chunk({"movies": [TEST_MOVIE]})

    loader.load_chunk(
        {
            "movie_ratings": [
                {
                    "imdb_id": TEST_MOVIE["imdb_id"],
                    "imdb_rating": 8.5,
                    "imdb_vote_count": 10000,
                }
            ]
        }
    )

    stats = loader.summary()

    loader.close()

    assert stats["movie_ratings"]["rows_failed"] == 0

    engine = build_engine()

    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    mr.imdb_rating,
                    mr.imdb_vote_count
                FROM movie_ratings mr
                JOIN movies m
                    ON m.movie_id = mr.movie_id
                WHERE m.imdb_id = :imdb_id
                """
            ),
            {"imdb_id": TEST_MOVIE["imdb_id"]},
        ).mappings().one()

    engine.dispose()

    assert float(row["imdb_rating"]) == 8.5
    assert row["imdb_vote_count"] == 10000


def test_loader_handles_multiple_entities() -> None:
    cleanup_test_data()

    loader = DatabaseLoader()

    loader.load_chunk(
        {
            "movies": [TEST_MOVIE],
            "people": [TEST_PERSON],
        }
    )

    stats = loader.summary()

    loader.close()

    assert stats["movies"]["rows_failed"] == 0
    assert stats["people"]["rows_failed"] == 0


def test_loader_close_is_safe() -> None:
    loader = DatabaseLoader()

    loader.close()

    # Closing a second time should not raise.
    loader.close()


def test_no_duplicate_test_movie() -> None:
    engine = build_engine()

    with engine.connect() as conn:
        count = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM movies
                WHERE imdb_id = :imdb_id
                """
            ),
            {"imdb_id": TEST_MOVIE["imdb_id"]},
        ).scalar_one()

    engine.dispose()

    assert count <= 1