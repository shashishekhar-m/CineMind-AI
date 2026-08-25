"""Unit tests for etl.enrich_tmdb. TMDBClient and DatabaseLoader are
both mocked/faked — no real network or database access.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from etl.enrich_tmdb import (
    TMDBEnricher,
    build_movie_enrichment_record,
    build_tv_enrichment_record,
    map_tmdb_status,
)
from etl.tmdb_client import TMDBFindResult, TMDBNotFoundError, TMDBTimeoutError


MOVIE_DETAILS = {
    "id": 278,
    "overview": "Two imprisoned men bond over a number of years.",
    "tagline": "Fear can hold you prisoner.",
    "status": "Released",
    "poster_path": "/poster.jpg",
    "backdrop_path": "/backdrop.jpg",
    "homepage": "https://example.com",
    "budget": 25000000,
    "revenue": 28341469,
    "popularity": 95.5,
    "vote_average": 8.7,
    "vote_count": 26000,
    "belongs_to_collection": None,
    "videos": {
        "results": [
            {"site": "YouTube", "type": "Trailer", "key": "abc123"},
            {"site": "YouTube", "type": "Teaser", "key": "zzz999"},
        ]
    },
}


class FakeLoader:
    """Fakes just the DatabaseLoader surface enrich_tmdb.py uses."""

    def __init__(self, movies_needing_sync: Optional[List[Dict[str, Any]]] = None) -> None:
        self._movies_needing_sync = movies_needing_sync or []
        self.enrich_calls: List[List[Dict[str, Any]]] = []
        self.closed = False

    def get_metadata_source_id(self, source_name: str) -> Optional[int]:
        return 2

    def get_movies_needing_tmdb_sync(self, limit: int, stale_after_days: int) -> List[Dict[str, Any]]:
        return self._movies_needing_sync[:limit]

    def enrich_movies(self, records: List[Dict[str, Any]]) -> None:
        self.enrich_calls.append(list(records))

    def close(self) -> None:
        self.closed = True


# ----------------------------------------------------------------------
# field mapping
# ----------------------------------------------------------------------


def test_map_tmdb_status_known_values():
    assert map_tmdb_status("Released") == "released"
    assert map_tmdb_status("Canceled") == "cancelled"
    assert map_tmdb_status("In Production") == "in_production"


def test_map_tmdb_status_unknown_defaults_to_released():
    assert map_tmdb_status("Some New Status TMDB Adds Later") == "released"


def test_map_tmdb_status_none_defaults_to_released():
    assert map_tmdb_status(None) == "released"


def test_build_movie_enrichment_record_picks_youtube_trailer():
    record = build_movie_enrichment_record("tt0111161", 278, MOVIE_DETAILS, metadata_source_id=2)

    assert record["imdb_id"] == "tt0111161"
    assert record["tmdb_id"] == 278
    assert record["trailer_key"] == "abc123"
    assert record["status"] == "released"
    assert record["poster_url"].endswith("/poster.jpg")
    assert record["has_video"] is True
    assert record["belongs_to_collection"] is False
    assert record["metadata_source_id"] == 2


def test_build_movie_enrichment_record_no_trailer():
    details = dict(MOVIE_DETAILS, videos={"results": [{"site": "Vimeo", "type": "Trailer", "key": "x"}]})

    record = build_movie_enrichment_record("tt1", 1, details, metadata_source_id=2)

    assert record["trailer_key"] is None


def test_build_movie_enrichment_record_missing_optional_fields():
    minimal = {"id": 1}

    record = build_movie_enrichment_record("tt1", 1, minimal, metadata_source_id=None)

    assert record["overview"] is None
    assert record["poster_url"] is None
    assert record["budget"] == 0
    assert record["status"] == "released"
    assert record["metadata_source_id"] is None


def test_build_tv_enrichment_record_maps_tv_status():
    details = dict(MOVIE_DETAILS, status="Canceled")

    record = build_tv_enrichment_record("tt2", 999, details, metadata_source_id=2)

    assert record["status"] == "cancelled"
    assert record["tmdb_url"] == "https://www.themoviedb.org/tv/999"
    assert record["budget"] == 0  # TV has no budget field in TMDB


# ----------------------------------------------------------------------
# enrich_one
# ----------------------------------------------------------------------


def test_enrich_one_movie_success():
    client = MagicMock()
    client.find_by_imdb_id.return_value = TMDBFindResult(tmdb_id=278, media_type="movie", raw={})
    client.get_movie_full.return_value = MOVIE_DETAILS

    enricher = TMDBEnricher(client=client, loader=FakeLoader())

    record = enricher.enrich_one("tt0111161")

    assert record is not None
    assert record["tmdb_id"] == 278
    assert enricher.stats.enriched == 1
    assert enricher.stats.attempted == 1


def test_enrich_one_tv_success():
    client = MagicMock()
    client.find_by_imdb_id.return_value = TMDBFindResult(tmdb_id=1399, media_type="tv", raw={})
    client.get_tv_full.return_value = MOVIE_DETAILS

    enricher = TMDBEnricher(client=client, loader=FakeLoader())

    record = enricher.enrich_one("tt0944947")

    assert record is not None
    client.get_tv_full.assert_called_once_with(1399)
    client.get_movie_full.assert_not_called()


def test_enrich_one_no_tmdb_match():
    client = MagicMock()
    client.find_by_imdb_id.return_value = TMDBFindResult(tmdb_id=None, media_type=None, raw={})

    enricher = TMDBEnricher(client=client, loader=FakeLoader())

    record = enricher.enrich_one("tt9999999")

    assert record is None
    assert enricher.stats.skipped_no_tmdb_match == 1
    assert enricher.stats.failed == 0


def test_enrich_one_find_raises_does_not_crash():
    client = MagicMock()
    client.find_by_imdb_id.side_effect = TMDBTimeoutError("timed out")

    enricher = TMDBEnricher(client=client, loader=FakeLoader())

    record = enricher.enrich_one("tt0111161")

    assert record is None
    assert enricher.stats.failed == 1
    assert enricher.stats.errors  # error captured for later inspection


def test_enrich_one_details_not_found_after_successful_find():
    client = MagicMock()
    client.find_by_imdb_id.return_value = TMDBFindResult(tmdb_id=278, media_type="movie", raw={})
    client.get_movie_full.side_effect = TMDBNotFoundError("gone")

    enricher = TMDBEnricher(client=client, loader=FakeLoader())

    record = enricher.enrich_one("tt0111161")

    assert record is None
    assert enricher.stats.skipped_no_tmdb_match == 1
    assert enricher.stats.failed == 0


def test_malformed_response_handled_gracefully():
    """A response missing expected keys should not raise — only
    genuinely absent/None fields, never a KeyError.
    """

    client = MagicMock()
    client.find_by_imdb_id.return_value = TMDBFindResult(tmdb_id=1, media_type="movie", raw={})
    client.get_movie_full.return_value = {}  # no "id", no "videos", nothing

    enricher = TMDBEnricher(client=client, loader=FakeLoader())

    record = enricher.enrich_one("tt1")

    assert record is not None
    assert record["overview"] is None
    assert record["has_video"] is False


# ----------------------------------------------------------------------
# run() — batching, resumability-by-construction, idempotency
# ----------------------------------------------------------------------


def test_run_batches_db_writes():
    movies = [{"imdb_id": f"tt{i:07d}", "tmdb_id": None, "title_type": "movie"} for i in range(3)]

    client = MagicMock()
    client.find_by_imdb_id.return_value = TMDBFindResult(tmdb_id=1, media_type="movie", raw={})
    client.get_movie_full.return_value = MOVIE_DETAILS

    loader = FakeLoader(movies_needing_sync=movies)
    enricher = TMDBEnricher(client=client, loader=loader, flush_every=2)

    stats = enricher.run(limit=10)

    assert stats.enriched == 3
    # flush_every=2 over 3 records -> one flush of 2, one flush of the remaining 1
    assert len(loader.enrich_calls) == 2
    assert sum(len(c) for c in loader.enrich_calls) == 3


def test_run_skips_titles_with_no_tmdb_match_and_continues():
    movies = [
        {"imdb_id": "tt0000001", "tmdb_id": None, "title_type": "movie"},
        {"imdb_id": "tt0000002", "tmdb_id": None, "title_type": "movie"},
    ]

    client = MagicMock()
    client.find_by_imdb_id.side_effect = [
        TMDBFindResult(tmdb_id=None, media_type=None, raw={}),
        TMDBFindResult(tmdb_id=278, media_type="movie", raw={}),
    ]
    client.get_movie_full.return_value = MOVIE_DETAILS

    loader = FakeLoader(movies_needing_sync=movies)
    enricher = TMDBEnricher(client=client, loader=loader, flush_every=50)

    stats = enricher.run(limit=10)

    assert stats.enriched == 1
    assert stats.skipped_no_tmdb_match == 1
    assert len(loader.enrich_calls[0]) == 1  # only the successful one was written


def test_run_specific_imdb_ids_bypasses_sync_query():
    client = MagicMock()
    client.find_by_imdb_id.return_value = TMDBFindResult(tmdb_id=278, media_type="movie", raw={})
    client.get_movie_full.return_value = MOVIE_DETAILS

    loader = FakeLoader(movies_needing_sync=[{"imdb_id": "tt_should_not_be_used", "title_type": "movie"}])
    enricher = TMDBEnricher(client=client, loader=loader, flush_every=50)

    stats = enricher.run(imdb_ids=["tt0111161"])

    assert stats.attempted == 1
    client.find_by_imdb_id.assert_called_once_with("tt0111161")


def test_enrichment_is_idempotent_across_two_runs():
    """Running enrichment twice with the same TMDB responses should
    produce the same mapped record both times (no accumulating state,
    no double-counting side effects beyond stats).
    """

    client = MagicMock()
    client.find_by_imdb_id.return_value = TMDBFindResult(tmdb_id=278, media_type="movie", raw={})
    client.get_movie_full.return_value = MOVIE_DETAILS

    loader = FakeLoader()
    enricher = TMDBEnricher(client=client, loader=loader)

    first = enricher.enrich_one("tt0111161")
    second = enricher.enrich_one("tt0111161")

    assert first["tmdb_id"] == second["tmdb_id"]
    assert first["overview"] == second["overview"]


def test_close_closes_both_client_and_loader():
    client = MagicMock()
    loader = FakeLoader()

    enricher = TMDBEnricher(client=client, loader=loader)
    enricher.close()

    client.close.assert_called_once()
    assert loader.closed is True
