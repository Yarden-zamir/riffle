"""Contract: a card shows the start of a long post with its formatting, cut between whole blocks, plus its first image."""

from html.parser import HTMLParser

from riffle.enrichment import EXCERPT_TEXT_BUDGET, enrich_change, enrichment_profile

PROFILE = enrichment_profile("compact", max_items=8)


class Items(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[str] = []
        self.tags: set[str] = set()
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag)
        if tag == "li":
            self.items.append("")
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "li":
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._depth:
            self.items[-1] += data


def release(items: int) -> str:
    notes = "".join(f"<li><p><strong>Change {n}</strong> (<a href=\"https://example.com/pull/{n}\">#{n}</a>): {'word ' * 30}</p></li>" for n in range(items))
    return f"<p>Daily release.</p><h2>Fork changes</h2><ul>{notes}</ul><h2>Upstream changes</h2><ul>{notes}</ul>"


def enrich(body: str):
    return enrich_change(title="T3 Code Fork 2026-10-25", summary="", content=body, url="https://example.com/release",
                         feed_title="Release notes from t3code", profile=PROFILE)


def test_long_release_notes_keep_their_format_and_cut_at_whole_items() -> None:
    enriched = enrich(release(60))

    parsed = Items()
    parsed.feed(enriched.content)
    assert {"h2", "ul", "li", "strong", "a"} <= parsed.tags
    assert 1 < len(parsed.items) < 60
    # Every kept item is whole.
    assert all(item.endswith("word ") or item.rstrip().endswith("word") for item in parsed.items)
    assert sum(len(item) for item in parsed.items) <= EXCERPT_TEXT_BUDGET
    assert enriched.content.endswith("<p>…</p>")


def test_short_posts_show_whole_and_drop_details_and_unsafe_markup() -> None:
    body = ("<p>Intro <script>alert(1)</script><a href=\"javascript:alert(1)\" onclick=\"x()\">link</a></p>"
            "<details><summary>Screenshots</summary><p>hidden text</p></details><ul><li>One</li></ul>")

    content = enrich(body).content

    assert content == "<p>Intro <a>link</a></p><ul><li>One</li></ul>"


def test_card_media_lists_images_gifs_and_videos_in_post_order_with_lasting_addresses() -> None:
    signed = ("https://private-user-images.githubusercontent.com/8178413/683589296-4651da5d-5013-45cf-8999-2eed4b6be37b.png"
              "?jwt=expires-in-300-seconds")
    gif = "https://camo.githubusercontent.com/digest/" + "https://files.example.org/search.gif".encode().hex()
    body = ("<p><img src=\"https://img.shields.io/badge/build-passing-green.svg\"><img class=\"emoji\" src=\"https://example.com/e.png\"></p>"
            f"<details><summary>Screenshots</summary><img src=\"{signed}\"><img src=\"{signed}\"></details>"
            f"<p>Text <img src=\"{gif}\"> <a href=\"https://example.com/demo.mp4\">demo</a></p>")

    enriched = enrich(body)

    assert [(item.url, item.kind) for item in enriched.media] == [
        ("https://github.com/user-attachments/assets/4651da5d-5013-45cf-8999-2eed4b6be37b", "image"),
        (gif, "gif"),
        ("https://example.com/demo.mp4", "video"),
    ]
    assert "<img" not in enriched.content
