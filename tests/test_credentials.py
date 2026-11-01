import json
import logging
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock
from urllib.parse import parse_qs, quote, urlsplit

import pytest
import requests
from urllib3.exceptions import ProtocolError

from filmweb_arr_sync.arr.radarr import RadarrClient
from filmweb_arr_sync.arr.sonarr import SonarrClient
from filmweb_arr_sync.bot.runner import BotRunner
from filmweb_arr_sync.bot.telegram import TelegramClient
from filmweb_arr_sync.config import load_config

API_KEY = "dummy-arr:key+secret"
BOT_TOKEN = "123456789:dummy-bot-token"
ARR_CLIENTS = [(RadarrClient, "movie", "tmdbId"), (SonarrClient, "series", "tvdbId")]


@pytest.fixture
def http_server():
    """Exercise requests, prepared URLs, HTTP errors and retries over loopback."""
    requests_seen = []
    response = {"status": 200, "body": {}}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            requests_seen.append((self.command, self.path, dict(self.headers), body))
            data = json.dumps(response.get(self.command, response["body"])).encode()
            self.send_response(response["status"], response.get("reason"))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_POST = do_GET

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", response, requests_seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    # Keep the production retry policy, but avoid waiting during failure tests.
    monkeypatch.setattr("urllib3.util.retry.Retry.sleep", lambda *_args: None)


def telegram_client(monkeypatch, url):
    monkeypatch.setattr("filmweb_arr_sync.bot.telegram._BASE", url)
    client = TelegramClient(BOT_TOKEN, poll_timeout_seconds=12)
    client._session.trust_env = False
    client._session.mount("http://", client._session.get_adapter("https://"))
    return client


@pytest.mark.parametrize("client_class,resource,id_key", ARR_CLIENTS)
def test_arr_auth_and_payloads_over_http(http_server, client_class, resource, id_key):
    url, response, seen = http_server
    client = client_class(url + "/", API_KEY, monitored=False)
    client._session.trust_env = False

    response["body"] = [{id_key: 42}]
    get_ids = getattr(client, f"get_existing_{id_key[:-2].lower()}_ids")
    assert get_ids() == {42}
    response["body"] = [{"id": 7, "label": "filmweb"}]
    assert client.ensure_tag("filmweb") == 7
    response.update(GET=[], POST={"id": 8})
    assert client.ensure_tag("new") == 8
    del response["GET"], response["POST"]
    response["body"] = [{"title": "Test Title", id_key: 42}]
    assert client.lookup(["Test Title"], 2023)[id_key] == 42
    assert client.lookup_by_imdb("tt1234567")[id_key] == 42
    response["body"] = {}
    client.add({"id": 99, "title": "Test Title", id_key: 42}, "/media", 2, tag_id=7)

    for _method, path, headers, _body in seen:
        assert headers["X-Api-Key"] == API_KEY
        assert headers["Content-Type"] == "application/json"
        assert API_KEY not in path
        assert "apikey" not in parse_qs(urlsplit(path).query)
    assert seen[0][1] == f"/api/v3/{resource}"
    assert parse_qs(urlsplit(seen[4][1]).query) == {"term": ["Test Title 2023"]}
    assert parse_qs(urlsplit(seen[5][1]).query) == {"term": ["imdb:tt1234567"]}
    method, path, _headers, body = seen[-1]
    assert (method, path) == ("POST", f"/api/v3/{resource}")
    payload = json.loads(body)
    assert "id" not in payload
    assert payload[id_key] == 42
    assert payload["monitored"] is False
    assert payload["tags"] == [7]


@pytest.mark.parametrize("client_class,resource,id_key", ARR_CLIENTS)
@pytest.mark.parametrize("status", [401, 500])
@pytest.mark.parametrize("operation", ["library", "lookup", "imdb", "tag", "add"])
def test_arr_http_errors_do_not_log_key(
    http_server, caplog, client_class, resource, id_key, status, operation
):
    url, response, seen = http_server
    response.update(
        status=status,
        reason=f"Rejected {API_KEY}",
        body={"message": f"Rejected credential: {API_KEY}"},
    )
    client = client_class(url, API_KEY)
    client._session.trust_env = False
    calls = {
        "library": lambda: getattr(client, f"get_existing_{id_key[:-2].lower()}_ids")(),
        "lookup": lambda: client.lookup(["Test Title"], 2023),
        "imdb": lambda: client.lookup_by_imdb("tt1234567"),
        "tag": lambda: client.ensure_tag("filmweb"),
        "add": lambda: client.add({"title": "Test Title", id_key: 42}, "/media", 1),
    }
    with pytest.raises(requests.RequestException) as caught:
        calls[operation]()
    # Match existing sync/batch/bot callers, including traceback formatting.
    logging.getLogger(__name__).error(
        "ARR failed: %s", caught.value, exc_info=(caught.type, caught.value, caught.tb)
    )
    assert len(seen) == (4 if status == 500 and operation != "add" else 1)
    assert API_KEY not in caplog.text
    assert API_KEY not in str(caught.value)
    assert str(status) in caplog.text


