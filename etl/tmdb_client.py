"""Thin, resilient wrapper around the TMDB v3 REST API.

Scope: this module only talks to TMDB and returns plain dicts (raw
API JSON, lightly unwrapped). It does not know about the database or
about transform.py's record shapes — that mapping lives in
enrich_tmdb.py, keeping this module independently testable and reusable.

Design notes
------------
- Synchronous, requests-based (matches the rest of this ETL, which is
  fully synchronous — no reason to introduce asyncio/httpx for this).
- A single `requests.Session` is reused across calls (connection
  pooling); a custom Session can be injected for testing.
- Transient failures (timeouts, connection errors, 5xx, 429) are
  retried with exponential backoff up to `max_retries` times. 429
  responses honor TMDB's `Retry-After` header when present.
- Every call raises a narrow `TMDBError` subclass on failure so
  callers (enrich_tmdb.py) can catch precisely and skip one title
  without crashing the whole enrichment run.
- A minimum-interval throttle keeps steady-state request rate well
  under TMDB's documented limits, independent of retry behavior.
- Responses are cached to disk (JSON, keyed by request signature)
  so a resumed/re-run enrichment job doesn't re-spend API quota on
  titles it already fetched in a previous run. Cache is opt-out per
  call via `use_cache=False`.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from etl.config import settings
from etl.constants import (
    API_TIMEOUT,
    MAX_RETRY_ATTEMPTS,
    RETRY_BACKOFF_SECONDS,
    TMDB_API_BASE_URL,
    TMDB_IMAGE_BASE_URL,
    TMDB_POSTER_BASE_URL,
)
from etl.logger import get_logger

logger = get_logger(__name__)


# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------


class TMDBError(Exception):
    """Base class for all TMDB client errors."""


class TMDBNotFoundError(TMDBError):
    """The requested resource does not exist on TMDB (HTTP 404)."""


class TMDBAuthError(TMDBError):
    """The API key is missing, invalid, or unauthorized (HTTP 401/403)."""


class TMDBRateLimitError(TMDBError):
    """TMDB returned 429 and retries were exhausted."""


class TMDBTimeoutError(TMDBError):
    """The request timed out (connect or read) and retries were exhausted."""


class TMDBConnectionError(TMDBError):
    """A network-level failure occurred and retries were exhausted."""


class TMDBResponseError(TMDBError):
    """TMDB returned a response that could not be parsed as JSON, or a
    non-2xx status not covered by the more specific errors above.
    """


# ----------------------------------------------------------------------
# Result types
# ----------------------------------------------------------------------


@dataclass(slots=True)
class TMDBFindResult:
    """Result of looking up an external ID (e.g. an IMDb id) on TMDB."""

    tmdb_id: Optional[int]
    media_type: Optional[str]  # "movie" or "tv"
    raw: Dict[str, Any]

    @property
    def found(self) -> bool:
        return self.tmdb_id is not None


# ----------------------------------------------------------------------
# Client
# ----------------------------------------------------------------------


class TMDBClient:
    """Synchronous TMDB API client with retries, throttling, and caching.

    Usage:
        client = TMDBClient()
        result = client.find_by_imdb_id("tt0111161")
        if result.found and result.media_type == "movie":
            details = client.get_movie_full(result.tmdb_id)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        session: Optional[requests.Session] = None,
        base_url: str = TMDB_API_BASE_URL,
        timeout: float = API_TIMEOUT,
        max_retries: int = MAX_RETRY_ATTEMPTS,
        backoff_seconds: float = RETRY_BACKOFF_SECONDS,
        min_request_interval: float = 0.05,
        cache_dir: Optional[Path] = None,
        use_cache: bool = True,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.tmdb_api_key

        if not self.api_key:
            logger.warning(
                "TMDBClient initialized without an API key "
                "(TMDB_API_KEY is not set); all requests will fail "
                "with TMDBAuthError."
            )

        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.min_request_interval = min_request_interval

        self.use_cache = use_cache
        self.cache_dir = cache_dir or (settings.tmdb_data_path / "cache")

        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._last_request_at: float = 0.0

        self.stats = {
            "requests_sent": 0,
            "cache_hits": 0,
            "retries": 0,
            "failures": 0,
        }

    # ------------------------------------------------------------------
    # Low-level request handling
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.min_request_interval - elapsed

        if wait > 0:
            time.sleep(wait)

    def _cache_key(self, path: str, params: Dict[str, Any]) -> str:
        signature = json.dumps({"path": path, "params": params}, sort_keys=True)
        return hashlib.sha256(signature.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        if not self.use_cache:
            return None

        path = self._cache_path(key)

        if not path.exists():
            return None

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _cache_set(self, key: str, payload: Dict[str, Any]) -> None:
        if not self.use_cache:
            return

        try:
            self._cache_path(key).write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("Failed to write TMDB cache entry %s", key)

    def _get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        use_cache: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Issues a GET request against the TMDB API, with retries,
        throttling, and caching. Returns the parsed JSON body.

        Raises a TMDBError subclass on any failure that survives
        retries; never returns a partial/garbage result silently.
        """

        if not self.api_key:
            raise TMDBAuthError("TMDB_API_KEY is not configured.")

        params = dict(params or {})
        effective_cache = self.use_cache if use_cache is None else use_cache

        cache_key = self._cache_key(path, params) if effective_cache else None

        if cache_key is not None:
            cached = self._cache_get(cache_key)

            if cached is not None:
                self.stats["cache_hits"] += 1
                return cached

        url = f"{self.base_url}{path}"
        params["api_key"] = self.api_key

        attempt = 0

        while True:
            self._throttle()

            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                self._last_request_at = time.monotonic()
                self.stats["requests_sent"] += 1

            except requests.Timeout as exc:
                attempt = self._handle_retryable(
                    attempt, path, "timeout", exc
                )
                if attempt is None:
                    raise TMDBTimeoutError(f"TMDB request timed out: {path}") from exc
                continue

            except requests.ConnectionError as exc:
                attempt = self._handle_retryable(
                    attempt, path, "connection error", exc
                )
                if attempt is None:
                    raise TMDBConnectionError(
                        f"TMDB connection failed: {path}"
                    ) from exc
                continue

            if response.status_code == 404:
                raise TMDBNotFoundError(f"TMDB resource not found: {path}")

            if response.status_code in (401, 403):
                raise TMDBAuthError(
                    f"TMDB authorization failed (status {response.status_code})."
                )

            if response.status_code == 429:
                retry_after = self._parse_retry_after(response)
                attempt = self._handle_retryable(
                    attempt,
                    path,
                    "rate limited",
                    None,
                    override_delay=retry_after,
                )
                if attempt is None:
                    raise TMDBRateLimitError(f"TMDB rate limit exceeded: {path}")
                continue

            if response.status_code >= 500:
                attempt = self._handle_retryable(
                    attempt, path, f"server error {response.status_code}", None
                )
                if attempt is None:
                    raise TMDBResponseError(
                        f"TMDB server error {response.status_code}: {path}"
                    )
                continue

            if not response.ok:
                raise TMDBResponseError(
                    f"TMDB request failed with status {response.status_code}: {path}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise TMDBResponseError(
                    f"TMDB returned a non-JSON response: {path}"
                ) from exc

            if not isinstance(payload, dict):
                raise TMDBResponseError(
                    f"TMDB returned an unexpected response shape: {path}"
                )

            if cache_key is not None:
                self._cache_set(cache_key, payload)

            return payload

    def _handle_retryable(
        self,
        attempt: int,
        path: str,
        reason: str,
        exc: Optional[Exception],
        override_delay: Optional[float] = None,
    ) -> Optional[int]:
        """Returns the next attempt number if a retry should happen, or
        None if attempts are exhausted (caller should raise).
        """

        if attempt >= self.max_retries:
            self.stats["failures"] += 1
            return None

        delay = override_delay if override_delay is not None else (
            self.backoff_seconds * (2**attempt)
        )

        self.stats["retries"] += 1

        logger.warning(
            "TMDB request to %s failed (%s), attempt %d/%d; retrying in %.1fs.",
            path,
            reason,
            attempt + 1,
            self.max_retries,
            delay,
        )

        time.sleep(delay)
        return attempt + 1

    @staticmethod
    def _parse_retry_after(response: requests.Response) -> float:
        header = response.headers.get("Retry-After")

        if header is None:
            return 1.0

        try:
            return max(float(header), 0.0)
        except ValueError:
            return 1.0

    # ------------------------------------------------------------------
    # Find / lookup
    # ------------------------------------------------------------------

    def find_by_imdb_id(self, imdb_id: str) -> TMDBFindResult:
        """Resolves an IMDb id (e.g. 'tt0111161') to a TMDB id + media
        type. Returns a TMDBFindResult with found=False if TMDB has no
        match (this is a normal, expected outcome — not an error).
        """

        payload = self._get(
            f"/find/{imdb_id}",
            {"external_source": "imdb_id"},
        )

        movie_results = payload.get("movie_results") or []
        tv_results = payload.get("tv_results") or []

        if movie_results:
            return TMDBFindResult(
                tmdb_id=movie_results[0].get("id"),
                media_type="movie",
                raw=movie_results[0],
            )

        if tv_results:
            return TMDBFindResult(
                tmdb_id=tv_results[0].get("id"),
                media_type="tv",
                raw=tv_results[0],
            )

        return TMDBFindResult(tmdb_id=None, media_type=None, raw=payload)

    # ------------------------------------------------------------------
    # Movies
    # ------------------------------------------------------------------

    # append_to_response bundles several related endpoints into one
    # HTTP call, which is the single biggest lever for staying well
    # under TMDB's rate limits during bulk enrichment.
    _MOVIE_APPEND = "credits,images,videos,release_dates,external_ids"
    _TV_APPEND = "credits,images,videos,external_ids"

    def get_movie_details(self, tmdb_id: int, **params: Any) -> Dict[str, Any]:
        return self._get(f"/movie/{tmdb_id}", params)

    def get_movie_credits(self, tmdb_id: int) -> Dict[str, Any]:
        return self._get(f"/movie/{tmdb_id}/credits")

    def get_movie_images(self, tmdb_id: int) -> Dict[str, Any]:
        return self._get(f"/movie/{tmdb_id}/images")

    def get_movie_videos(self, tmdb_id: int) -> Dict[str, Any]:
        return self._get(f"/movie/{tmdb_id}/videos")

    def get_movie_release_dates(self, tmdb_id: int) -> Dict[str, Any]:
        return self._get(f"/movie/{tmdb_id}/release_dates")

    def get_movie_external_ids(self, tmdb_id: int) -> Dict[str, Any]:
        return self._get(f"/movie/{tmdb_id}/external_ids")

    def get_movie_full(self, tmdb_id: int) -> Dict[str, Any]:
        """Movie details plus credits/images/videos/release_dates/
        external_ids in a single request via append_to_response.
        """

        return self.get_movie_details(tmdb_id, append_to_response=self._MOVIE_APPEND)

    # ------------------------------------------------------------------
    # TV
    # ------------------------------------------------------------------

    def get_tv_details(self, tmdb_id: int, **params: Any) -> Dict[str, Any]:
        return self._get(f"/tv/{tmdb_id}", params)

    def get_tv_credits(self, tmdb_id: int) -> Dict[str, Any]:
        return self._get(f"/tv/{tmdb_id}/credits")

    def get_tv_images(self, tmdb_id: int) -> Dict[str, Any]:
        return self._get(f"/tv/{tmdb_id}/images")

    def get_tv_videos(self, tmdb_id: int) -> Dict[str, Any]:
        return self._get(f"/tv/{tmdb_id}/videos")

    def get_tv_external_ids(self, tmdb_id: int) -> Dict[str, Any]:
        return self._get(f"/tv/{tmdb_id}/external_ids")

    def get_tv_full(self, tmdb_id: int) -> Dict[str, Any]:
        return self.get_tv_details(tmdb_id, append_to_response=self._TV_APPEND)

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def get_collection_details(self, collection_id: int) -> Dict[str, Any]:
        return self._get(f"/collection/{collection_id}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def poster_url(poster_path: Optional[str]) -> Optional[str]:
        return f"{TMDB_POSTER_BASE_URL}{poster_path}" if poster_path else None

    @staticmethod
    def image_url(file_path: Optional[str]) -> Optional[str]:
        return f"{TMDB_IMAGE_BASE_URL}{file_path}" if file_path else None

    def close(self) -> None:
        self.session.close()

