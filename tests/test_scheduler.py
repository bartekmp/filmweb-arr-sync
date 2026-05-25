import signal
import threading
from unittest.mock import MagicMock, patch

import pytest

from filmweb_arr_sync.config import Config, FilmwebConfig, RadarrConfig, SonarrConfig, SyncConfig
from filmweb_arr_sync.scheduler import run_scheduler


def _make_config(interval_minutes: int = 30, cron: str | None = None) -> Config:
    return Config(
        filmweb=FilmwebConfig(username="testuser"),
        radarr=RadarrConfig(url="", api_key="", root_folder=""),
        sonarr=SonarrConfig(url="", api_key="", root_folder=""),
        sync=SyncConfig(interval_minutes=interval_minutes, cron=cron),
    )


@pytest.fixture
def syncer():
    return MagicMock()


@pytest.fixture(autouse=True)
def mock_health():
    with (
        patch("filmweb_arr_sync.scheduler.health.start"),
        patch("filmweb_arr_sync.scheduler.health.set_last_sync"),
    ):
        yield


def _shutdown_after(n_false_calls):
    """Return an is_set() side_effect that returns False n times then True.

    The scheduler calls is_set() twice per sync cycle: once at the while condition
    and once after syncer.run() before sleeping. So N cycles require 2*N false calls.
    """
    count = [0]

    def is_set():
        count[0] += 1
        return count[0] > n_false_calls

    return is_set


class TestRunScheduler:
    def test_runs_sync_on_first_iteration(self, syncer):
        event = MagicMock(spec=threading.Event)
        event.is_set.side_effect = _shutdown_after(2)

        with patch("filmweb_arr_sync.scheduler.threading.Event", return_value=event):
            run_scheduler(syncer, _make_config(interval_minutes=30))

        syncer.run.assert_called_once()

    def test_waits_with_correct_interval(self, syncer):
        event = MagicMock(spec=threading.Event)
        event.is_set.side_effect = _shutdown_after(2)

        with patch("filmweb_arr_sync.scheduler.threading.Event", return_value=event):
            run_scheduler(syncer, _make_config(interval_minutes=15))

        event.wait.assert_called_with(timeout=900)

    def test_runs_multiple_sync_cycles(self, syncer):
        event = MagicMock(spec=threading.Event)
        event.is_set.side_effect = _shutdown_after(6)  # 3 cycles × 2 calls each

        with patch("filmweb_arr_sync.scheduler.threading.Event", return_value=event):
            run_scheduler(syncer, _make_config(interval_minutes=5))

        assert syncer.run.call_count == 3

    def test_continues_after_sync_exception(self, syncer):
        syncer.run.side_effect = [Exception("network error"), MagicMock()]
        event = MagicMock(spec=threading.Event)
        event.is_set.side_effect = _shutdown_after(4)  # 2 cycles × 2 calls each

        with patch("filmweb_arr_sync.scheduler.threading.Event", return_value=event):
            run_scheduler(syncer, _make_config(interval_minutes=5))

        assert syncer.run.call_count == 2

    def test_registers_sigterm_and_sigint_handlers(self, syncer):
        event = MagicMock(spec=threading.Event)
        event.is_set.return_value = True  # exit immediately without syncing

        with (
            patch("filmweb_arr_sync.scheduler.threading.Event", return_value=event),
            patch("filmweb_arr_sync.scheduler.signal.signal") as mock_signal,
        ):
            run_scheduler(syncer, _make_config(interval_minutes=30))

        registered = {c[0][0] for c in mock_signal.call_args_list}
        assert signal.SIGTERM in registered
        assert signal.SIGINT in registered

    def test_exits_after_sync_without_sleeping_when_shutdown_set(self, syncer):
        """Shutdown set during run() exits immediately after, skipping the sleep."""
        event = MagicMock(spec=threading.Event)
        # False on loop entry, True on post-sync check → breaks before wait()
        event.is_set.side_effect = _shutdown_after(1)

        with patch("filmweb_arr_sync.scheduler.threading.Event", return_value=event):
            run_scheduler(syncer, _make_config(interval_minutes=30))

        syncer.run.assert_called_once()
        event.wait.assert_not_called()

    def test_cron_uses_next_trigger_as_wait_duration(self, syncer):
        event = MagicMock(spec=threading.Event)
        event.is_set.side_effect = _shutdown_after(2)

        with (
            patch("filmweb_arr_sync.scheduler.threading.Event", return_value=event),
            patch("filmweb_arr_sync.scheduler._next_cron_wait", return_value=(3600.0, MagicMock())),
        ):
            run_scheduler(syncer, _make_config(cron="0 * * * *"))

        event.wait.assert_called_with(timeout=3600.0)

    def test_cron_invalid_expression_exits(self, syncer):
        with pytest.raises(SystemExit):
            run_scheduler(syncer, _make_config(cron="not-a-cron"))
