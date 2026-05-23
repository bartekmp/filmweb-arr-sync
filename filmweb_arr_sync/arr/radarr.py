import logging

import requests

logger = logging.getLogger(__name__)


class RadarrClient:
    def __init__(self, url: str, api_key: str) -> None:
        self._base = url.rstrip("/")
        self._session = requests.Session()
        self._session.params["apikey"] = api_key  # type: ignore[assignment]
        self._session.headers["Content-Type"] = "application/json"

    def get_existing_tmdb_ids(self) -> set[int]:
        response = self._session.get(f"{self._base}/api/v3/movie", timeout=30)
        response.raise_for_status()
        return {m["tmdbId"] for m in response.json()}

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

    def add(self, movie: dict, root_folder: str, quality_profile_id: int) -> None:
        payload = {
            "title": movie["title"],
            "year": movie.get("year"),
            "tmdbId": movie["tmdbId"],
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder,
            "monitored": True,
            "addOptions": {"searchForMovie": True},
        }
        response = self._session.post(f"{self._base}/api/v3/movie", json=payload, timeout=30)
        response.raise_for_status()
