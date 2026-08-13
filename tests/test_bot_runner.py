import threading
from unittest.mock import MagicMock

import pytest

from filmweb_arr_sync.bot.runner import BotRunner
from filmweb_arr_sync.config import load_config


@pytest.fixture
def config(tmp_path):
    return load_config(str(tmp_path / "missing.yaml"))


def _runner(config, allowed_user_ids):
    config.telegram.allowed_user_ids = allowed_user_ids
    handler = MagicMock()
    handler.handle_message.return_value = "reply"
    runner = BotRunner(config, handler, threading.Event())
    runner._client = MagicMock()
    return runner


def _update(user_id, text="/help"):
    return {
        "update_id": 1,
        "message": {"chat": {"id": 99}, "from": {"id": user_id}, "text": text},
    }


class TestAuthorization:
    def test_allowed_user_is_handled(self, config):
        runner = _runner(config, [111])
        runner._dispatch(_update(111))
        runner._handler.handle_message.assert_called_once_with("/help")
        runner._client.send_message.assert_called_once_with(99, "reply")

    def test_unknown_user_is_ignored_silently(self, config):
        runner = _runner(config, [111])
        runner._dispatch(_update(222))
        runner._handler.handle_message.assert_not_called()
        runner._client.send_message.assert_not_called()

    def test_empty_allow_list_authorizes_nobody(self, config):
        runner = _runner(config, [])
        runner._dispatch(_update(111))
        runner._handler.handle_message.assert_not_called()
        runner._client.send_message.assert_not_called()

    def test_message_without_sender_is_ignored(self, config):
        runner = _runner(config, [111])
        update = {"update_id": 1, "message": {"chat": {"id": 99}, "text": "/help"}}
        runner._dispatch(update)
        runner._handler.handle_message.assert_not_called()

    def test_edited_message_is_also_checked(self, config):
        runner = _runner(config, [111])
        runner._dispatch(
            {
                "update_id": 1,
                "message": None,
                "edited_message": {"chat": {"id": 99}, "from": {"id": 222}, "text": "/help"},
            }
        )
        runner._handler.handle_message.assert_not_called()
