"""Тест парсера-шаблона на сохранённой HTML-фикстуре."""

from pathlib import Path

from src.parsers.example_site import ExampleSiteParser

FIXTURE = Path(__file__).parent / "fixtures" / "example_site_list.html"


def test_parse_extracts_listings():
    html_text = FIXTURE.read_text(encoding="utf-8")
    parser = ExampleSiteParser(client=None)
    listings = parser.parse(html_text)

    # Третий блок без заголовка пропускается.
    assert len(listings) == 2

    first = listings[0]
    assert first.id == "example_site:101"
    assert first.title == "Уютная комната в центре"
    assert first.url == "https://example.com/ad/101"
    assert first.price == "450 EUR"
    assert first.price_value == 450.0
    assert first.location == "Центр"


def test_parse_empty_html_returns_empty():
    parser = ExampleSiteParser(client=None)
    assert parser.parse("<html></html>") == []
