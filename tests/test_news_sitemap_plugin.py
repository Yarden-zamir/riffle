import ssl
from datetime import datetime, timezone

import pytest
from test_network import Socket, Wire, response

from riffle.discovery import discover_sources
from riffle.models import Source, SourceCreate, TimeWindow
from riffle.network import PublicFetchError, validate_source_config
from riffle.plugins.news_sitemap import NewsSitemapPlugin, is_news_sitemap

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
WINDOW = TimeWindow(start=datetime(2026, 10, 18, tzinfo=timezone.utc), end=NOW)


def urlset(*entries: str) -> bytes:
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9' xmlns:news='http://www.google.com/schemas/sitemap-news/0.9'>"
        + "".join(entries)
        + "</urlset>"
    ).encode()


def entry(path: str, title: str, published: str, keywords: str = "") -> str:
    return (
        f"<url><loc>http://news.example{path}</loc><news:news>"
        "<news:publication><news:name>Example News</news:name><news:language>en</news:language></news:publication>"
        f"<news:publication_date>{published}</news:publication_date><news:title>{title}</news:title>"
        f"<news:keywords>{keywords}</news:keywords></news:news></url>"
    )


def index(*locations: str) -> bytes:
    children = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locations)
    return f"<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>{children}</sitemapindex>".encode()


def source(**config: object) -> Source:
    return Source(id=1, name="News", plugin="news-sitemap", config={"url": "http://news.example/news.xml", **config},
                  created_at=NOW, updated_at=NOW)


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    def wrap(context: ssl.SSLContext, sock: Socket, *, server_hostname: str) -> Socket:
        return sock

    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap)
    return Wire(monkeypatch)


def test_fetch_keeps_window_and_filters_newest_first(wire: Wire) -> None:
    wire.responses.append(response(urlset(
        entry("/tech/agents-1", "AI agents misbehave at a bank", "2026-10-24T09:30:00.120Z"),
        entry("/sport/match", "Late goal wins the derby", "2026-10-24T10:00:00Z"),
        entry("/tech/old", "AI agent story from last month", "2026-09-30T08:00:00Z"),
        entry("/tech/agents-2", "Regulators study chatbots", "2026-10-23", keywords="AI agent, regulation"),
        entry("/tech/agents-1", "AI agents misbehave at a bank", "2026-10-24T09:30:00.120Z"),
        entry("/tech/sponsored", "Sponsored: AI agents for you", "2026-10-24T11:00:00+02:00"),
    )))

    changes = NewsSitemapPlugin().fetch(source(include_any=["ai agent"], exclude_any="sponsored"), WINDOW)

    assert [change.url for change in changes] == ["http://news.example/tech/agents-1", "http://news.example/tech/agents-2"]
    assert changes[0].title == "AI agents misbehave at a bank"
    assert changes[0].published_at == datetime(2026, 10, 24, 9, 30, 0, 120000, tzinfo=timezone.utc)
    assert changes[0].external_id == changes[0].url
    assert changes[0].summary == ""
    assert changes[1].published_at == datetime(2026, 10, 23, tzinfo=timezone.utc)
    assert changes[1].metadata == {"feed_url": "http://news.example/news.xml", "publication": "Example News",
                                   "keywords": "AI agent, regulation"}


def test_long_urls_get_a_bounded_external_id(wire: Wire) -> None:
    path = "/tech/" + "a" * 900
    wire.responses.append(response(urlset(entry(path, "Long link", "2026-10-24T10:00:00Z"))))

    [change] = NewsSitemapPlugin().fetch(source(), WINDOW)

    assert change.url == f"http://news.example{path}"
    assert change.external_id is not None and change.external_id.startswith("sha256:") and len(change.external_id) <= 500


def test_entries_without_title_date_or_web_link_are_skipped(wire: Wire) -> None:
    wire.responses.append(response(urlset(
        entry("/ok", "Kept", "2026-10-24T10:00:00Z"),
        entry("/no-title", "", "2026-10-24T10:00:00Z"),
        entry("/bad-date", "Bad date", "yesterday"),
        "<url><loc>http://news.example/plain</loc></url>",
        entry("/ok", "Kept", "2026-10-24T10:00:00Z").replace("http://news.example", "javascript:alert(1)//"),
    )))

    assert [change.title for change in NewsSitemapPlugin().fetch(source(), WINDOW)] == ["Kept"]


def test_index_reads_children_until_a_page_is_older_than_the_window(wire: Wire) -> None:
    wire.responses.extend([
        response(index("/news.xml?page=1", "http://news.example/news.xml?page=2", "/news.xml?page=3", "/news.xml?page=4", "/news.xml?page=5")),
        # An updated old story on the first page does not stop the reading, and neither does an empty page.
        response(urlset(entry("/a", "First page", "2026-10-24T10:00:00Z"), entry("/updated", "Updated story", "2026-09-01T10:00:00Z"))),
        response(urlset("<url><loc>http://news.example/plain</loc></url>")),
        response(urlset(entry("/b", "Third page", "2026-10-20T10:00:00Z"))),
        response(urlset(entry("/c", "Fourth page, all older", "2026-10-10T10:00:00Z"))),
    ])

    changes = NewsSitemapPlugin().fetch(source(url="http://news.example/index.xml"), WINDOW)

    assert [change.title for change in changes] == ["First page", "Third page"]
    assert len(wire.sockets) == 5
    assert b"GET /news.xml?page=4 HTTP/1.1" in wire.sockets[4].sent
    assert not wire.responses


