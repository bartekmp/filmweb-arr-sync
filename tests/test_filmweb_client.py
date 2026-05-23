from unittest.mock import MagicMock, patch

import pytest
import requests

from filmweb_arr_sync.filmweb.client import FilmwebClient


@pytest.fixture
def client():
    return FilmwebClient("testuser")


def _mock_get(*responses):
    """Return a side_effect list of mock responses."""
    mocks = []
    for data in responses:
        m = MagicMock()
        if isinstance(data, Exception):
            m.raise_for_status.side_effect = data
        else:
            m.json.return_value = data
        mocks.append(m)
    return mocks


class TestGetMovies:
    def test_calls_film_watchlist_endpoint(self, client):
        with (
            patch.object(
                client._session, "get", return_value=MagicMock(json=lambda: [])
            ) as mock_get,
            patch("filmweb_arr_sync.filmweb.client.time.sleep"),
        ):
            client.get_movies()
        url = mock_get.call_args[0][0]
        assert "/want2see/film" in url
        assert "testuser" in url

    def test_calls_serial_watchlist_endpoint(self, client):
        with (
            patch.object(
                client._session, "get", return_value=MagicMock(json=lambda: [])
            ) as mock_get,
            patch("filmweb_arr_sync.filmweb.client.time.sleep"),
        ):
            client.get_serials()
        url = mock_get.call_args[0][0]
        assert "/want2see/serial" in url

    def test_returns_parsed_items(self, client):
        watchlist = [{"entity": 123}]
        info = {
            "title": "Polish Title",
            "originalTitle": "English Title",
            "year": 2023,
            "type": "film",
        }
        with (
            patch.object(client._session, "get", side_effect=_mock_get(watchlist, info)),
            patch("filmweb_arr_sync.filmweb.client.time.sleep"),
        ):
            items = client.get_movies()
        assert len(items) == 1
        assert items[0].filmweb_id == 123
        assert items[0].title == "Polish Title"
        assert items[0].original_title == "English Title"
        assert items[0].year == 2023

    def test_delays_between_info_calls(self, client):
        watchlist = [{"entity": 1}, {"entity": 2}]
        info = {"title": "T", "originalTitle": "T", "year": 2020, "type": "film"}
        with (
            patch.object(client._session, "get", side_effect=_mock_get(watchlist, info, info)),
            patch("filmweb_arr_sync.filmweb.client.time.sleep") as mock_sleep,
        ):
            client.get_movies()
        assert mock_sleep.call_count == 2


class TestFetchItemInfo:
    def test_skips_item_with_zero_year(self, client):
        watchlist = [{"entity": 1}]
        info = {"title": "No Year", "originalTitle": "No Year", "year": 0}
        with (
            patch.object(client._session, "get", side_effect=_mock_get(watchlist, info)),
            patch("filmweb_arr_sync.filmweb.client.time.sleep"),
        ):
            items = client.get_movies()
        assert items == []

    def test_skips_item_with_missing_title(self, client):
        watchlist = [{"entity": 1}]
        info = {"year": 2023}  # no title fields
        with (
            patch.object(client._session, "get", side_effect=_mock_get(watchlist, info)),
            patch("filmweb_arr_sync.filmweb.client.time.sleep"),
        ):
            items = client.get_movies()
        assert items == []

    def test_http_error_on_info_skips_and_continues(self, client):
        watchlist = [{"entity": 1}, {"entity": 2}]
        error = requests.HTTPError(response=MagicMock(status_code=404))
        good_info = {"title": "Good", "originalTitle": "Good", "year": 2020, "type": "film"}
        with (
            patch.object(
                client._session, "get", side_effect=_mock_get(watchlist, error, good_info)
            ),
            patch("filmweb_arr_sync.filmweb.client.time.sleep"),
        ):
            items = client.get_movies()
        assert len(items) == 1
        assert items[0].filmweb_id == 2

    def test_falls_back_original_title_to_title(self, client):
        watchlist = [{"entity": 1}]
        info = {"title": "Only Title", "year": 2023}  # no originalTitle key
        with (
            patch.object(client._session, "get", side_effect=_mock_get(watchlist, info)),
            patch("filmweb_arr_sync.filmweb.client.time.sleep"),
        ):
            items = client.get_movies()
        assert items[0].original_title == "Only Title"

    def test_falls_back_title_to_original_title(self, client):
        watchlist = [{"entity": 1}]
        info = {"originalTitle": "Only Original", "year": 2023}  # no title key
        with (
            patch.object(client._session, "get", side_effect=_mock_get(watchlist, info)),
            patch("filmweb_arr_sync.filmweb.client.time.sleep"),
        ):
            items = client.get_movies()
        assert items[0].title == "Only Original"
