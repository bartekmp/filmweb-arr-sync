import json

from filmweb_arr_sync.state import State


class TestState:
    def test_starts_empty_when_no_file_exists(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        assert state.processed_films == set()
        assert state.processed_serials == set()

    def test_mark_film_processed(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        state.mark_film_processed(123)
        assert 123 in state.processed_films

    def test_mark_serial_processed(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        state.mark_serial_processed(456)
        assert 456 in state.processed_serials

    def test_films_and_serials_are_independent(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        state.mark_film_processed(1)
        assert 1 not in state.processed_serials

    def test_no_duplicate_ids_written(self, tmp_path):
        path = tmp_path / "state.json"
        state = State(str(path))
        state.mark_film_processed(1)
        state.mark_film_processed(1)
        data = json.loads(path.read_text())
        assert data["processed_films"].count(1) == 1

    def test_persists_across_instances(self, tmp_path):
        path = str(tmp_path / "state.json")
        State(path).mark_film_processed(99)
        assert 99 in State(path).processed_films

    def test_corrupt_file_starts_fresh_without_raising(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("not valid json {{{{")
        state = State(str(path))
        assert state.processed_films == set()

    def test_creates_parent_directory_if_missing(self, tmp_path):
        path = tmp_path / "subdir" / "state.json"
        state = State(str(path))
        state.mark_film_processed(1)
        assert path.exists()

    def test_multiple_ids_all_stored(self, tmp_path):
        state = State(str(tmp_path / "state.json"))
        for fwid in [10, 20, 30]:
            state.mark_film_processed(fwid)
        assert state.processed_films == {10, 20, 30}
