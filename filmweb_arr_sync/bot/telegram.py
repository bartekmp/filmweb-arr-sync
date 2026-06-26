import json
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_BASE = "https://api.telegram.org"
_RETRY = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])


class TelegramClient:
    """Minimal Telegram Bot API client using long-polling over `requests`.

    Only the handful of methods the bot needs are implemented; this keeps the
    project free of a heavier async bot framework.
    """

    def __init__(self, token: str, poll_timeout_seconds: int = 30) -> None:
        self._base = f"{_BASE}/bot{token}"
        self._poll_timeout = poll_timeout_seconds
        self._session = requests.Session()
        adapter = HTTPAdapter(max_retries=_RETRY)
        self._session.mount("https://", adapter)

    def get_me(self) -> dict:
        response = self._session.get(f"{self._base}/getMe", timeout=30)
        response.raise_for_status()
        return response.json().get("result", {})

    def get_updates(self, offset: int | None = None) -> list[dict]:
        params: dict = {"timeout": self._poll_timeout, "allowed_updates": json.dumps(["message"])}
        if offset is not None:
            params["offset"] = offset
        # Read timeout must outlast the server-side long-poll window.
        response = self._session.get(
            f"{self._base}/getUpdates", params=params, timeout=self._poll_timeout + 10
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getUpdates returned an error: {data}")
        return data.get("result", [])

    def send_message(self, chat_id: int, text: str) -> None:
        response = self._session.post(
            f"{self._base}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=30,
        )
        if not response.ok:
            logger.error("Telegram sendMessage failed: %s", response.text[:300])
        response.raise_for_status()
