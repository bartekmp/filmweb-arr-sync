import logging
import threading

from .arr.radarr import RadarrClient
from .arr.sonarr import SonarrClient
from .config import Config
from .state import State

logger = logging.getLogger(__name__)


class BatchProcessor:
    def __init__(
        self,
        config: Config,
        state: State,
        radarr: RadarrClient | None,
        sonarr: SonarrClient | None,
        shutdown: threading.Event,
    ) -> None:
        self._config = config
        self._state = state
        self._radarr = radarr
        self._sonarr = sonarr
        self._shutdown = shutdown
        self._batch_size = config.sync.batch_size
        self._interval_seconds = config.sync.batch_interval_minutes * 60

    def start(self) -> None:
        thread = threading.Thread(target=self._run, name="batch-processor", daemon=True)
        thread.start()
        logger.info(
            "Batch processor started — %d item(s) per batch, %d min between batches",
            self._batch_size,
            self._config.sync.batch_interval_minutes,
        )

    def _run(self) -> None:
        while not self._shutdown.is_set():
            processed_any = False

            if self._radarr:
                processed_any |= self._process_films()

            if self._sonarr:
                processed_any |= self._process_serials()

            pending_total = len(self._state.pending_films) + len(self._state.pending_serials)
            if processed_any and pending_total > 0:
                logger.info(
                    "Batch done; %d item(s) still pending — next batch in %d min",
                    pending_total,
                    self._config.sync.batch_interval_minutes,
                )

            self._shutdown.wait(timeout=self._interval_seconds)

    def _process_films(self) -> bool:
        batch = self._state.dequeue_films(self._batch_size)
        if not batch:
            return False

        logger.info("Processing batch of %d movie(s)", len(batch))
        tag_id = self._resolve_tag(self._radarr, self._config.radarr.tag)

        for item in batch:
            filmweb_id: int = item["filmweb_id"]
            result: dict = item["result"]
            title = result.get("title", f"filmweb_id={filmweb_id}")
            tmdb_id = result.get("tmdbId", 0)
            try:
                self._radarr.add(  # type: ignore[union-attr]
                    result,
                    self._config.radarr.root_folder,
                    self._config.radarr.quality_profile_id,
                    tag_id=tag_id,
                )
                logger.info(
                    "Added to Radarr: %s (tmdbId=%d)", title, tmdb_id, extra={"status": "ok"}
                )
                self._state.mark_film_processed(filmweb_id)
            except Exception as e:
                logger.error("Failed to add %s to Radarr: %s — will retry next sync", title, e)
        return True

    def _process_serials(self) -> bool:
        batch = self._state.dequeue_serials(self._batch_size)
        if not batch:
            return False

        logger.info("Processing batch of %d serial(s)", len(batch))
        tag_id = self._resolve_tag(self._sonarr, self._config.sonarr.tag)

        for item in batch:
            filmweb_id: int = item["filmweb_id"]
            result: dict = item["result"]
            title = result.get("title", f"filmweb_id={filmweb_id}")
            tvdb_id = result.get("tvdbId", 0)
            try:
                self._sonarr.add(  # type: ignore[union-attr]
                    result,
                    self._config.sonarr.root_folder,
                    self._config.sonarr.quality_profile_id,
                    language_profile_id=self._config.sonarr.language_profile_id,
                    tag_id=tag_id,
                )
                logger.info(
                    "Added to Sonarr: %s (tvdbId=%d)", title, tvdb_id, extra={"status": "ok"}
                )
                self._state.mark_serial_processed(filmweb_id)
            except Exception as e:
                logger.error("Failed to add %s to Sonarr: %s — will retry next sync", title, e)
        return True

    def _resolve_tag(self, client: RadarrClient | SonarrClient | None, tag_name: str) -> int | None:
        if not tag_name or not client:
            return None
        try:
            return client.ensure_tag(tag_name)
        except Exception as e:
            logger.warning("Could not resolve tag '%s': %s — adding without tag", tag_name, e)
            return None
