from unittest.mock import MagicMock, patch

import pytest

from filmweb_arr_sync.arr.radarr import RadarrClient


@pytest.fixture
def client():
    return RadarrClient("http://radarr:7878", "testapikey")


def mock_response(data):
    m = MagicMock()
    m.json.return_value = data
    return m


class TestGetExistingTmdbIds:
    def test_returns_set_of_ids(self, client):
        with patch.object(
            client._session, "get", return_value=mock_response([{"tmdbId": 1}, {"tmdbId": 2}])
        ):
            assert client.get_existing_tmdb_ids() == {1, 2}

    def test_returns_empty_set_for_empty_library(self, client):
        with patch.object(client._session, "get", return_value=mock_response([])):
            assert client.get_existing_tmdb_ids() == set()


class TestEnsureTag:
    def test_returns_existing_tag_id(self, client):
        tags = [{"id": 3, "label": "other"}, {"id": 5, "label": "filmweb"}]
        with patch.object(client._session, "get", return_value=mock_response(tags)):
            assert client.ensure_tag("filmweb") == 5

    def test_creates_tag_when_not_found(self, client):
        with (
            patch.object(client._session, "get", return_value=mock_response([])),
            patch.object(
                client._session, "post", return_value=mock_response({"id": 7, "label": "filmweb"})
            ) as mock_post,
        ):
            assert client.ensure_tag("filmweb") == 7
        assert mock_post.call_args.kwargs["json"] == {"label": "filmweb"}


class TestLookup:
    def test_returns_first_result(self, client):
        results = [{"title": "Movie A", "tmdbId": 100}, {"title": "Movie B", "tmdbId": 200}]
        with patch.object(client._session, "get", return_value=mock_response(results)) as mock_get:
            result = client.lookup(["Movie A", "Movie PL"], 2023)
        assert result["tmdbId"] == 100
        assert mock_get.call_count == 1  # stopped after first hit

    def test_tries_second_title_when_first_returns_empty(self, client):
        empty = mock_response([])
        hit = mock_response([{"title": "Found", "tmdbId": 42}])
        with patch.object(client._session, "get", side_effect=[empty, hit]):
            result = client.lookup(["Japanese Title", "English Title"], 2023)
        assert result["tmdbId"] == 42

    def test_returns_none_when_all_titles_fail(self, client):
        empty = mock_response([])
        with patch.object(client._session, "get", return_value=empty):
            result = client.lookup(["Title A", "Title B"], 2023)
        assert result is None

    def test_search_term_includes_year(self, client):
        with patch.object(client._session, "get", return_value=mock_response([])) as mock_get:
            client.lookup(["My Movie"], 2019)
        params = mock_get.call_args.kwargs["params"]
        assert "2019" in params["term"]
        assert "My Movie" in params["term"]


class TestAdd:
    def test_sends_correct_payload(self, client):
        movie = {"title": "Test Movie", "year": 2023, "tmdbId": 999}
        with patch.object(client._session, "post", return_value=MagicMock()) as mock_post:
            client.add(movie, "/movies", 2)
        payload = mock_post.call_args.kwargs["json"]
        assert payload["tmdbId"] == 999
        assert payload["rootFolderPath"] == "/movies"
        assert payload["qualityProfileId"] == 2
        assert payload["monitored"] is True
        assert payload["addOptions"]["searchForMovie"] is False

    def test_posts_to_correct_endpoint(self, client):
        movie = {"title": "T", "year": 2023, "tmdbId": 1}
        with patch.object(client._session, "post", return_value=MagicMock()) as mock_post:
            client.add(movie, "/movies", 1)
        assert mock_post.call_args[0][0].endswith("/api/v3/movie")
