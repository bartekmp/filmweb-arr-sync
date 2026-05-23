from unittest.mock import MagicMock, patch

from filmweb_arr_sync.config import Config, FilmwebConfig, RadarrConfig, SonarrConfig, SyncConfig
from filmweb_arr_sync.filmweb.models import FilmwebItem
from filmweb_arr_sync.state import State
from filmweb_arr_sync.sync import Syncer


def make_config(dry_run: bool = False, add_delay_seconds: int = 0) -> Config:
    return Config(
        filmweb=FilmwebConfig(username="testuser"),
        radarr=RadarrConfig(url="http://radarr", api_key="key", root_folder="/movies"),
        sonarr=SonarrConfig(url="http://sonarr", api_key="key", root_folder="/tv"),
        sync=SyncConfig(
            dry_run=dry_run, state_file="/dev/null", add_delay_seconds=add_delay_seconds
        ),
    )


def make_item(
    filmweb_id: int = 1,
    title: str = "Polish",
    original_title: str = "English",
    year: int = 2023,
    item_type: str = "film",
) -> FilmwebItem:
    return FilmwebItem(
        filmweb_id=filmweb_id,
        title=title,
        original_title=original_title,
        year=year,
        item_type=item_type,
    )


def make_syncer(config: Config, state: State) -> Syncer:
    syncer = Syncer.__new__(Syncer)
    syncer._config = config
    syncer._state = state
    syncer._dry_run = config.sync.dry_run
    syncer._add_delay = config.sync.add_delay_seconds
    syncer._filmweb = MagicMock()
    syncer._radarr = MagicMock()
    syncer._sonarr = MagicMock()
    return syncer


# --- movies: phase ordering ---


class TestMoviePhaseOrdering:
    def test_all_lookups_happen_before_any_add(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(), state)
        syncer._filmweb.get_movies.return_value = [make_item(filmweb_id=1), make_item(filmweb_id=2)]
        syncer._radarr.get_existing_tmdb_ids.return_value = set()
        syncer._radarr.lookup.side_effect = [
            {"title": "Movie 1", "tmdbId": 101},
            {"title": "Movie 2", "tmdbId": 102},
        ]

        call_order = []
        syncer._radarr.lookup.side_effect = lambda titles, year: (
            call_order.append(("lookup", titles[0]))
            or {"title": titles[0], "tmdbId": hash(titles[0]) % 1000}
        )
        syncer._radarr.add.side_effect = lambda result, *_: call_order.append(
            ("add", result["title"])
        )

        syncer._sync_movies()

        lookup_indices = [i for i, (op, _) in enumerate(call_order) if op == "lookup"]
        add_indices = [i for i, (op, _) in enumerate(call_order) if op == "add"]
        assert max(lookup_indices) < min(add_indices), "All lookups must complete before first add"

    def test_delay_applied_between_adds_not_after_last(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(add_delay_seconds=3), state)
        syncer._filmweb.get_movies.return_value = [
            make_item(filmweb_id=1, original_title="A"),
            make_item(filmweb_id=2, original_title="B"),
            make_item(filmweb_id=3, original_title="C"),
        ]
        syncer._radarr.get_existing_tmdb_ids.return_value = set()
        syncer._radarr.lookup.side_effect = [
            {"title": "A", "tmdbId": 1},
            {"title": "B", "tmdbId": 2},
            {"title": "C", "tmdbId": 3},
        ]

        with patch("filmweb_arr_sync.sync.time.sleep") as mock_sleep:
            syncer._sync_movies()

        assert mock_sleep.call_count == 2  # 3 items → 2 gaps
        mock_sleep.assert_called_with(3)

    def test_no_delay_for_single_add(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(add_delay_seconds=5), state)
        syncer._filmweb.get_movies.return_value = [make_item(filmweb_id=1)]
        syncer._radarr.get_existing_tmdb_ids.return_value = set()
        syncer._radarr.lookup.return_value = {"title": "Movie", "tmdbId": 1}

        with patch("filmweb_arr_sync.sync.time.sleep") as mock_sleep:
            syncer._sync_movies()

        mock_sleep.assert_not_called()


