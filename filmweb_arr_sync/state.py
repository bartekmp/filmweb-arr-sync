import json
import logging
import os
import threading

logger = logging.getLogger(__name__)


class State:
    def __init__(self, state_file: str) -> None:
        self._path = state_file
        self._lock = threading.Lock()
        self._data = self._load()

    @property
    def processed_films(self) -> set[int]:
        with self._lock:
            return set(self._data.get("processed_films", []))

    @property
    def processed_serials(self) -> set[int]:
        with self._lock:
            return set(self._data.get("processed_serials", []))

    @property
    def pending_films(self) -> list[dict]:
        with self._lock:
            return list(self._data.get("pending_films", []))

    @property
    def pending_serials(self) -> list[dict]:
        with self._lock:
            return list(self._data.get("pending_serials", []))

    def mark_film_processed(self, filmweb_id: int) -> None:
        with self._lock:
            self._append_locked("processed_films", filmweb_id)

    def mark_serial_processed(self, filmweb_id: int) -> None:
        with self._lock:
            self._append_locked("processed_serials", filmweb_id)

    def enqueue_film(self, filmweb_id: int, result: dict) -> None:
        with self._lock:
            self._enqueue_locked("pending_films", "processed_films", filmweb_id, result)

    def enqueue_serial(self, filmweb_id: int, result: dict) -> None:
        with self._lock:
            self._enqueue_locked("pending_serials", "processed_serials", filmweb_id, result)

    def dequeue_films(self, n: int) -> list[dict]:
        with self._lock:
            return self._dequeue_locked("pending_films", n)

    def dequeue_serials(self, n: int) -> list[dict]:
        with self._lock:
            return self._dequeue_locked("pending_serials", n)

    def _enqueue_locked(
        self, queue_key: str, processed_key: str, filmweb_id: int, result: dict
    ) -> None:
        queue: list[dict] = self._data.setdefault(queue_key, [])
        already_queued = {item["filmweb_id"] for item in queue}
        processed = set(self._data.get(processed_key, []))
        if filmweb_id not in already_queued and filmweb_id not in processed:
            queue.append({"filmweb_id": filmweb_id, "result": result})
            self._save()

    def _dequeue_locked(self, key: str, n: int) -> list[dict]:
        queue: list[dict] = self._data.get(key, [])
        batch, self._data[key] = queue[:n], queue[n:]
        if batch:
            self._save()
        return batch

    def _append_locked(self, key: str, filmweb_id: int) -> None:
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
