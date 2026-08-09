"""SQLAlchemy-based batch loader for transformed IMDb records.

Design notes
------------
- Batch/streaming only: callers pass chunks of already-transformed
  records (see transform.py); nothing here does row-by-row inserts.
- Foreign keys (movie_id, person_id, genre_id, language_id) are natural
  keys (imdb_id, imdb_person_id, genre_name, iso_639_1) in the transformed
  records. Genre/language lookup tables are tiny and cached in memory for
  the lifetime of the loader. Movie/person id lookups are NOT cached
  in-memory (IMDb has ~11M titles and ~13M people; a full cache would
  violate the project's memory ceiling) — instead each chunk resolves
  only the ids it needs via a single indexed `WHERE x = ANY(:ids)` query.
- Every table load happens inside one transaction per chunk. Any
  failure rolls the whole chunk back; nothing partially commits.
- Each chunk transaction is retried a bounded number of times with
  backoff before being counted as failed. All statements here (INSERT
  ... ON CONFLICT, and SELECT lookups) are naturally idempotent/pure,
  so re-running an attempt from scratch after a transient connection
  failure is always safe.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeAlias

from sqlalchemy import Boolean, Column, Integer, MetaData, Numeric, Table, Text, event, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from etl.config import settings
from etl.logger import get_logger

logger = get_logger(__name__)

Record: TypeAlias = Dict[str, Any]
RecordBatch: TypeAlias = List[Record]

# (inserted, updated, skipped) returned by every per-batch operation.
BatchCounts: TypeAlias = Tuple[int, int, int]

# Minimal Core table definitions (columns actually written by this loader)
# for the tables that need INSERT ... ON CONFLICT ... RETURNING against a
# multi-row batch. Raw text() SQL with a list of parameter dicts is
# executed by psycopg as cursor.executemany(), which does not return
# rows for RETURNING; SQLAlchemy's Core insert() construct instead
# compiles the whole batch into a single multi-row INSERT statement
# (one cursor.execute()), which RETURNING works with correctly.
_METADATA = MetaData(schema=None)  # search_path handles schema resolution

MOVIES_TABLE = Table(
    "movies",
    _METADATA,
    Column("imdb_id", Text),
    Column("title", Text),
    Column("original_title", Text),
    Column("title_type", Text),
    Column("release_year", Integer),
    Column("end_year", Integer),
    Column("runtime_minutes", Integer),
    Column("original_language", Text),
    Column("is_adult", Boolean),
)

PEOPLE_TABLE = Table(
    "people",
    _METADATA,
    Column("imdb_person_id", Text),
    Column("full_name", Text),
    Column("birth_year", Integer),
    Column("death_year", Integer),
    Column("primary_profession", Text),
    Column("known_for_titles", Text),
)

MOVIE_RATINGS_TABLE = Table(
    "movie_ratings",
    _METADATA,
    Column("movie_id", Integer),
    Column("imdb_rating", Numeric),
    Column("imdb_vote_count", Integer),
)

MOVIE_PEOPLE_TABLE = Table(
    "movie_people",
    _METADATA,
    Column("movie_id", Integer),
    Column("person_id", Integer),
    Column("role", Text),
    Column("job_title", Text),
    Column("character_name", Text),
    Column("billing_order", Integer),
)


def build_database_url() -> str:
    return (
        "postgresql+psycopg://"
        f"{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}"
        f"/{settings.postgres_database}"
    )


def build_engine(*, echo: bool = False) -> Engine:
    from sqlalchemy import create_engine

    engine = create_engine(
        build_database_url(),
        pool_pre_ping=True,
        pool_size=max(settings.max_workers, 1),
        pool_recycle=1800,
        future=True,
        echo=echo,
    )

    schema = settings.postgres_schema

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET search_path TO {schema}, public")
        cursor.close()
        # Without this commit, the SET runs inside psycopg's default
        # (non-autocommit) transaction and is silently undone the first
        # time SQLAlchemy issues a ROLLBACK on this connection (which it
        # does by default whenever a connection is returned to the pool),
        # reverting search_path back to the default on every reuse.
        dbapi_connection.commit()

    return engine


@dataclass(slots=True)
class LoadStatistics:
    """Aggregate load counters, per destination table."""

    table_name: str
    rows_received: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    rows_failed: int = 0
    batches_committed: int = 0
    batches_rolled_back: int = 0
    retries_attempted: int = 0

    def record_result(self, inserted: int, updated: int, skipped: int) -> None:
        self.rows_inserted += inserted
        self.rows_updated += updated
        self.rows_skipped += skipped

    def summary(self) -> Dict[str, Any]:
        return {
            "table": self.table_name,
            "rows_received": self.rows_received,
            "rows_inserted": self.rows_inserted,
            "rows_updated": self.rows_updated,
            "rows_skipped": self.rows_skipped,
            "rows_failed": self.rows_failed,
            "batches_committed": self.batches_committed,
            "batches_rolled_back": self.batches_rolled_back,
            "retries_attempted": self.retries_attempted,
        }


class DatabaseLoader:
    """Loads transformed IMDb records into PostgreSQL in batches.

    Usage:
        loader = DatabaseLoader()
        loader.load_chunk({"movies": [...], "movie_genres": [...]})
        ...
        loader.close()
    """

    def __init__(
        self,
        engine: Optional[Engine] = None,
        batch_size: Optional[int] = None,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self.engine = engine or build_engine()
        self.batch_size = batch_size or settings.batch_size
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.session_factory = sessionmaker(bind=self.engine, future=True)

        self._genre_cache: Dict[str, int] = {}
        self._language_cache: Dict[str, int] = {}

        self.statistics: Dict[str, LoadStatistics] = {}

        logger.info(
            "DatabaseLoader initialized (batch_size=%s, host=%s, database=%s)",
            self.batch_size,
            settings.postgres_host,
            settings.postgres_database,
        )

    # ------------------------------------------------------------------
    # Infrastructure
    # ------------------------------------------------------------------

    def _stats(self, table_name: str) -> LoadStatistics:
        if table_name not in self.statistics:
            self.statistics[table_name] = LoadStatistics(table_name=table_name)
        return self.statistics[table_name]

    def _run_batch(
        self,
        table_name: str,
        batch: RecordBatch,
        operation: Callable[[Session, RecordBatch], BatchCounts],
    ) -> None:
        """Runs one batch inside a transaction, with bounded retries.

        `operation` receives a live session and the batch, performs the
        insert(s), and returns (inserted, updated, skipped). On any
        SQLAlchemyError the transaction is rolled back and, if attempts
        remain, retried after a short backoff — every operation here is
        idempotent (ON CONFLICT upserts / pure SELECT lookups), so
        re-running a failed attempt from scratch is always safe.
        """

        stats = self._stats(table_name)
        attempt = 0

        while True:
            session = self.session_factory()

            try:
                inserted, updated, skipped = operation(session, batch)
                session.commit()
                stats.batches_committed += 1
                stats.record_result(inserted=inserted, updated=updated, skipped=skipped)
                return

            except SQLAlchemyError:
                session.rollback()
                stats.batches_rolled_back += 1
                attempt += 1

                if attempt <= self.max_retries:
                    stats.retries_attempted += 1
                    delay = self.retry_backoff_seconds * (2 ** (attempt - 1))

                    logger.warning(
                        "Batch load for '%s' failed (attempt %d/%d); "
                        "retrying in %.1fs.",
                        table_name,
                        attempt,
                        self.max_retries,
                        delay,
                    )

                    time.sleep(delay)
                    continue

                stats.rows_failed += len(batch)

                logger.exception(
                    "Batch load for '%s' failed after %d attempts; "
                    "giving up on this batch (%d rows).",
                    table_name,
                    attempt,
                    len(batch),
                )
                return

            finally:
                session.close()

    @staticmethod
    def _chunked(records: RecordBatch, size: int) -> List[RecordBatch]:
        return [records[start : start + size] for start in range(0, len(records), size)]

    # ------------------------------------------------------------------
    # Lookup tables (genres, languages) — small, cached in memory
    # ------------------------------------------------------------------

    def _resolve_genre_ids(self, session: Session, genre_names: List[str]) -> Dict[str, int]:
        missing = [name for name in genre_names if name not in self._genre_cache]

        if missing:
            rows = session.execute(
                text("SELECT genre_id, genre_name FROM genres WHERE genre_name = ANY(:names)"),
                {"names": missing},
            ).all()

            for genre_id, genre_name in rows:
                self._genre_cache[genre_name] = genre_id

            still_missing = [name for name in missing if name not in self._genre_cache]

            for name in still_missing:
                result = session.execute(
                    text(
                        "INSERT INTO genres (genre_name) VALUES (:name) "
                        "ON CONFLICT (genre_name) DO UPDATE SET genre_name = EXCLUDED.genre_name "
                        "RETURNING genre_id"
                    ),
                    {"name": name},
                )
                genre_id = result.scalar_one()
                self._genre_cache[name] = genre_id

        return {name: self._genre_cache[name] for name in genre_names if name in self._genre_cache}

    def _resolve_language_ids(self, session: Session, iso_codes: List[str]) -> Dict[str, int]:
        missing = [code for code in iso_codes if code not in self._language_cache]

        if missing:
            rows = session.execute(
                text("SELECT language_id, iso_639_1 FROM languages WHERE iso_639_1 = ANY(:codes)"),
                {"codes": missing},
            ).all()

            for language_id, iso_code in rows:
                self._language_cache[iso_code] = language_id

        return {code: self._language_cache[code] for code in iso_codes if code in self._language_cache}

    # ------------------------------------------------------------------
    # Movie id / person id lookups — resolved per-chunk, never fully cached
    # ------------------------------------------------------------------

    @staticmethod
    def _lookup_movie_ids(session: Session, imdb_ids: List[str]) -> Dict[str, int]:
        if not imdb_ids:
            return {}

        rows = session.execute(
            text("SELECT movie_id, imdb_id FROM movies WHERE imdb_id = ANY(:ids)"),
            {"ids": list(set(imdb_ids))},
        ).all()

        return {imdb_id: movie_id for movie_id, imdb_id in rows}

    @staticmethod
    def _lookup_person_ids(session: Session, imdb_person_ids: List[str]) -> Dict[str, int]:
        if not imdb_person_ids:
            return {}

        rows = session.execute(
            text("SELECT person_id, imdb_person_id FROM people WHERE imdb_person_id = ANY(:ids)"),
            {"ids": list(set(imdb_person_ids))},
        ).all()

        return {imdb_person_id: person_id for person_id, imdb_person_id in rows}

    # ------------------------------------------------------------------
    # movies
    # ------------------------------------------------------------------

    @staticmethod
    def _insert_movies(session: Session, batch: RecordBatch) -> BatchCounts:
        stmt = pg_insert(MOVIES_TABLE).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["imdb_id"],
            set_={
                "title": stmt.excluded.title,
                "original_title": stmt.excluded.original_title,
                "title_type": stmt.excluded.title_type,
                "release_year": stmt.excluded.release_year,
                "end_year": stmt.excluded.end_year,
                "runtime_minutes": stmt.excluded.runtime_minutes,
                "original_language": stmt.excluded.original_language,
                "is_adult": stmt.excluded.is_adult,
            },
        ).returning(text("(xmax = 0) AS inserted"))

        result = session.execute(stmt)
        inserted = sum(1 for row in result if row.inserted)
        return inserted, len(batch) - inserted, 0

    def load_movies(self, records: RecordBatch) -> None:
        stats = self._stats("movies")
        stats.rows_received += len(records)

        for batch in self._chunked(records, self.batch_size):
            self._run_batch("movies", batch, self._insert_movies)

        if records:
            logger.info("movies: %s", stats.summary())

    # ------------------------------------------------------------------
    # movie_ratings
    # ------------------------------------------------------------------

    def _insert_movie_ratings(self, session: Session, batch: RecordBatch) -> BatchCounts:
        imdb_ids = [r["imdb_id"] for r in batch]
        movie_id_map = self._lookup_movie_ids(session, imdb_ids)

        rows = [
            {
                "movie_id": movie_id_map[r["imdb_id"]],
                "imdb_rating": r.get("imdb_rating"),
                "imdb_vote_count": r.get("imdb_vote_count"),
            }
            for r in batch
            if r["imdb_id"] in movie_id_map
        ]

        skipped = len(batch) - len(rows)

        if not rows:
            return 0, 0, skipped

        stmt = pg_insert(MOVIE_RATINGS_TABLE).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["movie_id"],
            set_={
                "imdb_rating": stmt.excluded.imdb_rating,
                "imdb_vote_count": stmt.excluded.imdb_vote_count,
            },
        ).returning(text("(xmax = 0) AS inserted"))

        result = session.execute(stmt)
        inserted = sum(1 for row in result if row.inserted)
        return inserted, len(rows) - inserted, skipped

    def load_movie_ratings(self, records: RecordBatch) -> None:
        stats = self._stats("movie_ratings")
        stats.rows_received += len(records)

        for batch in self._chunked(records, self.batch_size):
            self._run_batch("movie_ratings", batch, self._insert_movie_ratings)

        if records:
            logger.info("movie_ratings: %s", stats.summary())

    # ------------------------------------------------------------------
    # movie_genres
    # ------------------------------------------------------------------

    def _insert_movie_genres(self, session: Session, batch: RecordBatch) -> BatchCounts:
        imdb_ids = [r["imdb_id"] for r in batch]
        genre_names = [r["genre_name"] for r in batch]

        movie_id_map = self._lookup_movie_ids(session, imdb_ids)
        genre_id_map = self._resolve_genre_ids(session, genre_names)

        rows = [
            {
                "movie_id": movie_id_map[r["imdb_id"]],
                "genre_id": genre_id_map[r["genre_name"]],
            }
            for r in batch
            if r["imdb_id"] in movie_id_map and r["genre_name"] in genre_id_map
        ]

        skipped = len(batch) - len(rows)

        if not rows:
            return 0, 0, skipped

        stmt = text(
            """
            INSERT INTO movie_genres (movie_id, genre_id)
            VALUES (:movie_id, :genre_id)
            ON CONFLICT (movie_id, genre_id) DO NOTHING
            """
        )

        session.execute(stmt, rows)
        return len(rows), 0, skipped

    def load_movie_genres(self, records: RecordBatch) -> None:
        stats = self._stats("movie_genres")
        stats.rows_received += len(records)

        for batch in self._chunked(records, self.batch_size):
            self._run_batch("movie_genres", batch, self._insert_movie_genres)

        if records:
            logger.info("movie_genres: %s", stats.summary())

    # ------------------------------------------------------------------
    # movie_languages
    # ------------------------------------------------------------------

    def _insert_movie_languages(self, session: Session, batch: RecordBatch) -> BatchCounts:
        imdb_ids = [r["imdb_id"] for r in batch]
        iso_codes = [r["iso_639_1"] for r in batch]

        movie_id_map = self._lookup_movie_ids(session, imdb_ids)
        language_id_map = self._resolve_language_ids(session, iso_codes)

        rows = [
            {
                "movie_id": movie_id_map[r["imdb_id"]],
                "language_id": language_id_map[r["iso_639_1"]],
                "is_original": r.get("is_original", True),
            }
            for r in batch
            if r["imdb_id"] in movie_id_map and r["iso_639_1"] in language_id_map
        ]

        skipped = len(batch) - len(rows)

        if not rows:
            return 0, 0, skipped

        stmt = text(
            """
            INSERT INTO movie_languages (movie_id, language_id, is_original)
            VALUES (:movie_id, :language_id, :is_original)
            ON CONFLICT (movie_id, language_id) DO NOTHING
            """
        )

        session.execute(stmt, rows)
        return len(rows), 0, skipped

    def load_movie_languages(self, records: RecordBatch) -> None:
        stats = self._stats("movie_languages")
        stats.rows_received += len(records)

        for batch in self._chunked(records, self.batch_size):
            self._run_batch("movie_languages", batch, self._insert_movie_languages)

        if records:
            logger.info("movie_languages: %s", stats.summary())

    # ------------------------------------------------------------------
    # people
    # ------------------------------------------------------------------

    @staticmethod
    def _insert_people(session: Session, batch: RecordBatch) -> BatchCounts:
        stmt = pg_insert(PEOPLE_TABLE).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["imdb_person_id"],
            set_={
                "full_name": stmt.excluded.full_name,
                "birth_year": stmt.excluded.birth_year,
                "death_year": stmt.excluded.death_year,
                "primary_profession": stmt.excluded.primary_profession,
                "known_for_titles": stmt.excluded.known_for_titles,
            },
        ).returning(text("(xmax = 0) AS inserted"))

        result = session.execute(stmt)
        inserted = sum(1 for row in result if row.inserted)
        return inserted, len(batch) - inserted, 0

    def load_people(self, records: RecordBatch) -> None:
        stats = self._stats("people")
        stats.rows_received += len(records)

        for batch in self._chunked(records, self.batch_size):
            self._run_batch("people", batch, self._insert_people)

        if records:
            logger.info("people: %s", stats.summary())

    # ------------------------------------------------------------------
    # movie_people
    # ------------------------------------------------------------------

    def _insert_movie_people(self, session: Session, batch: RecordBatch) -> BatchCounts:
        imdb_ids = [r["imdb_id"] for r in batch]
        imdb_person_ids = [r["imdb_person_id"] for r in batch]

        movie_id_map = self._lookup_movie_ids(session, imdb_ids)
        person_id_map = self._lookup_person_ids(session, imdb_person_ids)

        rows = []
        for r in batch:
            if r["imdb_id"] not in movie_id_map:
                continue
            if r["imdb_person_id"] not in person_id_map:
                continue

            rows.append(
                {
                    "movie_id": movie_id_map[r["imdb_id"]],
                    "person_id": person_id_map[r["imdb_person_id"]],
                    "role": r["role"],
                    "job_title": r.get("job_title"),
                    # uq_movie_person_role treats NULL as distinct, which
                    # would make re-runs insert duplicates for rows with
                    # no character (directors, writers). Coalescing to ''
                    # keeps ON CONFLICT idempotent across re-runs.
                    "character_name": r.get("character_name") or "",
                    "billing_order": r.get("billing_order"),
                }
            )

        skipped = len(batch) - len(rows)

        if not rows:
            return 0, 0, skipped

        stmt = pg_insert(MOVIE_PEOPLE_TABLE).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["movie_id", "person_id", "role", "character_name"],
            set_={
                "job_title": stmt.excluded.job_title,
                "billing_order": stmt.excluded.billing_order,
            },
        ).returning(text("(xmax = 0) AS inserted"))

        result = session.execute(stmt)
        inserted = sum(1 for row in result if row.inserted)
        return inserted, len(rows) - inserted, skipped

    def load_movie_people(self, records: RecordBatch) -> None:
        stats = self._stats("movie_people")
        stats.rows_received += len(records)

        for batch in self._chunked(records, self.batch_size):
            self._run_batch("movie_people", batch, self._insert_movie_people)

        if records:
            logger.info("movie_people: %s", stats.summary())

    # ------------------------------------------------------------------
    # Dispatch: routes a table-keyed dict of records (as produced by
    # transform.IMDbRowTransformer.build_postgresql_records, accumulated
    # over a chunk) to the correct per-table loader, in dependency order.
    # ------------------------------------------------------------------

    _LOAD_ORDER = (
        "movies",
        "people",
        "movie_ratings",
        "movie_genres",
        "movie_languages",
        "movie_people",
    )

    _DISPATCH = {
        "movies": "load_movies",
        "people": "load_people",
        "movie_ratings": "load_movie_ratings",
        "movie_genres": "load_movie_genres",
        "movie_languages": "load_movie_languages",
        "movie_people": "load_movie_people",
    }

    def load_chunk(self, table_records: Dict[str, RecordBatch]) -> None:
        for table_name in self._LOAD_ORDER:
            records = table_records.get(table_name)

            if not records:
                continue

            method = getattr(self, self._DISPATCH[table_name])
            method(records)

    def summary(self) -> Dict[str, Dict[str, Any]]:
        return {name: stats.summary() for name, stats in self.statistics.items()}

    def record_etl_run(
        self,
        *,
        pipeline_name: str,
        source_name: str,
        started_at: Any,
        finished_at: Any,
        status: str,
        records_read: int,
        records_inserted: int,
        records_updated: int,
        records_failed: int,
        execution_time_seconds: float,
        error_message: Optional[str] = None,
    ) -> None:
        session = self.session_factory()

        try:
            session.execute(
                text(
                    """
                    INSERT INTO etl_runs (
                        pipeline_name, source_name, started_at, finished_at,
                        status, records_read, records_inserted, records_updated,
                        records_failed, execution_time_seconds, error_message
                    ) VALUES (
                        :pipeline_name, :source_name, :started_at, :finished_at,
                        :status, :records_read, :records_inserted, :records_updated,
                        :records_failed, :execution_time_seconds, :error_message
                    )
                    """
                ),
                {
                    "pipeline_name": pipeline_name,
                    "source_name": source_name,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "status": status,
                    "records_read": records_read,
                    "records_inserted": records_inserted,
                    "records_updated": records_updated,
                    "records_failed": records_failed,
                    "execution_time_seconds": execution_time_seconds,
                    "error_message": error_message,
                },
            )
            session.commit()

        except SQLAlchemyError:
            session.rollback()
            logger.exception("Failed to record etl_runs entry for '%s'.", source_name)

        finally:
            session.close()

    def close(self) -> None:
        self.engine.dispose()
        logger.info("DatabaseLoader closed. Final summary: %s", self.summary())
