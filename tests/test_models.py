from filmweb_arr_sync.filmweb.models import FilmwebItem


def item(**kwargs) -> FilmwebItem:
    defaults = dict(
        filmweb_id=1,
        title="Polish Title",
        original_title="English Title",
        year=2023,
        item_type="film",
    )
    defaults.update(kwargs)
    return FilmwebItem(**defaults)


class TestSearchTitles:
    def test_original_title_is_first(self):
        assert item().search_titles[0] == "English Title"

    def test_title_is_fallback(self):
        assert item().search_titles == ["English Title", "Polish Title"]

    def test_deduplicates_when_both_titles_are_the_same(self):
        assert item(title="Same", original_title="Same").search_titles == ["Same"]

    def test_empty_original_title_returns_only_title(self):
        assert item(original_title="").search_titles == ["Polish Title"]

    def test_empty_title_returns_only_original_title(self):
        assert item(title="").search_titles == ["English Title"]


class TestStr:
    def test_uses_original_title_and_year(self):
        assert str(item(filmweb_id=42, year=2023)) == "English Title (2023) [fw:42]"

    def test_falls_back_to_title_when_original_is_empty(self):
        assert str(item(original_title="", filmweb_id=7)) == "Polish Title (2023) [fw:7]"
