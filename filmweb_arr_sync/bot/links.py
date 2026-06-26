import re
from dataclasses import dataclass

# Filmweb title URLs look like:
#   https://www.filmweb.pl/film/Incepcja-2010-468741
#   https://www.filmweb.pl/serial/Wiedzmin-2019-668941
# The numeric Filmweb id is the last run of digits in the path segment.
_FILMWEB_RE = re.compile(
    r"filmweb\.pl/(?P<kind>film|serial)/[^/\s?#]*?(?P<id>\d+)(?=[/?#\s]|$)",
    re.IGNORECASE,
)

# IMDb title URLs look like:
#   https://www.imdb.com/title/tt1375666/
# The URL does not encode whether it is a movie or a series.
_IMDB_RE = re.compile(r"imdb\.com/title/(?P<id>tt\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedLink:
    source: str  # "filmweb" or "imdb"
    item_id: str  # Filmweb numeric id (as str) or IMDb "tt…" id
    media_type: str | None  # "film", "serial", or None when unknown (IMDb)

    @property
    def filmweb_id(self) -> int:
        return int(self.item_id)


def parse_link(text: str) -> ParsedLink | None:
    """Find the first valid Filmweb or IMDb title link in *text*.

    Returns None if the text contains no recognised link, so callers can
    reject anything that is not a supported URL.
    """
    if not text:
        return None

    match = _FILMWEB_RE.search(text)
    if match:
        kind = match.group("kind").lower()
        return ParsedLink(source="filmweb", item_id=match.group("id"), media_type=kind)

    match = _IMDB_RE.search(text)
    if match:
        return ParsedLink(source="imdb", item_id=match.group("id").lower(), media_type=None)

    return None
