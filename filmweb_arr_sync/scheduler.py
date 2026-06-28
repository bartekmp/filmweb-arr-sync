import logging
import signal
import sys
import threading
from datetime import datetime

from croniter import croniter

from . import health
from .config import Config
from .sync import Syncer

logger = logging.getLogger(__name__)


def _validate_cron(expr: str) -> None:
    if not croniter.is_valid(expr):
        logger.critical(
            "Invalid SYNC_CRON expression: %r — see https://crontab.guru for help", expr
        )
        sys.exit(1)


def _next_cron_wait(expr: str) -> tuple[float, datetime]:
    now = datetime.now()
    next_run: datetime = croniter(expr, now).get_next(datetime)
    return (next_run - datetime.now()).total_seconds(), next_run


def _maybe_start_bot(syncer: Syncer, config: Config, shutdown: threading.Event) -> None:
    if not config.telegram.enabled:
        return
    if not config.telegram.bot_token:
        logger.warning("Telegram bot enabled but TELEGRAM_BOT_TOKEN is empty — bot not started")
        return

    from .bot.handler import BotHandler
    from .bot.runner import BotRunner

    handler = BotHandler(
        config,
        syncer.state,
        syncer.radarr,
        syncer.sonarr,
        syncer.filmweb,
    )
    BotRunner(config, handler, shutdown).start()


def run_scheduler(syncer: Syncer, config: Config) -> None:
    sync_cfg = config.sync

    if sync_cfg.cron:
        _validate_cron(sync_cfg.cron)
        logger.info("Daemon started — syncing on cron schedule: %s", sync_cfg.cron)
    else:
        logger.info("Daemon started — syncing every %d minutes", sync_cfg.interval_minutes)

    health.start()

    shutdown = threading.Event()
    syncer.start_batch_processor(shutdown)
    _maybe_start_bot(syncer, config, shutdown)

    def _handle_signal(signum: int, frame: object) -> None:
        logger.info("Shutdown signal received, stopping after current sync...")
        shutdown.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not shutdown.is_set():
        try:
            syncer.run()
            health.set_last_sync(datetime.now().astimezone().isoformat())
        except Exception as e:
            logger.error("Sync failed with unexpected error: %s", e, exc_info=True)

        if shutdown.is_set():
            break

        if sync_cfg.cron:
            wait_seconds, next_run = _next_cron_wait(sync_cfg.cron)
            logger.info("Next sync at %s", next_run.strftime("%Y-%m-%dT%H:%M:%S"))
            shutdown.wait(timeout=max(0.0, wait_seconds))
        else:
            logger.info("Next sync in %d minutes", sync_cfg.interval_minutes)
            shutdown.wait(timeout=sync_cfg.interval_minutes * 60)

    logger.info("Daemon stopped")
