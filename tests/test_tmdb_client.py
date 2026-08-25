"""Unit tests for etl.tmdb_client. All HTTP calls are mocked — these
tests never hit the real TMDB API.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest
import requests

from etl.tmdb_client import (
    TMDBAuthError,
    TMDBClient,
    TMDBConnectionError,
    TMDBNotFoundError,
    TMDBRateLimitError,
    TMDBResponseError,
    TMDBTimeoutError,
)


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(
        self,
        status_code: int = 200,
        json_body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        raise_on_json: bool = False,
    ) -> None:
        self.status_code = status_code
        self._json_body = json_body or {}
        self.headers = headers or {}
        self._raise_on_json = raise_on_json
        self.ok = 200 <= status_code < 400

    def json(self) -> Dict[str, Any]:
        if self._raise_on_json:
            raise ValueError("not JSON")
        return self._json_body


def make_client(get_side_effect, **kwargs) -> TMDBClient:
    session = MagicMock(spec=requests.Session)
    session.get = MagicMock(side_effect=get_side_effect)

    client = TMDBClient(
        api_key="test-key",
        session=session,
        use_cache=False,
        min_request_interval=0.0,
        backoff_seconds=0.0,
        max_retries=2,
        **kwargs,
    )

    return client


# ----------------------------------------------------------------------
# find_by_imdb_id
# ----------------------------------------------------------------------


def test_find_by_imdb_id_movie_match():
    client = make_client([FakeResponse(200, {"movie_results": [{"id": 278}], "tv_results": []})])

    result = client.find_by_imdb_id("tt0111161")

    assert result.found is True
    assert result.tmdb_id == 278
    assert result.media_type == "movie"


def test_find_by_imdb_id_tv_match():
    client = make_client([FakeResponse(200, {"movie_results": [], "tv_results": [{"id": 1399}]})])

    result = client.find_by_imdb_id("tt0944947")

    assert result.found is True
    assert result.tmdb_id == 1399
    assert result.media_type == "tv"


def test_find_by_imdb_id_no_match():
    client = make_client([FakeResponse(200, {"movie_results": [], "tv_results": []})])

    result = client.find_by_imdb_id("tt9999999")

    assert result.found is False
    assert result.tmdb_id is None


# ----------------------------------------------------------------------
# error handling
# ----------------------------------------------------------------------


def test_not_found_raises():
    client = make_client([FakeResponse(404)])

    with pytest.raises(TMDBNotFoundError):
        client.get_movie_details(999999999)


def test_auth_error_raises():
    client = make_client([FakeResponse(401)])

    with pytest.raises(TMDBAuthError):
        client.get_movie_details(278)


def test_missing_api_key_raises_auth_error():
    client = TMDBClient(api_key="", use_cache=False)

    with pytest.raises(TMDBAuthError):
        client.get_movie_details(278)


def test_malformed_json_raises_response_error():
    client = make_client([FakeResponse(200, raise_on_json=True)])

    with pytest.raises(TMDBResponseError):
        client.get_movie_details(278)


def test_non_dict_json_raises_response_error():
    session = MagicMock(spec=requests.Session)
    response = FakeResponse(200)
    response.json = lambda: ["not", "a", "dict"]
    session.get = MagicMock(return_value=response)

    client = TMDBClient(
        api_key="k", session=session, use_cache=False, min_request_interval=0.0
    )

    with pytest.raises(TMDBResponseError):
        client.get_movie_details(278)


# ----------------------------------------------------------------------
# timeouts / connection errors / retries
# ----------------------------------------------------------------------


def test_timeout_retries_then_raises():
    client = make_client([requests.Timeout(), requests.Timeout(), requests.Timeout()])

    with pytest.raises(TMDBTimeoutError):
        client.get_movie_details(278)

    assert client.session.get.call_count == 3  # initial + 2 retries
    assert client.stats["retries"] == 2


def test_timeout_then_success_recovers():
    client = make_client([requests.Timeout(), FakeResponse(200, {"id": 278, "title": "Fight Club"})])

    result = client.get_movie_details(278)

    assert result["id"] == 278
    assert client.session.get.call_count == 2


def test_connection_error_retries_then_raises():
    client = make_client([requests.ConnectionError(), requests.ConnectionError(), requests.ConnectionError()])

    with pytest.raises(TMDBConnectionError):
        client.get_movie_details(278)


def test_server_error_retries_then_raises():
    client = make_client([FakeResponse(500), FakeResponse(502), FakeResponse(503)])

    with pytest.raises(TMDBResponseError):
        client.get_movie_details(278)

    assert client.session.get.call_count == 3


# ----------------------------------------------------------------------
# rate limiting
# ----------------------------------------------------------------------


def test_rate_limit_honors_retry_after_then_succeeds():
    client = make_client(
        [
            FakeResponse(429, headers={"Retry-After": "0"}),
            FakeResponse(200, {"id": 278}),
        ]
    )

    result = client.get_movie_details(278)

    assert result["id"] == 278


def test_rate_limit_exhausted_raises():
    client = make_client([FakeResponse(429), FakeResponse(429), FakeResponse(429)])

    with pytest.raises(TMDBRateLimitError):
        client.get_movie_details(278)


# ----------------------------------------------------------------------
# caching
# ----------------------------------------------------------------------


def test_cache_avoids_duplicate_requests(tmp_path):
    session = MagicMock(spec=requests.Session)
    session.get = MagicMock(return_value=FakeResponse(200, {"id": 278}))

    client = TMDBClient(
        api_key="k",
        session=session,
        use_cache=True,
        cache_dir=tmp_path,
        min_request_interval=0.0,
    )

    first = client.get_movie_details(278)
    second = client.get_movie_details(278)

    assert first == second == {"id": 278}
    assert session.get.call_count == 1
    assert client.stats["cache_hits"] == 1


def test_cache_disabled_per_call(tmp_path):
    session = MagicMock(spec=requests.Session)
    session.get = MagicMock(return_value=FakeResponse(200, {"id": 278}))

    client = TMDBClient(
        api_key="k",
        session=session,
        use_cache=True,
        cache_dir=tmp_path,
        min_request_interval=0.0,
    )

    client.get_movie_details(278)
    client._get("/movie/278", {}, use_cache=False)

    assert session.get.call_count == 2


# ----------------------------------------------------------------------
# append_to_response bundling
# ----------------------------------------------------------------------


def test_get_movie_full_uses_append_to_response():
    session = MagicMock(spec=requests.Session)
    session.get = MagicMock(return_value=FakeResponse(200, {"id": 278}))

    client = TMDBClient(api_key="k", session=session, use_cache=False, min_request_interval=0.0)

    client.get_movie_full(278)

    _, kwargs = session.get.call_args
    assert "credits" in kwargs["params"]["append_to_response"]
    assert "videos" in kwargs["params"]["append_to_response"]


def test_get_tv_full_uses_append_to_response():
    session = MagicMock(spec=requests.Session)
    session.get = MagicMock(return_value=FakeResponse(200, {"id": 1399}))

    client = TMDBClient(api_key="k", session=session, use_cache=False, min_request_interval=0.0)

    client.get_tv_full(1399)

    _, kwargs = session.get.call_args
    assert "credits" in kwargs["params"]["append_to_response"]


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def test_poster_url_none_when_no_path():
    assert TMDBClient.poster_url(None) is None


def test_poster_url_builds_full_url():
    assert TMDBClient.poster_url("/abc.jpg").endswith("/abc.jpg")
