import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import FilmwebItem

logger = logging.getLogger(__name__)

_BASE = "https://www.filmweb.pl"
_INFO_DELAY = 0.5  # seconds between /info calls to avoid rate limiting
_RETRY = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])


class FilmwebClient:
    def __init__(self, username: str) -> None:
        self._username = username
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "filmweb-arr-sync/1.0",
                "Accept": "application/json",
            }
        )
        adapter = HTTPAdapter(max_retries=_RETRY)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def get_movies(self) -> list[FilmwebItem]:
        return self._fetch_watchlist("film")

    def get_serials(self) -> list[FilmwebItem]:
        return self._fetch_watchlist("serial")

    def get_item(self, filmweb_id: int, item_type: str) -> FilmwebItem | None:
        """Fetch info for a single title. item_type is 'film' or 'serial'."""
        return self._fetch_item_info(filmweb_id, item_type)

    def _fetch_watchlist(self, item_type: str) -> list[FilmwebItem]:
        url = f"{_BASE}/api/v1/user/{self._username}/want2see/{item_type}"
        logger.debug("GET %s", url)

        response = self._session.get(url, timeout=30)
        response.raise_for_status()

        entries = response.json()
        logger.info("Filmweb returned %d %s(s) in want-to-see list", len(entries), item_type)

        total = len(entries)
        items: list[FilmwebItem] = []
        for i, entry in enumerate(entries):
            if i % 10 == 0:
                logger.info("⏳ Fetching %s details... (%d/%d)", item_type, i, total)
            filmweb_id: int = entry["entity"]
            item = self._fetch_item_info(filmweb_id, item_type)
            if item:
                items.append(item)
            time.sleep(_INFO_DELAY)

        return items

    def _fetch_item_info(self, filmweb_id: int, item_type: str) -> FilmwebItem | None:
        url = f"{_BASE}/api/v1/title/{filmweb_id}/info"
        try:
            response = self._session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            title = data.get("title") or data.get("originalTitle", "")
            original_title = data.get("originalTitle") or data.get("title", "")
            year: int = data.get("year", 0)

            if not title or not year:
                logger.warning("Incomplete data for Filmweb ID %d, skipping", filmweb_id)
                return None

            return FilmwebItem(
                filmweb_id=filmweb_id,
                title=title,
                original_title=original_title,
                year=year,
                item_type=item_type,
            )
        except requests.HTTPError as e:
            logger.warning(
                "HTTP %s fetching info for Filmweb ID %d", e.response.status_code, filmweb_id
            )
            return None
        except Exception as e:
            logger.warning("Failed to fetch info for Filmweb ID %d: %s", filmweb_id, e)
            return None
