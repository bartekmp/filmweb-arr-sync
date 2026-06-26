import logging

from ..config import Config
from ..filmweb.models import FilmwebItem

logger = logging.getLogger(__name__)


class FilmwebWatchlist:
    """Hook for writing entries back to a user's Filmweb 'Want to see' list.

    Writing to Filmweb requires an authenticated session and an undocumented
    endpoint (there is no official public write API), so a real implementation
    is intentionally deferred. The bot calls :meth:`add` whenever it processes a
    Filmweb link; only when ``enabled`` is True does it surface the result to the
    user. A future authenticated implementation can subclass this and be wired in
    via :func:`build_watchlist` without touching the bot handler.
    """

    enabled: bool = False

    def add(self, item: FilmwebItem) -> bool:
        """Add *item* to the watchlist. Returns True on success."""
        return False


class NoopFilmwebWatchlist(FilmwebWatchlist):
    enabled = False

    def add(self, item: FilmwebItem) -> bool:
        logger.debug("Filmweb watchlist write-back not enabled; skipping %s", item)
        return False


def build_watchlist(config: Config) -> FilmwebWatchlist:
    """Return the watchlist write-back implementation for the current config.

    Currently always a no-op placeholder; this is the single seam where an
    authenticated implementation gets plugged in later.
    """
    return NoopFilmwebWatchlist()