@pytest.mark.parametrize("client_class,resource,id_key", ARR_CLIENTS)
@pytest.mark.parametrize("status", [401, 500])
def test_arr_redacts_key_from_http_reason(
    http_server, caplog, client_class, resource, id_key, status
):
    url, response, _seen = http_server
    response.update(status=status, reason=f"Rejected {API_KEY}")
    client = client_class(url, API_KEY)
    client._session.trust_env = False
    with pytest.raises(requests.RequestException) as caught:
        client.add({"title": "Test Title", id_key: 42}, "/media", 1)
    logging.getLogger(__name__).error(
        "ARR failed: %s", caught.value, exc_info=(caught.type, caught.value, caught.tb)
    )
    assert API_KEY not in caplog.text
    assert "[REDACTED]" in str(caught.value)
    assert str(status) in str(caught.value)
    assert caught.value.response.status_code == status
    assert caught.value.request.headers["X-Api-Key"] == API_KEY


@pytest.mark.parametrize("client_class,resource,id_key", ARR_CLIENTS)
@pytest.mark.parametrize("key", [" dummy-secret", "dummy-secret\n", "dummy-secret\U0001f511"])
def test_arr_invalid_header_does_not_expose_key(caplog, client_class, resource, id_key, key):
    with pytest.raises(requests.exceptions.InvalidHeader) as caught:
        client = client_class("http://invalid.local", key)
        client.ensure_tag("filmweb")
    logging.getLogger(__name__).error(
        "ARR failed: %s", caught.value, exc_info=(caught.type, caught.value, caught.tb)
    )
    assert "dummy-secret" not in caplog.text
    assert "dummy-secret" not in str(caught.value)


@pytest.mark.parametrize("method", ["get_me", "get_updates", "send_message"])
@pytest.mark.parametrize("status", [401, 500])
def test_telegram_http_errors_are_safe(http_server, monkeypatch, caplog, method, status):
    url, response, seen = http_server
    response.update(status=status, body={"description": f"Rejected bot {BOT_TOKEN}"})
    client = telegram_client(monkeypatch, url)
    args = (99, "hello") if method == "send_message" else ()
    with pytest.raises(requests.RequestException) as caught:
        getattr(client, method)(*args)
    rendered = "".join(traceback.format_exception(caught.value))
    logging.getLogger(__name__).error(
        "Telegram failed: %s", caught.value, exc_info=(caught.type, caught.value, caught.tb)
    )
    assert len(seen) == (4 if status == 500 and method != "send_message" else 1)
    assert BOT_TOKEN not in str(caught.value)
    assert BOT_TOKEN not in rendered
    assert BOT_TOKEN not in caplog.text
    assert method.replace("_", "").lower() in str(caught.value).lower()
    assert str(status) in str(caught.value)


def test_telegram_success_and_request_options(http_server, monkeypatch):
    url, response, seen = http_server
    client = telegram_client(monkeypatch, url)
    response["body"] = {"ok": True, "result": {"id": 123, "is_bot": True}}
    assert client.get_me() == {"id": 123, "is_bot": True}
    response["body"] = {"ok": True, "result": [{"update_id": 17}]}
    assert client.get_updates(offset=16) == [{"update_id": 17}]
    assert parse_qs(urlsplit(seen[-1][1]).query) == {
        "timeout": ["12"],
        "allowed_updates": ['["message"]'],
        "offset": ["16"],
    }
    response["body"] = {"ok": True, "result": {}}
    assert client.send_message(99, "hello") is None
    assert seen[-1][0] == "POST"
    assert seen[-1][1] == f"/bot{BOT_TOKEN}/sendMessage"
    assert json.loads(seen[-1][3]) == {
        "chat_id": 99,
        "text": "hello",
        "disable_web_page_preview": True,
    }


