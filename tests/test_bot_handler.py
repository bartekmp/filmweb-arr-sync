from unittest.mock import MagicMock

import pytest

from filmweb_arr_sync.bot.handler import BotHandler
from filmweb_arr_sync.config import load_config
from filmweb_arr_sync.filmweb.models import FilmwebItem
from filmweb_arr_sync.state import State


@pytest.fixture
def config(tmp_path):
    return load_config(str(tmp_path / "missing.yaml"))


@pytest.fixture
def state(tmp_path):
    return State(str(tmp_path / "state.json"))


def _radarr():
    client = MagicMock()
    client.get_existing_tmdb_ids.return_value = set()
    client.ensure_tag.return_value = 7
    client.lookup.return_value = {"title": "Inception", "year": 2010, "tmdbId": 27205}
    client.lookup_by_imdb.return_value = {"title": "Inception", "year": 2010, "tmdbId": 27205}
    return client


def _sonarr():
    client = MagicMock()
    client.get_existing_tvdb_ids.return_value = set()
    client.ensure_tag.return_value = 7
    client.lookup.return_value = {"title": "The Witcher", "year": 2019, "tvdbId": 362696}
    client.lookup_by_imdb.return_value = {"title": "The Witcher", "year": 2019, "tvdbId": 362696}
    return client


def _filmweb(item):
    client = MagicMock()
    client.get_item.return_value = item
    return client


def _handler(config, state, radarr=None, sonarr=None, filmweb=None):
    return BotHandler(
        config,
        state,
        radarr,
        sonarr,
        filmweb or MagicMock(),
    )


class TestCommands:
    def test_help(self, config, state):
        handler = _handler(config, state)
        assert "Filmweb" in handler.handle_message("/help")

    def test_start_shows_help(self, config, state):
        handler = _handler(config, state)
        assert "/last_sync" in handler.handle_message("/start")

    def test_last_sync_never_ran(self, config, state, monkeypatch):
        monkeypatch.setattr("filmweb_arr_sync.bot.handler.health.get_last_sync", lambda: None)
        handler = _handler(config, state)
        assert "No scheduled sync" in handler.handle_message("/last_sync")

    def test_last_sync_with_timestamp(self, config, state, monkeypatch):
        monkeypatch.setattr(
            "filmweb_arr_sync.bot.handler.health.get_last_sync", lambda: "2026-06-26T10:00:00"
        )
        handler = _handler(config, state)
        assert "2026-06-26T10:00:00" in handler.handle_message("/last_sync")

    def test_command_with_botname_suffix(self, config, state, monkeypatch):
        monkeypatch.setattr("filmweb_arr_sync.bot.handler.health.get_last_sync", lambda: None)
        handler = _handler(config, state)
        assert "No scheduled sync" in handler.handle_message("/last_sync@mybot")

    def test_stats_counts_processed(self, config, state):
        state.mark_film_processed(1)
        state.mark_serial_processed(2)
        handler = _handler(config, state)
        reply = handler.handle_message("/stats")
        assert "Movies processed: 1" in reply
        assert "Series processed: 1" in reply

    def test_unknown_command(self, config, state):
        handler = _handler(config, state)
        assert "Unknown command" in handler.handle_message("/frobnicate")


class TestShowConfig:
    def test_lists_configured_values(self, config, state):
        config.filmweb.username = "bartekmp"
        config.radarr.url = "http://radarr:7878"
        config.radarr.root_folder = "/movies"
        config.sync.interval_minutes = 45
        config.telegram.allowed_user_ids = [111, 222]
        reply = _handler(config, state).handle_message("/showconfig")
        assert "bartekmp" in reply
        assert "http://radarr:7878" in reply
        assert "/movies" in reply
        assert "every 45 min" in reply
        assert "111, 222" in reply

    def test_redacts_credentials(self, config, state):
        config.radarr.url = "http://radarr:7878"
        config.radarr.api_key = "radarr-secret-key"
        config.sonarr.url = "http://sonarr:8989"
        config.sonarr.api_key = "sonarr-secret-key"
        config.telegram.bot_token = "123456:bot-secret-token"
        reply = _handler(config, state).handle_message("/showconfig")
        assert "radarr-secret-key" not in reply
        assert "sonarr-secret-key" not in reply
        assert "bot-secret-token" not in reply
        assert "API key: set" in reply
        assert "Bot token: set" in reply

    def test_marks_unset_credentials(self, config, state):
        config.radarr.url = "http://radarr:7878"
        reply = _handler(config, state).handle_message("/showconfig")
        assert "API key: (not set)" in reply

    def test_shows_disabled_services(self, config, state):
        reply = _handler(config, state).handle_message("/showconfig")
        assert "Radarr\n• Disabled" in reply
        assert "Sonarr\n• Disabled" in reply

    def test_shows_cron_schedule_when_set(self, config, state):
        config.sync.cron = "0 * * * *"
        reply = _handler(config, state).handle_message("/showconfig")
        assert "0 * * * * (cron)" in reply

    def test_shows_batch_queue_settings(self, config, state):
        config.sync.batch_queue_enabled = True
        config.sync.batch_size = 5
        config.sync.batch_interval_minutes = 10
        reply = _handler(config, state).handle_message("/showconfig")
        assert "5 items / 10 min" in reply

    def test_config_alias(self, config, state):
        assert "Configuration" in _handler(config, state).handle_message("/config")


