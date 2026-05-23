import logging

import requests

logger = logging.getLogger(__name__)


class SonarrClient:
    def __init__(self, url: str, api_key: str) -> None:
        self._base = url.rstrip("/")
        self._session = requests.Session()
        self._session.params["apikey"] = api_key  # type: ignore[assignment]
        self._session.headers["Content-Type"] = "application/json"

    def get_existing_tvdb_ids(self) -> set[int]:
        response = self._session.get(f"{self._base}/api/v3/series", timeout=30)
        response.raise_for_status()
        return {s["tvdbId"] for s in response.json()}

    def lookup(self, titles: list[str], year: int) -> dict | None:
        for title in titles:
            response = self._session.get(
                f"{self._base}/api/v3/series/lookup",
                params={"term": f"{title} {year}"},
                timeout=30,
            )
            response.raise_for_status()
            results = response.json()
            if results:
                return results[0]
        return None

    def add(
        self,
        series: dict,
        root_folder: str,
        quality_profile_id: int,
        language_profile_id: int | None = None,
    ) -> None:
        payload = {
            "title": series["title"],
            "tvdbId": series["tvdbId"],
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder,
            "monitored": True,
            "seasonFolder": True,
            "seasons": series.get("seasons", []),
            "addOptions": {"searchForMissingEpisodes": True},
        }
        # languageProfileId is required by Sonarr v3 but ignored by v4
        if language_profile_id is not None:
            payload["languageProfileId"] = language_profile_id

        response = self._session.post(f"{self._base}/api/v3/series", json=payload, timeout=30)
        response.raise_for_status()