# --- movies: lookup phase ---


class TestLookupMovie:
    def test_skips_already_processed_films(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        state.mark_film_processed(1)
        syncer = make_syncer(make_config(), state)
        syncer._filmweb.get_movies.return_value = [make_item(filmweb_id=1)]
        syncer._radarr.get_existing_tmdb_ids.return_value = set()

        syncer._sync_movies()

        syncer._radarr.lookup.assert_not_called()
        syncer._radarr.add.assert_not_called()

    def test_already_in_radarr_marks_state_during_lookup(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(), state)
        syncer._filmweb.get_movies.return_value = [make_item(filmweb_id=99)]
        syncer._radarr.get_existing_tmdb_ids.return_value = {123}
        syncer._radarr.lookup.return_value = {"title": "Movie", "tmdbId": 123}

        syncer._sync_movies()

        syncer._radarr.add.assert_not_called()
        assert 99 in state.processed_films

    def test_no_match_does_not_mark_state(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(), state)
        syncer._filmweb.get_movies.return_value = [make_item(filmweb_id=99)]
        syncer._radarr.get_existing_tmdb_ids.return_value = set()
        syncer._radarr.lookup.return_value = None

        syncer._sync_movies()

        assert 99 not in state.processed_films

    def test_lookup_error_does_not_mark_state(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(), state)
        syncer._filmweb.get_movies.return_value = [make_item(filmweb_id=99)]
        syncer._radarr.get_existing_tmdb_ids.return_value = set()
        syncer._radarr.lookup.side_effect = Exception("Read timed out")

        syncer._sync_movies()

        syncer._radarr.add.assert_not_called()
        assert 99 not in state.processed_films

    def test_dry_run_marks_state_without_adding(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(dry_run=True), state)
        syncer._filmweb.get_movies.return_value = [make_item(filmweb_id=99)]
        syncer._radarr.get_existing_tmdb_ids.return_value = set()
        syncer._radarr.lookup.return_value = {"title": "Movie", "tmdbId": 123}

        syncer._sync_movies()

        syncer._radarr.add.assert_not_called()
        assert 99 in state.processed_films

    def test_library_fetch_failure_skips_entire_movie_sync(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(), state)
        syncer._filmweb.get_movies.return_value = [make_item(filmweb_id=99)]
        syncer._radarr.get_existing_tmdb_ids.side_effect = Exception("Connection refused")

        syncer._sync_movies()

        syncer._radarr.lookup.assert_not_called()
        assert 99 not in state.processed_films


# --- movies: add phase ---


class TestAddMovie:
    def test_successful_add_marks_state(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(), state)
        syncer._filmweb.get_movies.return_value = [make_item(filmweb_id=99)]
        syncer._radarr.get_existing_tmdb_ids.return_value = set()
        syncer._radarr.lookup.return_value = {"title": "Movie", "tmdbId": 123}

        syncer._sync_movies()

        syncer._radarr.add.assert_called_once()
        assert 99 in state.processed_films

    def test_add_failure_does_not_mark_state(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(), state)
        syncer._filmweb.get_movies.return_value = [make_item(filmweb_id=99)]
        syncer._radarr.get_existing_tmdb_ids.return_value = set()
        syncer._radarr.lookup.return_value = {"title": "Movie", "tmdbId": 123}
        syncer._radarr.add.side_effect = Exception("HTTP 500")

        syncer._sync_movies()

        assert 99 not in state.processed_films

    def test_add_failure_does_not_block_remaining_items(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(), state)
        syncer._filmweb.get_movies.return_value = [
            make_item(filmweb_id=1, original_title="A"),
            make_item(filmweb_id=2, original_title="B"),
        ]
        syncer._radarr.get_existing_tmdb_ids.return_value = set()
        syncer._radarr.lookup.side_effect = [
            {"title": "A", "tmdbId": 1},
            {"title": "B", "tmdbId": 2},
        ]
        syncer._radarr.add.side_effect = [Exception("timeout"), None]

        syncer._sync_movies()

        assert syncer._radarr.add.call_count == 2
        assert 1 not in state.processed_films
        assert 2 in state.processed_films


# --- serials ---


class TestSyncSerials:
    def test_all_lookups_before_adds(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(), state)
        syncer._filmweb.get_serials.return_value = [
            make_item(filmweb_id=1, item_type="serial", original_title="Show A"),
            make_item(filmweb_id=2, item_type="serial", original_title="Show B"),
        ]
        syncer._sonarr.get_existing_tvdb_ids.return_value = set()

        call_order = []
        syncer._sonarr.lookup.side_effect = lambda titles, year: (
            call_order.append(("lookup", titles[0]))
            or {"title": titles[0], "tvdbId": hash(titles[0]) % 1000, "seasons": []}
        )
        syncer._sonarr.add.side_effect = lambda result, *_: call_order.append(
            ("add", result["title"])
        )

        syncer._sync_serials()

        lookup_indices = [i for i, (op, _) in enumerate(call_order) if op == "lookup"]
        add_indices = [i for i, (op, _) in enumerate(call_order) if op == "add"]
        assert max(lookup_indices) < min(add_indices)

    def test_delay_applied_between_serial_adds(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(add_delay_seconds=2), state)
        syncer._filmweb.get_serials.return_value = [
            make_item(filmweb_id=1, item_type="serial", original_title="A"),
            make_item(filmweb_id=2, item_type="serial", original_title="B"),
        ]
        syncer._sonarr.get_existing_tvdb_ids.return_value = set()
        syncer._sonarr.lookup.side_effect = [
            {"title": "A", "tvdbId": 1, "seasons": []},
            {"title": "B", "tvdbId": 2, "seasons": []},
        ]

        with patch("filmweb_arr_sync.sync.time.sleep") as mock_sleep:
            syncer._sync_serials()

        assert mock_sleep.call_count == 1
        mock_sleep.assert_called_with(2)

    def test_skips_already_processed_serials(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        state.mark_serial_processed(5)
        syncer = make_syncer(make_config(), state)
        syncer._filmweb.get_serials.return_value = [make_item(filmweb_id=5, item_type="serial")]
        syncer._sonarr.get_existing_tvdb_ids.return_value = set()

        syncer._sync_serials()

        syncer._sonarr.lookup.assert_not_called()

    def test_add_failure_does_not_mark_state(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(), state)
        syncer._filmweb.get_serials.return_value = [make_item(filmweb_id=77, item_type="serial")]
        syncer._sonarr.get_existing_tvdb_ids.return_value = set()
        syncer._sonarr.lookup.return_value = {"title": "Show", "tvdbId": 999, "seasons": []}
        syncer._sonarr.add.side_effect = Exception("timeout")

        syncer._sync_serials()

        assert 77 not in state.processed_serials


# --- run ---


class TestRun:
    def test_skips_movies_when_radarr_is_none(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(), state)
        syncer._radarr = None

        syncer.run()

        syncer._filmweb.get_movies.assert_not_called()

    def test_skips_serials_when_sonarr_is_none(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(), state)
        syncer._sonarr = None

        syncer.run()

        syncer._filmweb.get_serials.assert_not_called()

    def test_runs_both_when_both_configured(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        syncer = make_syncer(make_config(), state)
        syncer._filmweb.get_movies.return_value = []
        syncer._filmweb.get_serials.return_value = []
        syncer._radarr.get_existing_tmdb_ids.return_value = set()
        syncer._sonarr.get_existing_tvdb_ids.return_value = set()

        syncer.run()

        syncer._filmweb.get_movies.assert_called_once()
        syncer._filmweb.get_serials.assert_called_once()