class TestRejectsInvalid:
    def test_empty_message(self, config, state):
        handler = _handler(config, state)
        assert "/help" in handler.handle_message("   ")

    def test_non_link_text(self, config, state):
        handler = _handler(config, state)
        assert "not a valid" in handler.handle_message("add the matrix please")


class TestFilmwebLinks:
    def test_adds_movie(self, config, state):
        item = FilmwebItem(468741, "Incepcja", "Inception", 2010, "film")
        radarr = _radarr()
        handler = _handler(config, state, radarr=radarr, filmweb=_filmweb(item))
        reply = handler.handle_message("https://www.filmweb.pl/film/Incepcja-2010-468741")
        assert "Added to Radarr: Inception (2010)" in reply
        radarr.add.assert_called_once()
        assert 468741 in state.processed_films

    def test_movie_already_in_radarr(self, config, state):
        item = FilmwebItem(468741, "Incepcja", "Inception", 2010, "film")
        radarr = _radarr()
        radarr.get_existing_tmdb_ids.return_value = {27205}
        handler = _handler(config, state, radarr=radarr, filmweb=_filmweb(item))
        reply = handler.handle_message("https://www.filmweb.pl/film/Incepcja-2010-468741")
        assert "Already in Radarr" in reply
        radarr.add.assert_not_called()
        assert 468741 in state.processed_films

    def test_adds_serial(self, config, state):
        item = FilmwebItem(668941, "Wiedzmin", "The Witcher", 2019, "serial")
        sonarr = _sonarr()
        handler = _handler(config, state, sonarr=sonarr, filmweb=_filmweb(item))
        reply = handler.handle_message("https://www.filmweb.pl/serial/Wiedzmin-2019-668941")
        assert "Added to Sonarr: The Witcher (2019)" in reply
        sonarr.add.assert_called_once()
        assert 668941 in state.processed_serials

    def test_movie_link_but_radarr_disabled(self, config, state):
        item = FilmwebItem(468741, "Incepcja", "Inception", 2010, "film")
        handler = _handler(config, state, radarr=None, filmweb=_filmweb(item))
        assert "Radarr isn't enabled" in handler.handle_message(
            "https://www.filmweb.pl/film/Incepcja-2010-468741"
        )

    def test_no_radarr_match(self, config, state):
        item = FilmwebItem(468741, "Obscure", "Obscure", 2010, "film")
        radarr = _radarr()
        radarr.lookup.return_value = None
        handler = _handler(config, state, radarr=radarr, filmweb=_filmweb(item))
        assert "No Radarr match" in handler.handle_message(
            "https://www.filmweb.pl/film/Obscure-2010-468741"
        )

    def test_filmweb_fetch_fails(self, config, state):
        handler = _handler(config, state, radarr=_radarr(), filmweb=_filmweb(None))
        assert "Couldn't fetch" in handler.handle_message(
            "https://www.filmweb.pl/film/Incepcja-2010-468741"
        )


class TestImdbLinks:
    def test_adds_movie(self, config, state):
        radarr = _radarr()
        handler = _handler(config, state, radarr=radarr, sonarr=_sonarr())
        reply = handler.handle_message("https://www.imdb.com/title/tt1375666/")
        assert "Added to Radarr: Inception (2010)" in reply
        radarr.add.assert_called_once()

    def test_falls_back_to_series_when_no_movie(self, config, state):
        radarr = _radarr()
        radarr.lookup_by_imdb.return_value = None
        sonarr = _sonarr()
        handler = _handler(config, state, radarr=radarr, sonarr=sonarr)
        reply = handler.handle_message("https://www.imdb.com/title/tt0903747/")
        assert "Added to Sonarr: The Witcher (2019)" in reply
        sonarr.add.assert_called_once()

    def test_no_match_anywhere(self, config, state):
        radarr = _radarr()
        radarr.lookup_by_imdb.return_value = None
        sonarr = _sonarr()
        sonarr.lookup_by_imdb.return_value = None
        handler = _handler(config, state, radarr=radarr, sonarr=sonarr)
        assert "No movie or series match" in handler.handle_message(
            "https://www.imdb.com/title/tt9999999/"
        )

    def test_neither_service_configured(self, config, state):
        handler = _handler(config, state)
        assert "Neither Radarr nor Sonarr" in handler.handle_message(
            "https://www.imdb.com/title/tt1375666/"
        )
