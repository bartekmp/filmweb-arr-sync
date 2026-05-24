from unittest.mock import MagicMock, patch

import pytest

from filmweb_arr_sync.arr.sonarr import SonarrClient


@pytest.fixture
def client():
    return SonarrClient("http://sonarr:8989", "testapikey")


def mock_response(data):
    m = MagicMock()
    m.json.return_value = data
    return m


class TestGetExistingTvdbIds:
    def test_returns_set_of_ids(self, client):
        with patch.object(
            client._session, "get", return_value=mock_response([{"tvdbId": 10}, {"tvdbId": 20}])
        ):
            assert client.get_existing_tvdb_ids() == {10, 20}

    def test_returns_empty_set_for_empty_library(self, client):
        with patch.object(client._session, "get", return_value=mock_response([])):
            assert client.get_existing_tvdb_ids() == set()


class TestEnsureTag:
    def test_returns_existing_tag_id(self, client):
        tags = [{"id": 2, "label": "other"}, {"id": 9, "label": "filmweb"}]
        with patch.object(client._session, "get", return_value=mock_response(tags)):
            assert client.ensure_tag("filmweb") == 9

    def test_creates_tag_when_not_found(self, client):
        with (
            patch.object(client._session, "get", return_value=mock_response([])),
            patch.object(
                client._session, "post", return_value=mock_response({"id": 4, "label": "filmweb"})
            ) as mock_post,
        ):
            assert client.ensure_tag("filmweb") == 4
        assert mock_post.call_args.kwargs["json"] == {"label": "filmweb"}


class TestLookup:
    def test_returns_first_result(self, client):
        results = [{"title": "Show A", "tvdbId": 100}, {"title": "Show B", "tvdbId": 200}]
        with patch.object(client._session, "get", return_value=mock_response(results)) as mock_get:
            result = client.lookup(["Show A", "Show PL"], 2022)
        assert result["tvdbId"] == 100
        assert mock_get.call_count == 1

    def test_tries_second_title_when_first_returns_empty(self, client):
        empty = mock_response([])
        hit = mock_response([{"title": "Found Show", "tvdbId": 77}])
        with patch.object(client._session, "get", side_effect=[empty, hit]):
            result = client.lookup(["Original Title", "Fallback Title"], 2020)
        assert result["tvdbId"] == 77

    def test_returns_none_when_all_titles_fail(self, client):
        with patch.object(client._session, "get", return_value=mock_response([])):
            assert client.lookup(["A", "B"], 2020) is None


class TestAdd:
    def test_sends_correct_payload(self, client):
        series = {"title": "Test Show", "tvdbId": 555, "seasons": []}
        with patch.object(client._session, "post", return_value=MagicMock()) as mock_post:
            client.add(series, "/tv", 1)
        payload = mock_post.call_args.kwargs["json"]
        assert payload["tvdbId"] == 555
        assert payload["rootFolderPath"] == "/tv"
        assert payload["qualityProfileId"] == 1
        assert payload["monitored"] is True
        assert payload["seasonFolder"] is True
        assert payload["addOptions"]["searchForMissingEpisodes"] is True

    def test_includes_language_profile_id_when_provided(self, client):
        series = {"title": "T", "tvdbId": 1, "seasons": []}
        with patch.object(client._session, "post", return_value=MagicMock()) as mock_post:
            client.add(series, "/tv", 1, language_profile_id=3)
        assert mock_post.call_args.kwargs["json"]["languageProfileId"] == 3

    def test_omits_language_profile_id_when_none(self, client):
        series = {"title": "T", "tvdbId": 1, "seasons": []}
        with patch.object(client._session, "post", return_value=MagicMock()) as mock_post:
            client.add(series, "/tv", 1, language_profile_id=None)
        assert "languageProfileId" not in mock_post.call_args.kwargs["json"]

    def test_posts_to_correct_endpoint(self, client):
        series = {"title": "T", "tvdbId": 1, "seasons": []}
        with patch.object(client._session, "post", return_value=MagicMock()) as mock_post:
            client.add(series, "/tv", 1)
        assert mock_post.call_args[0][0].endswith("/api/v3/series")
