from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from riffle import store
from riffle.api import create_app
from riffle.models import SharedProfile, SharedSource


class Head(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.title = ""
        self.in_title = False
        self.tags: dict[str, str] = {}
        self.elements: list[str] = []
        self.feed(html.split("</head>")[0])

    def handle_starttag(self, tag, attrs):
        self.elements.append(tag)
        self.in_title = tag == "title"
        values = dict(attrs)
        if tag == "meta":
            key = values.get("property", values.get("name"))
            if key == "description" or (key and key.startswith(("og:", "twitter:"))):
                assert key not in self.tags, f"duplicate metadata: {key}"
                self.tags[key] = values["content"]

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


@pytest.fixture
def page_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("KITSHN_ENVIRONMENT", raising=False)
    # The real Vite source head, without a frontend build, database, lifespan, or network.
    index = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
    (tmp_path / "index.html").write_text(index.read_text(encoding="utf-8"), encoding="utf-8")
    client = TestClient(create_app(frontend_dist=tmp_path))
    yield client
    client.close()


@pytest.mark.parametrize("count", [0, 1, 44])
@pytest.mark.parametrize("login", ["Yarden-zamir", None])
def test_share_head_is_present_without_javascript(page_client, monkeypatch, count, login):
    shared = SharedProfile(
        name="dev", shared_by=login,
        sources=[SharedSource(name="Public source", plugin="rss-atom", config={}) for _ in range(count)],
    )
    calls = []

    def public_profile(token, keys):
        calls.append(token)
        assert "url" in keys["rss-atom"]
        return shared

    monkeypatch.setattr(store, "get_shared_profile", public_profile)
    response = page_client.get("/share/public-token")  # no cookies, identity, or owner headers
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "private, no-store"
    head = Head(response.text)
    byline = f"{login}'s " if login else ""
    title = f"{byline}dev desk on Riffle"
    description = f"{count} {'source' if count == 1 else 'sources'}. Import them into your own Riffle feed."
    assert head.title == head.tags["og:title"] == head.tags["twitter:title"] == title
    assert head.tags["description"] == head.tags["og:description"] == head.tags["twitter:description"] == description
    assert head.tags["og:type"] == "website"
    assert head.tags["og:site_name"] == "Riffle"
    assert head.tags["twitter:card"] == "summary"
    assert head.elements.count("title") == 1
    assert calls == ["public-token"]
    assert "Public source" not in response.text, "metadata needs only the public source count"
    assert '<div id="root"></div>' in response.text


def test_share_head_escapes_every_dynamic_value(page_client, monkeypatch):
    attack = '\'"><script>alert("x")</script>&'
    shared = SharedProfile(name=attack, shared_by=attack, sources=[])
    monkeypatch.setattr(store, "get_shared_profile", lambda *_: shared)
    response = page_client.get("/share/public-token")
    head = Head(response.text)
    expected = f"{attack}'s {attack} desk on Riffle"
    assert head.title == head.tags["og:title"] == head.tags["twitter:title"] == expected
    assert "script" not in head.elements
    assert attack not in response.text
    assert "&quot;" in response.text and "&#x27;" in response.text
    assert "&lt;script&gt;" in response.text and "&amp;" in response.text


def test_unknown_share_uses_generic_tags_and_keeps_not_found_behavior(page_client, monkeypatch):
    def missing(*_):
        raise KeyError("share not found")

    monkeypatch.setattr(store, "get_shared_profile", missing)
    response = page_client.get("/share/unknown-token")
    # Preserve the existing SPA response; the API still reports 404 to the page.
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    head = Head(response.text)
    assert head.title == head.tags["og:title"] == head.tags["twitter:title"] == "Riffle"
    assert head.tags["description"] == head.tags["og:description"] == head.tags["twitter:description"] == "Follow your sources in one feed with Riffle."
    assert head.tags["twitter:card"] == "summary"
    assert "unknown-token" not in response.text
    assert '<div id="root"></div>' in response.text
    assert page_client.get("/shares/unknown-token").status_code == 404
