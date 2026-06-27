import logging

from .. import health
from ..arr.radarr import RadarrClient
from ..arr.sonarr import SonarrClient
from ..config import Config
from ..filmweb.client import FilmwebClient
from ..filmweb.models import FilmwebItem
from ..state import State
from .links import ParsedLink, parse_link
from .watchlist import FilmwebWatchlist

logger = logging.getLogger(__name__)

_HELP = (
    "🎬 Filmweb → Radarr/Sonarr bot\n\n"
    "Send me a Filmweb or IMDb link to a movie or TV series and I'll add it to "
    "Radarr/Sonarr.\n\n"
    "Examples:\n"
    "• https://www.filmweb.pl/film/Incepcja-2010-468741\n"
    "• https://www.imdb.com/title/tt1375666/\n\n"
    "Commands:\n"
    "/last_sync — when the watchlist sync last ran\n"
    "/stats — how many items have been processed\n"
    "/help — show this message"
)


class BotHandler:
    """Turns an incoming message into a reply, performing Radarr/Sonarr adds.

    The handler is transport-agnostic: it takes message text and returns reply
    text. The Telegram plumbing lives in :mod:`runner`/:mod:`telegram`.
    """

    def __init__(
        self,
        config: Config,
        state: State,
        radarr: RadarrClient | None,
        sonarr: SonarrClient | None,
        filmweb: FilmwebClient,
        watchlist: FilmwebWatchlist,
    ) -> None:
        self._config = config
        self._state = state
        self._radarr = radarr
        self._sonarr = sonarr
        self._filmweb = filmweb
        self._watchlist = watchlist

    # --- entry point ---

    def handle_message(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return "🤔 Send me a Filmweb or IMDb link, or /help."
        if text.startswith("/"):
            return self._handle_command(text)
        return self._handle_link(text)

    # --- commands ---

    def _handle_command(self, text: str) -> str:
        # Telegram command names use letters/digits/underscores; "/cmd@botname"
        # is the form used in group chats.
        cmd = text.split()[0].lstrip("/").split("@")[0].lower()
        if cmd in ("start", "help"):
            return _HELP
        if cmd in ("last_sync", "lastsync"):
            return self._last_sync()
        if cmd in ("stats", "status"):
            return self._stats()
        return f"❓ Unknown command /{cmd}. Try /help."

    def _last_sync(self) -> str:
        timestamp = health.get_last_sync()
        if not timestamp:
            return "🕓 No scheduled sync has completed yet."
        return f"🕓 Last sync ran at: {timestamp}"

    def _stats(self) -> str:
        lines = [
            "📊 Stats",
            f"Movies processed: {len(self._state.processed_films)}",
            f"Series processed: {len(self._state.processed_serials)}",
        ]
        pending = len(self._state.pending_films) + len(self._state.pending_serials)
        if pending:
            lines.append(f"Pending in batch queue: {pending}")
        return "\n".join(lines)

    # --- links ---

    def _handle_link(self, text: str) -> str:
        parsed = parse_link(text)
        if parsed is None:
            return (
                "❌ That's not a valid Filmweb or IMDb link.\n"
                "Send something like https://www.filmweb.pl/film/… or "
                "https://www.imdb.com/title/tt…"
            )
        if parsed.source == "filmweb":
            return self._add_from_filmweb(parsed)
        return self._add_from_imdb(parsed)

    def _add_from_filmweb(self, parsed: ParsedLink) -> str:
        item = self._filmweb.get_item(parsed.filmweb_id, parsed.media_type or "film")
        if item is None:
            return "❌ Couldn't fetch details for that Filmweb title — try again later."

        if item.item_type == "serial":
            if self._sonarr is None:
                return "❌ Sonarr isn't enabled — can't add series."
            result = self._safe_lookup(self._sonarr, item)
            reply = self._add_serial_from_lookup(result, item.filmweb_id)
        else:
            if self._radarr is None:
                return "❌ Radarr isn't enabled — can't add movies."
            result = self._safe_lookup(self._radarr, item)
            reply = self._add_movie_from_lookup(result, item.filmweb_id)

        return reply + self._watchlist_note(item)

    def _add_from_imdb(self, parsed: ParsedLink) -> str:
        imdb_id = parsed.item_id

        # IMDb URLs don't say whether the title is a movie or a series, so try
        # Radarr (movies) first, then Sonarr (series).
        if self._radarr is not None:
            result = self._safe_lookup_imdb(self._radarr, imdb_id)
            if result:
                return self._add_movie_from_lookup(result, None)

        if self._sonarr is not None:
            result = self._safe_lookup_imdb(self._sonarr, imdb_id)
            if result:
                return self._add_serial_from_lookup(result, None)

        if self._radarr is None and self._sonarr is None:
            return "❌ Neither Radarr nor Sonarr is configured."
        return f"🔍 No movie or series match found for {imdb_id}."

    # --- shared add helpers ---

    def _add_movie_from_lookup(self, result: dict | None, filmweb_id: int | None) -> str:
        if not result:
            return "🔍 No Radarr match found for that title."
        assert self._radarr is not None
        title = result.get("title", "?")
        year = result.get("year", "")
        tmdb_id: int = result.get("tmdbId", 0)

        try:
            existing = self._radarr.get_existing_tmdb_ids()
        except Exception as e:
            logger.warning("Could not fetch Radarr library: %s", e)
            existing = set()

        if tmdb_id in existing:
            if filmweb_id is not None:
                self._state.mark_film_processed(filmweb_id)
            return f"ℹ️ Already in Radarr: {title} ({year})"

        tag_id = self._resolve_tag(self._radarr, self._config.radarr.tag)
        try:
            self._radarr.add(
                result,
                self._config.radarr.root_folder,
                self._config.radarr.quality_profile_id,
                tag_id=tag_id,
                search=self._config.telegram.search_on_add,
            )
        except Exception as e:
            logger.error("Failed to add %s to Radarr: %s", title, e)
            return f"❌ Failed to add {title} to Radarr."

        if filmweb_id is not None:
            self._state.mark_film_processed(filmweb_id)
        return f"✅ Added to Radarr: {title} ({year})"

    def _add_serial_from_lookup(self, result: dict | None, filmweb_id: int | None) -> str:
        if not result:
            return "🔍 No Sonarr match found for that title."
        assert self._sonarr is not None
        title = result.get("title", "?")
        year = result.get("year", "")
        tvdb_id: int = result.get("tvdbId", 0)

        try:
            existing = self._sonarr.get_existing_tvdb_ids()
        except Exception as e:
            logger.warning("Could not fetch Sonarr library: %s", e)
            existing = set()

        if tvdb_id in existing:
            if filmweb_id is not None:
                self._state.mark_serial_processed(filmweb_id)
            return f"ℹ️ Already in Sonarr: {title} ({year})"

        tag_id = self._resolve_tag(self._sonarr, self._config.sonarr.tag)
        try:
            self._sonarr.add(
                result,
                self._config.sonarr.root_folder,
                self._config.sonarr.quality_profile_id,
                language_profile_id=self._config.sonarr.language_profile_id,
                tag_id=tag_id,
                search=self._config.telegram.search_on_add,
            )
        except Exception as e:
            logger.error("Failed to add %s to Sonarr: %s", title, e)
            return f"❌ Failed to add {title} to Sonarr."

        if filmweb_id is not None:
            self._state.mark_serial_processed(filmweb_id)
        return f"✅ Added to Sonarr: {title} ({year})"

    def _safe_lookup(self, client: RadarrClient | SonarrClient, item: FilmwebItem) -> dict | None:
        try:
            return client.lookup(item.search_titles, item.year)
        except Exception as e:
            logger.warning("Lookup failed for %s: %s", item, e)
            return None

    def _safe_lookup_imdb(self, client: RadarrClient | SonarrClient, imdb_id: str) -> dict | None:
        try:
            return client.lookup_by_imdb(imdb_id)
        except Exception as e:
            logger.warning("IMDb lookup failed for %s: %s", imdb_id, e)
            return None

    def _resolve_tag(self, client: RadarrClient | SonarrClient, tag_name: str) -> int | None:
        if not tag_name:
            return None
        try:
            return client.ensure_tag(tag_name)
        except Exception as e:
            logger.warning("Could not resolve tag '%s': %s — adding without tag", tag_name, e)
            return None

    def _watchlist_note(self, item: FilmwebItem) -> str:
        """Optionally write the item back to the Filmweb watchlist.

        The default implementation is a no-op (see :mod:`watchlist`), so nothing
        is appended unless an authenticated write-back is wired in.
        """
        if not self._watchlist.enabled:
            return ""
        if self._watchlist.add(item):
            return "\n📌 Added to your Filmweb watchlist."
        return "\n⚠️ Couldn't add to your Filmweb watchlist."
