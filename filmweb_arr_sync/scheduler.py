import logging
import time

from .sync import Syncer

logger = logging.getLogger(__name__)


def run_scheduler(syncer: Syncer, interval_minutes: int) -> None:
    interval_seconds = interval_minutes * 60
    logger.info("Daemon started — syncing every %d minutes", interval_minutes)

    while True:
        try:
            syncer.run()
        except Exception as e:
            logger.error("Sync failed with unexpected error: %s", e, exc_info=True)

        logger.info("Next sync in %d minutes", interval_minutes)
        time.sleep(interval_seconds)
