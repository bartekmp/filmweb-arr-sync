import json
import logging
import os

logger = logging.getLogger(__name__)


class State:
    def __init__(self, state_file: str) -> None:
        self._path = state_file
        self._data = self._load()

    @property
    def processed_films(self) -> set[int]:
        return set(self._data.get("processed_films", []))

    @property
    def processed_serials(self) -> set[int]:
        return set(self._data.get("processed_serials", []))

    def mark_film_processed(self, filmweb_id: int) -> None:
        self._append("processed_films", filmweb_id)

    def mark_serial_processed(self, filmweb_id: int) -> None:
        self._append("processed_serials", filmweb_id)

    def _append(self, key: str, filmweb_id: int) -> None:
        ids: list[int] = self._data.setdefault(key, [])
        if filmweb_id not in ids:
            ids.append(filmweb_id)
            self._save()

    def _load(self) -> dict:
        if not os.path.exists(self._path):
            return {}
        try:
            with open(self._path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not read state file %s: %s — starting fresh", self._path, e)
            return {}

    def _save(self) -> None:
        dir_path = os.path.dirname(self._path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2)
