import logging
import signal
import threading

from .sync import Syncer

logger = logging.getLogger(__name__)


def run_scheduler(syncer: Syncer, interval_minutes: int) -> None:
    interval_seconds = interval_minutes * 60
    logger.info("Daemon started — syncing every %d minutes", interval_minutes)

    shutdown = threading.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        logger.info("Shutdown signal received, stopping after current sync...")
        shutdown.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not shutdown.is_set():
        try:
            syncer.run()
        except Exception as e:
            logger.error("Sync failed with unexpected error: %s", e, exc_info=True)

        if shutdown.is_set():
            break

        logger.info("Next sync in %d minutes", interval_minutes)
        shutdown.wait(timeout=interval_seconds)

    logger.info("Daemon stopped")
