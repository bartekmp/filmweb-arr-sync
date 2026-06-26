import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_RETRY = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])


class SonarrClient:
    def __init__(self, url: str, api_key: str) -> None:
        self._base = url.rstrip("/")
        self._session = requests.Session()
        self._session.params["apikey"] = api_key  # type: ignore[assignment]
        self._session.headers["Content-Type"] = "application/json"
        adapter = HTTPAdapter(max_retries=_RETRY)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def get_existing_tvdb_ids(self) -> set[int]:
        response = self._session.get(f"{self._base}/api/v3/series", timeout=30)
        response.raise_for_status()
        return {s["tvdbId"] for s in response.json()}

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
                f"{self._base}/api/v3/series/lookup",
                params={"term": f"{title} {year}"},
                timeout=30,
            )
            response.raise_for_status()
            results = response.json()
            if results:
                return results[0]
        return None

    def lookup_by_imdb(self, imdb_id: str) -> dict | None:
        response = self._session.get(
            f"{self._base}/api/v3/series/lookup",
            params={"term": f"imdb:{imdb_id}"},
            timeout=30,
        )
        response.raise_for_status()
        results = response.json()
        return results[0] if results else None

    def add(
        self,
        series: dict,
        root_folder: str,
        quality_profile_id: int,
        language_profile_id: int | None = None,
        tag_id: int | None = None,
        search: bool = False,
    ) -> None:
        payload = {
            **{k: v for k, v in series.items() if k != "id"},
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder,
            "monitored": True,
            "seasonFolder": True,
            "tags": [tag_id] if tag_id is not None else [],
            "addOptions": {"searchForMissingEpisodes": search},
        }
        # languageProfileId is required by Sonarr v3 but ignored by v4
        if language_profile_id is not None:
            payload["languageProfileId"] = language_profile_id

        response = self._session.post(f"{self._base}/api/v3/series", json=payload, timeout=30)
        if not response.ok:
            logger.error(
                "Sonarr rejected add for '%s': %s", series.get("title"), response.text[:500]
            )
        response.raise_for_status()
