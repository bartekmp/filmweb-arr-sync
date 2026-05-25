import logging
import threading
import time

from .arr.radarr import RadarrClient
from .arr.sonarr import SonarrClient
from .config import Config
from .filmweb.client import FilmwebClient
from .filmweb.models import FilmwebItem
from .state import State

logger = logging.getLogger(__name__)


class Syncer:
    def __init__(self, config: Config, state: State) -> None:
        self._config = config
        self._state = state
        self._dry_run = config.sync.dry_run
        self._add_delay = config.sync.add_delay_seconds
        self._filmweb = FilmwebClient(config.filmweb.username)

        self._radarr: RadarrClient | None = None
        if config.radarr.enabled and config.radarr.url and config.radarr.api_key:
            self._radarr = RadarrClient(config.radarr.url, config.radarr.api_key)

        self._sonarr: SonarrClient | None = None
        if config.sonarr.enabled and config.sonarr.url and config.sonarr.api_key:
            self._sonarr = SonarrClient(config.sonarr.url, config.sonarr.api_key)

    def start_batch_processor(self, shutdown: threading.Event) -> None:
        if not self._config.sync.batch_queue_enabled:
            return
        from .batch_processor import BatchProcessor

        BatchProcessor(self._config, self._state, self._radarr, self._sonarr, shutdown).start()

    def run(self) -> None:
        logger.info("Starting sync (dry_run=%s)", self._dry_run)

        if self._radarr:
            self._sync_movies()
        else:
            logger.info("Radarr disabled or not configured, skipping movies")

        if self._sonarr:
            self._sync_serials()
        else:
            logger.info("Sonarr disabled or not configured, skipping serials")

        logger.info("Sync complete")

    def _resolve_tag(self, client: RadarrClient | SonarrClient, tag_name: str) -> int | None:
        if not tag_name:
            return None
        try:
            return client.ensure_tag(tag_name)
        except Exception as e:
            logger.warning("Could not resolve tag '%s': %s — adding without tag", tag_name, e)
            return None

    # --- movies ---

    def _sync_movies(self) -> None:
        logger.info("--- Movies @ Radarr ---")
        movies = self._filmweb.get_movies()

        new_items = [m for m in movies if m.filmweb_id not in self._state.processed_films]
        if not new_items:
            logger.info("No new movies to process")
            return

        logger.info("%d new movie(s) to process", len(new_items))
        try:
            existing_tmdb_ids = self._radarr.get_existing_tmdb_ids()  # type: ignore[union-attr]
        except Exception as e:
            logger.error("Failed to fetch Radarr library: %s — skipping movies this sync", e)
            return

        # Phase 1: look up every item; collect the ones that need adding
        pending: list[tuple[FilmwebItem, dict]] = []
        for item in new_items:
            result = self._lookup_movie(item, existing_tmdb_ids)
            if result is not None:
                pending.append((item, result))

        if not pending:
            return

        # Phase 2: enqueue for background processing, or add immediately
        if self._config.sync.batch_queue_enabled:
            for item, result in pending:
                self._state.enqueue_film(item.filmweb_id, result)
            logger.info("Enqueued %d movie(s) for batch processing", len(pending))
        else:
            tag_id = self._resolve_tag(self._radarr, self._config.radarr.tag)  # type: ignore[arg-type]
            logger.info(
                "Adding %d movie(s) to Radarr (delay=%ds between each)",
                len(pending),
                self._add_delay,
            )
            for i, (item, result) in enumerate(pending):
                self._add_movie(item, result, tag_id)
                if i < len(pending) - 1:
                    time.sleep(self._add_delay)

    def _lookup_movie(self, item: FilmwebItem, existing_tmdb_ids: set[int]) -> dict | None:
        """Look up one movie. Returns the Radarr result if it needs adding, None otherwise."""
        try:
            result = self._radarr.lookup(item.search_titles, item.year)  # type: ignore[union-attr]
        except Exception as e:
            logger.warning("Radarr lookup failed for %s: %s — will retry next sync", item, e)
            return None

        if not result:
            logger.warning("No Radarr match for: %s — will retry next sync", item)
            return None

        tmdb_id: int = result.get("tmdbId", 0)
        matched_title: str = result.get("title", item.search_titles[0])

        if tmdb_id in existing_tmdb_ids:
            logger.info(
                "Already in Radarr: %s (tmdbId=%d)",
                matched_title,
                tmdb_id,
                extra={"status": "skip"},
            )
            self._state.mark_film_processed(item.filmweb_id)
            return None

        if self._dry_run:
            logger.info("[DRY RUN] Would add to Radarr: %s (tmdbId=%d)", matched_title, tmdb_id)
            self._state.mark_film_processed(item.filmweb_id)
            return None

        return result

    def _add_movie(self, item: FilmwebItem, result: dict, tag_id: int | None = None) -> None:
        matched_title: str = result.get("title", item.search_titles[0])
        tmdb_id: int = result.get("tmdbId", 0)
        try:
            self._radarr.add(  # type: ignore[union-attr]
                result,
                self._config.radarr.root_folder,
                self._config.radarr.quality_profile_id,
                tag_id=tag_id,
            )
            logger.info(
                "Added to Radarr: %s (tmdbId=%d)", matched_title, tmdb_id, extra={"status": "ok"}
            )
            self._state.mark_film_processed(item.filmweb_id)
        except Exception as e:
            logger.error("Failed to add %s to Radarr: %s — will retry next sync", matched_title, e)

    # --- serials ---

    def _sync_serials(self) -> None:
        logger.info("--- Serials @ Sonarr ---")
        serials = self._filmweb.get_serials()

        new_items = [s for s in serials if s.filmweb_id not in self._state.processed_serials]
        if not new_items:
            logger.info("No new serials to process")
            return

        logger.info("%d new serial(s) to process", len(new_items))
        try:
            existing_tvdb_ids = self._sonarr.get_existing_tvdb_ids()  # type: ignore[union-attr]
        except Exception as e:
            logger.error("Failed to fetch Sonarr library: %s — skipping serials this sync", e)
            return

        # Phase 1: look up every item; collect the ones that need adding
        pending: list[tuple[FilmwebItem, dict]] = []
        for item in new_items:
            result = self._lookup_serial(item, existing_tvdb_ids)
            if result is not None:
                pending.append((item, result))

        if not pending:
            return

        # Phase 2: enqueue for background processing, or add immediately
        if self._config.sync.batch_queue_enabled:
            for item, result in pending:
                self._state.enqueue_serial(item.filmweb_id, result)
            logger.info("Enqueued %d serial(s) for batch processing", len(pending))
        else:
            tag_id = self._resolve_tag(self._sonarr, self._config.sonarr.tag)  # type: ignore[arg-type]
            logger.info(
                "Adding %d serial(s) to Sonarr (delay=%ds between each)",
                len(pending),
                self._add_delay,
            )
            for i, (item, result) in enumerate(pending):
                self._add_serial(item, result, tag_id)
                if i < len(pending) - 1:
                    time.sleep(self._add_delay)

    def _lookup_serial(self, item: FilmwebItem, existing_tvdb_ids: set[int]) -> dict | None:
        """Look up one serial. Returns the Sonarr result if it needs adding, None otherwise."""
        try:
            result = self._sonarr.lookup(item.search_titles, item.year)  # type: ignore[union-attr]
        except Exception as e:
            logger.warning("Sonarr lookup failed for %s: %s — will retry next sync", item, e)
            return None

        if not result:
            logger.warning("No Sonarr match for: %s — will retry next sync", item)
            return None

        tvdb_id: int = result.get("tvdbId", 0)
        matched_title: str = result.get("title", item.search_titles[0])

        if tvdb_id in existing_tvdb_ids:
            logger.info(
                "Already in Sonarr: %s (tvdbId=%d)",
                matched_title,
                tvdb_id,
                extra={"status": "skip"},
            )
            self._state.mark_serial_processed(item.filmweb_id)
            return None

        if self._dry_run:
            logger.info("[DRY RUN] Would add to Sonarr: %s (tvdbId=%d)", matched_title, tvdb_id)
            self._state.mark_serial_processed(item.filmweb_id)
            return None

        return result

    def _add_serial(self, item: FilmwebItem, result: dict, tag_id: int | None = None) -> None:
        matched_title: str = result.get("title", item.search_titles[0])
        tvdb_id: int = result.get("tvdbId", 0)
        try:
            self._sonarr.add(  # type: ignore[union-attr]
                result,
                self._config.sonarr.root_folder,
                self._config.sonarr.quality_profile_id,
                language_profile_id=self._config.sonarr.language_profile_id,
                tag_id=tag_id,
            )
            logger.info(
                "Added to Sonarr: %s (tvdbId=%d)", matched_title, tvdb_id, extra={"status": "ok"}
            )
            self._state.mark_serial_processed(item.filmweb_id)
        except Exception as e:
            logger.error("Failed to add %s to Sonarr: %s — will retry next sync", matched_title, e)
