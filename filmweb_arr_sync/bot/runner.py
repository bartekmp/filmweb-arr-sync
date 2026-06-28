import logging
import threading

from ..config import Config
from .handler import BotHandler
from .telegram import TelegramClient

logger = logging.getLogger(__name__)


class BotRunner:
    """Runs the Telegram long-polling loop in a background daemon thread."""

    def __init__(self, config: Config, handler: BotHandler, shutdown: threading.Event) -> None:
        self._config = config
        self._handler = handler
        self._shutdown = shutdown
        tg = config.telegram
        self._client = TelegramClient(tg.bot_token, tg.poll_timeout_seconds)
        self._allowed = set(tg.allowed_user_ids)

    def start(self) -> None:
        thread = threading.Thread(target=self._run, name="telegram-bot", daemon=True)
        thread.start()
        scope = (
            f"restricted to {len(self._allowed)} user(s)"
            if self._allowed
            else "open to all users (set TELEGRAM_ALLOWED_USER_IDS to restrict)"
        )
        logger.info("Telegram bot started — %s", scope)

    def _run(self) -> None:
        offset: int | None = None
        backoff = 1
        while not self._shutdown.is_set():
            try:
                updates = self._client.get_updates(offset)
                backoff = 1
            except Exception as e:
                logger.warning("Telegram getUpdates failed: %s — retrying in %ds", e, backoff)
                self._shutdown.wait(timeout=backoff)
                backoff = min(backoff * 2, 60)
                continue

            for update in updates:
                offset = update["update_id"] + 1
                try:
                    self._dispatch(update)
                except Exception as e:
                    logger.error(
                        "Error handling update %s: %s", update.get("update_id"), e, exc_info=True
                    )

    def _dispatch(self, update: dict) -> None:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return
        text = message.get("text")
        if not text:
            return

        chat_id = message["chat"]["id"]
        user_id = message.get("from", {}).get("id")

        if self._allowed and user_id not in self._allowed:
            logger.warning("Ignoring message from unauthorized user_id=%s", user_id)
            self._client.send_message(chat_id, "⛔ You're not authorized to use this bot.")
            return

        reply = self._handler.handle_message(text)
        if reply:
            self._client.send_message(chat_id, reply)
