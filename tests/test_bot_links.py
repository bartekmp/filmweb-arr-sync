import pytest

from filmweb_arr_sync.bot.links import parse_link


class TestFilmwebLinks:
    def test_parses_film_url(self):
        parsed = parse_link("https://www.filmweb.pl/film/Incepcja-2010-468741")
        assert parsed is not None
        assert parsed.source == "filmweb"
        assert parsed.media_type == "film"
        assert parsed.item_id == "468741"
        assert parsed.filmweb_id == 468741

    def test_parses_serial_url(self):
        parsed = parse_link("https://www.filmweb.pl/serial/Wiedzmin-2019-668941")
        assert parsed.media_type == "serial"
        assert parsed.filmweb_id == 668941

    def test_takes_last_number_as_id_not_year(self):
        parsed = parse_link("https://www.filmweb.pl/film/Blade.Runner.2049-2017-771764")
        assert parsed.filmweb_id == 771764

    def test_parses_url_with_trailing_path(self):
        parsed = parse_link("https://www.filmweb.pl/film/Incepcja-2010-468741/discussion")
        assert parsed.filmweb_id == 468741

    def test_parses_url_with_query_and_fragment(self):
        parsed = parse_link("https://www.filmweb.pl/film/Incepcja-2010-468741?ref=x#top")
        assert parsed.filmweb_id == 468741

    def test_parses_url_embedded_in_text(self):
        parsed = parse_link("please add https://www.filmweb.pl/serial/Wiedzmin-2019-668941 thanks")
        assert parsed.source == "filmweb"
        assert parsed.filmweb_id == 668941

    def test_parses_without_scheme(self):
        parsed = parse_link("www.filmweb.pl/film/Incepcja-2010-468741")
        assert parsed is not None
        assert parsed.filmweb_id == 468741


class TestImdbLinks:
    def test_parses_title_url(self):
        parsed = parse_link("https://www.imdb.com/title/tt1375666/")
        assert parsed is not None
        assert parsed.source == "imdb"
        assert parsed.media_type is None
        assert parsed.item_id == "tt1375666"

    def test_parses_without_www(self):
        parsed = parse_link("https://imdb.com/title/tt0903747")
        assert parsed.item_id == "tt0903747"

    def test_parses_mobile_url(self):
        parsed = parse_link("https://m.imdb.com/title/tt0903747/")
        assert parsed.item_id == "tt0903747"

    def test_lowercases_id(self):
        parsed = parse_link("https://www.imdb.com/title/TT1375666/")
        assert parsed.item_id == "tt1375666"


class TestRejectsInvalid:
    @pytest.mark.parametrize(
        "text",
        [
            "",
            "hello world",
            "https://www.google.com",
            "https://www.filmweb.pl/user/someone",
            "https://www.imdb.com/name/nm0000138",
            "tt1375666",
        ],
    )
    def test_returns_none(self, text):
        assert parse_link(text) is None
