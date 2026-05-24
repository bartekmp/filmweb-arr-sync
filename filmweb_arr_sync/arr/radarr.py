import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_RETRY = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])


class RadarrClient:
    def __init__(self, url: str, api_key: str) -> None:
        self._base = url.rstrip("/")
        self._session = requests.Session()
        self._session.params["apikey"] = api_key  # type: ignore[assignment]
        self._session.headers["Content-Type"] = "application/json"
        adapter = HTTPAdapter(max_retries=_RETRY)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def get_existing_tmdb_ids(self) -> set[int]:
        response = self._session.get(f"{self._base}/api/v3/movie", timeout=30)
        response.raise_for_status()
        return {m["tmdbId"] for m in response.json()}

    def ensure_tag(self, label: str) -> int:
        response = self._session.get(f"{self._base}/api/v3/tag", timeout=30)
        response.raise_for_status()
        for tag in response.json():
            if tag["label"] == label:
                return tag["id"]
        response = self._session.post(f"{self._base}/api/v3/tag", json={"label": label}, timeout=30)
        response.raise_for_status()
        return response.json()["id"]

    def lookup(self, titles: list[str], year: int) -> dict | None:
        for title in titles:
            response = self._session.get(
                f"{self._base}/api/v3/movie/lookup",
                params={"term": f"{title} {year}"},
                timeout=30,
            )
            response.raise_for_status()
            results = response.json()
            if results:
                return results[0]
        return None

    def add(
        self, movie: dict, root_folder: str, quality_profile_id: int, tag_id: int | None = None
    ) -> None:
        payload = {
            "title": movie["title"],
            "year": movie.get("year"),
            "tmdbId": movie["tmdbId"],
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder,
            "monitored": True,
            "tags": [tag_id] if tag_id is not None else [],
            "addOptions": {"searchForMovie": True},
        }
        response = self._session.post(f"{self._base}/api/v3/movie", json=payload, timeout=30)
        response.raise_for_status()