@pytest.mark.parametrize("body", [
    b"<?xml version='1.0'?><!DOCTYPE urlset [<!ENTITY a 'aaaa'>]><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'/>",
    # UTF-16 hides the declaration from a byte search.
    "<?xml version='1.0' encoding='UTF-16'?><!DOCTYPE urlset [<!ENTITY a 'aaaa'>]><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>&a;</urlset>".encode("utf-16"),
    b"<rss version='2.0'><channel><title>Feed</title></channel></rss>",
    b"<html><title>Page</title>",
])
def test_documents_that_are_not_plain_sitemaps_fail(wire: Wire, body: bytes) -> None:
    wire.responses.append(response(body))
    with pytest.raises(PublicFetchError):
        NewsSitemapPlugin().fetch(source(), WINDOW)


def test_index_child_that_is_not_a_sitemap_fails(wire: Wire) -> None:
    wire.responses.extend([response(index("/news.xml?page=1", "/news.xml?page=2")),
                           response(b"<rss version='2.0'><channel><title>Feed</title></channel></rss>")])
    with pytest.raises(PublicFetchError, match="not a sitemap"):
        NewsSitemapPlugin().fetch(source(url="http://news.example/index.xml"), WINDOW)


def test_empty_urlset_is_a_valid_empty_source(wire: Wire) -> None:
    wire.responses.append(response(urlset()))
    assert NewsSitemapPlugin().fetch(source(), WINDOW) == []


def test_config_accepts_filters_and_rejects_enrichment_and_html_options() -> None:
    def create(**config: object) -> SourceCreate:
        return SourceCreate(name="News", plugin="news-sitemap", config={"url": "https://news.example/news.xml", **config})

    validate_source_config(create(include_any=["ai"], exclude_any="sport", user_agent="riffle-test", profile="dev"))
    for extra in ({"enrichment_profile": "release-notes"}, {"article_path_prefix": "/news/"}, {"limit": 5}):
        with pytest.raises(PublicFetchError):
            validate_source_config(create(**extra))


def test_is_news_sitemap_needs_news_entries_or_an_index() -> None:
    assert is_news_sitemap(urlset(entry("/a", "Title", "2026-10-24")))
    assert is_news_sitemap(index("http://news.example/news.xml"))
    assert not is_news_sitemap(urlset("<url><loc>http://news.example/plain</loc></url>"))
    assert not is_news_sitemap(b"<rss version='2.0'/>")


def test_discovery_offers_a_pasted_news_sitemap(wire: Wire) -> None:
    wire.responses.append(response(urlset(entry("/a", "Title", "2026-10-24"))))

    sources = discover_sources("https://www.news.example/news-sitemap.xml")

    assert [(s.plugin, s.name, s.config) for s in sources] == [
        ("news-sitemap", "news.example news sitemap", {"url": "https://www.news.example/news-sitemap.xml"})
    ]
    assert len(wire.sockets) == 1


ROBOTS = b"""User-agent: *
Disallow: /private
Sitemap: https://news.example/sitemap-index.xml
SITEMAP: https://news.example/news-sitemap-index.xml
sitemap: /news/sitemap.xml
Sitemap: https://news.example/news-sitemap-index.xml
Sitemap: http://127.0.0.1/news.xml
"""


@pytest.mark.parametrize("page", [
    response(b"denied", status=401),
    response(b"<html><head><title>No feed links</title></head></html>"),
])
def test_discovery_reads_robots_news_sitemaps_for_refusals_and_pages_without_feeds(wire: Wire, page: bytes) -> None:
    wire.responses.extend([page, response(ROBOTS)])

    sources = discover_sources("https://news.example/technology/")

    assert [s.config["url"] for s in sources] == [
        "https://news.example/news-sitemap-index.xml",
        "https://news.example/news/sitemap.xml",
    ]
    assert all(s.plugin == "news-sitemap" and s.name == "news.example news sitemap" for s in sources)
    assert b"GET /robots.txt HTTP/1.1" in wire.sockets[1].sent


def test_refusal_without_news_sitemaps_stays_a_fetch_error(wire: Wire) -> None:
    wire.responses.extend([response(b"denied", status=403), response(b"Sitemap: https://news.example/sitemap.xml")])
    with pytest.raises(PublicFetchError, match="403"):
        discover_sources("https://news.example/technology/")


def test_github_errors_never_read_robots(wire: Wire) -> None:
    wire.responses.append(response(b"missing", status=404))
    with pytest.raises(PublicFetchError, match="404"):
        discover_sources("Other/Repo")
    assert len(wire.sockets) == 1