def test_telegram_api_error_redacts_token(http_server, monkeypatch, caplog):
    url, response, _seen = http_server
    response["body"] = {"ok": False, "description": BOT_TOKEN, "error_code": 401}
    client = telegram_client(monkeypatch, url)
    with pytest.raises(RuntimeError) as caught:
        client.get_updates()
    logging.getLogger(__name__).error("Polling failed: %s", caught.value)
    assert "getUpdates" in str(caught.value)
    assert BOT_TOKEN not in caplog.text


@pytest.mark.parametrize("method", ["get_me", "get_updates", "send_message"])
def test_telegram_connection_retry_logs_are_safe(monkeypatch, caplog, method):
    caplog.set_level(logging.DEBUG)
    client = TelegramClient(BOT_TOKEN)
    client._session.trust_env = False

    def disconnect(*_args, **_kwargs):
        raise ProtocolError("Connection aborted", OSError("test disconnect"))

    monkeypatch.setattr("urllib3.connectionpool.HTTPSConnectionPool._make_request", disconnect)
    args = (99, "hello") if method == "send_message" else ()
    with pytest.raises(requests.RequestException) as caught:
        getattr(client, method)(*args)
    if method != "send_message":
        assert any("Retrying" in r.getMessage() for r in caplog.records)
    assert BOT_TOKEN not in caplog.text
    assert BOT_TOKEN not in "".join(traceback.format_exception(caught.value))
    assert "ConnectionError" in str(caught.value)


@pytest.mark.parametrize("client_class,resource,id_key", ARR_CLIENTS)
@pytest.mark.parametrize("encoded", [False, True])
def test_arr_redacts_echoed_key_before_truncation(
    http_server, caplog, client_class, resource, id_key, encoded
):
    url, response, _seen = http_server
    credential = quote(API_KEY, safe="").replace("%3A", "%3a") if encoded else API_KEY
    response.update(status=401, body={"message": "x" * 470 + credential})
    client = client_class(url, API_KEY)
    client._session.trust_env = False
    with pytest.raises(requests.HTTPError):
        client.add({"title": "Test Title", id_key: 42}, "/media", 1)
    assert "[REDACTED]" in caplog.text
    assert "dummy-arr" not in caplog.text


@pytest.mark.parametrize("encoded", [False, True])
def test_telegram_redacts_echoed_token_before_truncation(http_server, monkeypatch, caplog, encoded):
    url, response, _seen = http_server
    credential = quote(BOT_TOKEN, safe="").replace("%3A", "%3a") if encoded else BOT_TOKEN
    response.update(status=401, body={"description": "x" * 260 + credential})
    client = telegram_client(monkeypatch, url)
    with pytest.raises(requests.HTTPError):
        client.send_message(99, "hello")
    assert "[REDACTED]" in caplog.text
    assert "123456789" not in caplog.text


@pytest.mark.parametrize("failure", ["poll", "reply"])
@pytest.mark.parametrize("status", [401, 500])
def test_runner_logs_no_token_on_http_error(
    http_server, monkeypatch, tmp_path, caplog, failure, status
):
    url, response, _seen = http_server
    config = load_config(str(tmp_path / "missing.yaml"))
    config.telegram.bot_token = BOT_TOKEN
    config.telegram.allowed_user_ids = [111]
    shutdown = threading.Event()
    handler = MagicMock()
    handler.handle_message.return_value = "reply"
    runner = BotRunner(config, handler, shutdown)
    runner._client = telegram_client(monkeypatch, url)
    response.update(status=status, body={"description": BOT_TOKEN})

    def stop_waiting(**_kwargs):
        shutdown.set()

    monkeypatch.setattr(shutdown, "wait", stop_waiting)
    if failure == "reply":

        def updates(_offset):
            shutdown.set()
            return [
                {
                    "update_id": 1,
                    "message": {"chat": {"id": 99}, "from": {"id": 111}, "text": "/help"},
                }
            ]

        monkeypatch.setattr(runner._client, "get_updates", updates)
    runner._run()
    assert "failed" in caplog.text if failure == "poll" else "Error handling" in caplog.text
    assert BOT_TOKEN not in caplog.text
