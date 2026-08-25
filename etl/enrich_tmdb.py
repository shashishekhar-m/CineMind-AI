"""TMDB enrichment: fills in tmdb_id and TMDB-sourced metadata for
movies already loaded from IMDb.

IMDb remains the canonical source for identity fields (imdb_id,
title, original_title, title_type, release_year, end_year,
runtime_minutes, is_adult) — this module never writes to those.

Usage:
    python -m etl.enrich_tmdb                      # enrich up to --limit stale/never-synced movies
    python -m etl.enrich_tmdb --limit 500
    python -m etl.enrich_tmdb --stale-after-days 14
    python -m etl.enrich_tmdb --imdb-id tt0111161   # enrich one specific title

Design notes
------------
- One TMDB find + details call per movie (details call uses
  append_to_response to bundle credits/images/videos/release_dates/
  external_ids into that single call).
- A single TMDB failure (not found, timeout, rate limit exhausted,
  malformed response) is logged and skipped — it never aborts the
  run. This is the whole point of tmdb_client.py's narrow exception
  types.
- DB writes are batched (DatabaseLoader.enrich_movies), flushed every
  `flush_every` successfully-enriched movies, not one row at a time.
- Resumable by construction: get_movies_needing_tmdb_sync() only
  returns movies with no/stale last_synced_at, and every enriched
  movie's last_synced_at is set to now(). Re-running the command
  after a partial run (or on a cron schedule) naturally continues
  from where it left off — no separate checkpoint file needed.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from etl.load_database import DatabaseLoader
from etl.logger import get_logger
from etl.tmdb_client import (
    TMDBClient,
    TMDBError,
    TMDBNotFoundError,
)

logger = get_logger(__name__)

# TMDB movie.status -> content_status_enum (database/schema.sql).
# TMDB uses "Canceled" (American spelling); the schema uses the
# British "cancelled" — everything else lowercases directly.
TMDB_STATUS_MAP = {
    "Rumored": "rumored",
    "Planned": "planned",
    "In Production": "in_production",
    "Post Production": "post_production",
    "Released": "released",
    "Canceled": "cancelled",
}

DEFAULT_STATUS = "released"


@dataclass(slots=True)
class EnrichmentStatistics:
    attempted: int = 0
    enriched: int = 0
    not_found: int = 0
    skipped_no_tmdb_match: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {
            "attempted": self.attempted,
            "enriched": self.enriched,
            "not_found": self.not_found,
            "skipped_no_tmdb_match": self.skipped_no_tmdb_match,
            "failed": self.failed,
        }


def map_tmdb_status(tmdb_status: Optional[str]) -> str:
    if tmdb_status is None:
        return DEFAULT_STATUS

    return TMDB_STATUS_MAP.get(tmdb_status, DEFAULT_STATUS)


def build_movie_enrichment_record(
    imdb_id: str,
    tmdb_id: int,
    details: Dict[str, Any],
    metadata_source_id: Optional[int],
) -> Dict[str, Any]:
    """Maps a TMDB `/movie/{id}?append_to_response=...` response into
    the record shape DatabaseLoader.enrich_movies expects.
    """

    videos = (details.get("videos") or {}).get("results") or []
    trailer_key = next(
        (
            v.get("key")
            for v in videos
            if v.get("site") == "YouTube" and v.get("type") == "Trailer"
        ),
        None,
    )

    return {
        "imdb_id": imdb_id,
        "tmdb_id": tmdb_id,
        "overview": details.get("overview") or None,
        "tagline": details.get("tagline") or None,
        "status": map_tmdb_status(details.get("status")),
        "poster_url": TMDBClient.poster_url(details.get("poster_path")),
        "backdrop_url": TMDBClient.image_url(details.get("backdrop_path")),
        "trailer_key": trailer_key,
        "homepage_url": details.get("homepage") or None,
        "tmdb_url": f"https://www.themoviedb.org/movie/{tmdb_id}",
        "budget": details.get("budget") or 0,
        "revenue": details.get("revenue") or 0,
        "popularity": details.get("popularity") or 0,
        "vote_average": details.get("vote_average") or None,
        "vote_count": details.get("vote_count") or 0,
        "belongs_to_collection": details.get("belongs_to_collection") is not None,
        "has_video": bool(videos),
        "metadata_source_id": metadata_source_id,
        "last_synced_at": datetime.now(timezone.utc),
    }


def build_tv_enrichment_record(
    imdb_id: str,
    tmdb_id: int,
    details: Dict[str, Any],
    metadata_source_id: Optional[int],
) -> Dict[str, Any]:
    """Maps a TMDB `/tv/{id}?append_to_response=...` response into the
    same enrichment record shape as movies, for the unified `movies`
    catalog table (title_type already distinguishes movie vs. series).
    """

    videos = (details.get("videos") or {}).get("results") or []
    trailer_key = next(
        (
            v.get("key")
            for v in videos
            if v.get("site") == "YouTube" and v.get("type") == "Trailer"
        ),
        None,
    )

    # TV has no numeric "status" content_status_enum equivalent as
    # clean as movies (values like "Returning Series", "Ended",
    # "Canceled"); map what maps and default the rest to released,
    # which matches the vast majority of catalogued (aired) series.
    tv_status_map = {
        "Ended": "released",
        "Canceled": "cancelled",
        "Returning Series": "released",
        "In Production": "in_production",
        "Planned": "planned",
        "Pilot": "planned",
    }

    return {
        "imdb_id": imdb_id,
        "tmdb_id": tmdb_id,
        "overview": details.get("overview") or None,
        "tagline": details.get("tagline") or None,
        "status": tv_status_map.get(details.get("status"), DEFAULT_STATUS),
        "poster_url": TMDBClient.poster_url(details.get("poster_path")),
        "backdrop_url": TMDBClient.image_url(details.get("backdrop_path")),
        "trailer_key": trailer_key,
        "homepage_url": details.get("homepage") or None,
        "tmdb_url": f"https://www.themoviedb.org/tv/{tmdb_id}",
        "budget": 0,
        "revenue": 0,
        "popularity": details.get("popularity") or 0,
        "vote_average": details.get("vote_average") or None,
        "vote_count": details.get("vote_count") or 0,
        "belongs_to_collection": False,
        "has_video": bool(videos),
        "metadata_source_id": metadata_source_id,
        "last_synced_at": datetime.now(timezone.utc),
    }


class TMDBEnricher:
    """Orchestrates: pick movies needing sync -> TMDB find + details ->
    map -> batched DB write. Client and loader are injected so this
    class is fully testable without real network/DB access.
    """

    def __init__(
        self,
        client: Optional[TMDBClient] = None,
        loader: Optional[DatabaseLoader] = None,
        flush_every: int = 50,
    ) -> None:
        self.client = client or TMDBClient()
        self.loader = loader or DatabaseLoader()
        self.flush_every = flush_every
        self.stats = EnrichmentStatistics()

        self._metadata_source_id = self.loader.get_metadata_source_id("TMDb")

        if self._metadata_source_id is None:
            logger.warning(
                "No 'TMDb' row in metadata_sources; enriched movies "
                "will have metadata_source_id=NULL."
            )

    def enrich_one(self, imdb_id: str, known_title_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetches and maps TMDB data for a single IMDb id. Returns the
        enrichment record, or None if TMDB has no match / the call
        failed (already logged; caller should just move on).
        """

        self.stats.attempted += 1

        try:
            found = self.client.find_by_imdb_id(imdb_id)
        except TMDBError as exc:
            logger.warning("TMDB find failed for %s: %s", imdb_id, exc)
            self.stats.failed += 1
            self.stats.errors.append(f"{imdb_id}: find failed ({exc})")
            return None

        if not found.found:
            self.stats.skipped_no_tmdb_match += 1
            logger.info("No TMDB match for %s.", imdb_id)
            return None

        try:
            if found.media_type == "tv":
                details = self.client.get_tv_full(found.tmdb_id)
                record = build_tv_enrichment_record(
                    imdb_id, found.tmdb_id, details, self._metadata_source_id
                )
            else:
                details = self.client.get_movie_full(found.tmdb_id)
                record = build_movie_enrichment_record(
                    imdb_id, found.tmdb_id, details, self._metadata_source_id
                )

        except TMDBNotFoundError:
            # Found via /find but details 404'd (rare, e.g. deleted
            # between the two calls) — treat like no match.
            self.stats.skipped_no_tmdb_match += 1
            logger.info("TMDB details 404 for %s (tmdb_id=%s).", imdb_id, found.tmdb_id)
            return None

        except TMDBError as exc:
            logger.warning("TMDB details fetch failed for %s: %s", imdb_id, exc)
            self.stats.failed += 1
            self.stats.errors.append(f"{imdb_id}: details failed ({exc})")
            return None

        self.stats.enriched += 1
        return record

    def run(
        self,
        limit: int = 100,
        stale_after_days: int = 30,
        imdb_ids: Optional[List[str]] = None,
    ) -> EnrichmentStatistics:
        if imdb_ids:
            targets = [{"imdb_id": i, "title_type": None} for i in imdb_ids]
        else:
            targets = self.loader.get_movies_needing_tmdb_sync(
                limit=limit, stale_after_days=stale_after_days
            )

        logger.info("TMDB enrichment starting for %d movie(s).", len(targets))

        buffer: List[Dict[str, Any]] = []

        for target in targets:
            record = self.enrich_one(target["imdb_id"], target.get("title_type"))

            if record is not None:
                buffer.append(record)

            if len(buffer) >= self.flush_every:
                self.loader.enrich_movies(buffer)
                buffer = []

        if buffer:
            self.loader.enrich_movies(buffer)

        logger.info("TMDB enrichment finished: %s", self.stats.summary())
        return self.stats

    def close(self) -> None:
        self.client.close()
        self.loader.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CineMind AI - TMDB enrichment")

    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--stale-after-days", type=int, default=30)
    parser.add_argument(
        "--imdb-id",
        action="append",
        dest="imdb_ids",
        default=None,
        help="Enrich one specific IMDb id (repeatable).",
    )
    parser.add_argument("--flush-every", type=int, default=50)

    return parser


def main() -> None:
    args = build_arg_parser().parse_args()

    enricher = TMDBEnricher(flush_every=args.flush_every)

    try:
        enricher.run(
            limit=args.limit,
            stale_after_days=args.stale_after_days,
            imdb_ids=args.imdb_ids,
        )
    finally:
        enricher.close()


if __name__ == "__main__":
    main()
