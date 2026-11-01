import json
import logging
import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .._http import redact_secret

logger = logging.getLogger(__name__)

_BASE = "https://api.telegram.org"
_RETRY = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])


def _redact_bot_url(record: logging.LogRecord) -> bool:
    # urllib3 logs retry warnings before requests raises an exception. Filter at
    # the emitting logger so every handler receives a sanitized message.
    message = record.getMessage()
    if "/bot" in message:
        record.msg = re.sub(r"(/bot)[^/\s'\"?]+", r"\1[REDACTED]", message)
        record.args = ()
    return True


class TelegramClient:
    """Minimal Telegram Bot API client using long-polling over `requests`.

    Only the handful of methods the bot needs are implemented; this keeps the
    project free of a heavier async bot framework.
    """

    def __init__(self, token: str, poll_timeout_seconds: int = 30) -> None:
        self._token = token
        self._base = f"{_BASE}/bot{token}"
        self._poll_timeout = poll_timeout_seconds
        self._session = requests.Session()
        adapter = HTTPAdapter(max_retries=_RETRY)
        self._session.mount("https://", adapter)
        logging.getLogger("urllib3.connectionpool").addFilter(_redact_bot_url)
        logging.getLogger("urllib3.util.retry").addFilter(_redact_bot_url)

    def _request(self, method: str, http_method: str = "GET", **kwargs) -> dict:
        try:
            response = self._session.request(http_method, f"{self._base}/{method}", **kwargs)
            if method == "sendMessage" and not response.ok:
                logger.error(
                    "Telegram sendMessage failed: %s",
                    redact_secret(response.text, self._token)[:300],
                )
            response.raise_for_status()
            return response.json() if method != "sendMessage" else {}
        except requests.RequestException as exc:
            error_type = (
                requests.HTTPError
                if isinstance(exc, requests.HTTPError)
                else requests.RequestException
            )
            message = redact_secret(str(exc), self._token)
            # The runner logs tracebacks too; do not expose the original exception
            # through its implicit context or cause.
            raise error_type(
                f"Telegram {method} failed ({type(exc).__name__}): {message}"
            ) from None

    def get_me(self) -> dict:
        return self._request("getMe", timeout=30).get("result", {})

    def get_updates(self, offset: int | None = None) -> list[dict]:
        params: dict = {"timeout": self._poll_timeout, "allowed_updates": json.dumps(["message"])}
        if offset is not None:
            params["offset"] = offset
        # Read timeout must outlast the server-side long-poll window.
        data = self._request("getUpdates", params=params, timeout=self._poll_timeout + 10)
        if not data.get("ok"):
            raise RuntimeError(
                f"Telegram getUpdates returned an error: {redact_secret(str(data), self._token)}"
            )
        return data.get("result", [])

    def send_message(self, chat_id: int, text: str) -> None:
        self._request(
            "sendMessage",
            "POST",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=30,
        )
