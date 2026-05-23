from dataclasses import dataclass


@dataclass
class FilmwebItem:
    filmweb_id: int
    title: str
    original_title: str
    year: int
    item_type: str  # "film" or "serial"

    @property
    def search_titles(self) -> list[str]:
        """Titles to try in order. originalTitle first (better for TMDb/TVDb),
        with title as fallback for cases like Japanese films where the romanized
        originalTitle doesn't match the English entry in the database."""
        seen: set[str] = set()
        titles: list[str] = []
        for t in (self.original_title, self.title):
            if t and t not in seen:
                seen.add(t)
                titles.append(t)
        return titles

    def __str__(self) -> str:
        return f"{self.search_titles[0]} ({self.year}) [fw:{self.filmweb_id}]"
