from __future__ import annotations

import html as html_lib
import uuid
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable, Literal
from urllib.parse import urlsplit


GENERIC_SUMMARY_PHRASES = (
    "learn what's new",
    "learn what is new",
    "is here",
    "is out",
    "release date:",
)


@dataclass(frozen=True)
class EnrichmentProfile:
    name: str
    fetch_link_when: frozenset[str] = field(default_factory=frozenset)
    max_items: int = 6
    drop_phrases: tuple[str, ...] = ()
    compress_overloaded: bool = True


def enrichment_profile(
    name: str,
    *,
    fetch_link_when: tuple[str, ...] = (),
    max_items: int = 6,
    drop_phrases: tuple[str, ...] = (),
    compress_overloaded: bool = True,
) -> EnrichmentProfile:
    return EnrichmentProfile(
        name=name,
        fetch_link_when=frozenset(fetch_link_when),
        max_items=max_items,
        drop_phrases=drop_phrases,
        compress_overloaded=compress_overloaded,
    )


PROFILES = {
    "default": enrichment_profile("default"),
    "linked-release-notes": enrichment_profile(
        "linked-release-notes",
        fetch_link_when=("thin_summary", "summary_repeats_title", "generic_summary"),
        max_items=8,
    ),
    "compact-release-notes": enrichment_profile("compact-release-notes", max_items=8),
    "vscode-updates": enrichment_profile(
        "vscode-updates",
        fetch_link_when=("thin_summary", "summary_repeats_title", "generic_summary", "version_only_title"),
        max_items=8,
        drop_phrases=(
            "Edit",
            "Build",
            "Debug",
            "Extensions",
            "Follow us on",
            "Last updated",
            "Downloads:",
            "Release date:",
            "Rewatch VS Code Live",
            "You can still track our progress",
            "Happy Coding!",
        ),
    ),
    "minecraft-news": enrichment_profile(
        "minecraft-news",
        fetch_link_when=("thin_summary", "summary_repeats_title", "generic_summary"),
        max_items=8,
        drop_phrases=("Share this story", "Community Creations", "News"),
    ),
    "official-game-news": enrichment_profile(
        "official-game-news",
        max_items=8,
        drop_phrases=("Back to Top", "Buy now", "Cookie Settings", "Privacy Policy"),
    ),
    "raycast-changelog": enrichment_profile("raycast-changelog", max_items=7),
    "status-feed": enrichment_profile("status-feed", compress_overloaded=False),
}


URL_PROFILE_HINTS = {
    "code.visualstudio.com/feed.xml": "vscode-updates",
    "github.com/microsoft/vscode/releases.atom": "vscode-updates",
    "minecraft.net/en-us/feeds/community-content/rss": "minecraft-news",
    "www.python.org/downloads/feed.rss": "linked-release-notes",
    "docs.slack.dev/changelog/rss.xml": "linked-release-notes",
    "api.slack.com/changelog.rss": "linked-release-notes",
    "blog.jetbrains.com/idea/feed/": "linked-release-notes",
    "raycast.com/changelog/feed.xml": "raycast-changelog",
    "githubstatus.com/history.rss": "status-feed",
    "reachthefinals.com/patchnotes?format=rss": "official-game-news",
    "arcraiders.com/news": "official-game-news",
}


@dataclass(frozen=True)
class HtmlBlock:
    tag: str
    text: str


@dataclass(frozen=True)
class EnrichmentResult:
    title: str
    summary: str
    content: str
    quality_flags: list[str]
    profile: str
    media: tuple[CardMedia, ...] = ()


# Images and videos that a card shows, in post order. A post with more links to the source for the rest.
MAX_CARD_MEDIA = 12
VIDEO_SUFFIXES = (".mp4", ".webm", ".mov", ".m4v")
MediaKind = Literal["image", "gif", "video"]
# Characters of text that a card shows. The cut falls between whole blocks or whole list items.
EXCERPT_TEXT_BUDGET = 1500
# Kept with their formatting. Only `a` keeps an attribute (`href`). `tt` becomes `code`.
EXCERPT_KEEP_TAGS = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "b", "em", "i", "code", "tt", "kbd",
    "pre", "a", "blockquote", "br", "hr", "del", "s", "sub", "sup", "table", "thead", "tbody", "tr", "th", "td",
})
# Dropped with all of their content. Images go to the card picture instead, so the excerpt has none.
EXCERPT_DROP_TAGS = frozenset({
    "script", "style", "svg", "nav", "footer", "header", "details", "img", "picture", "video", "audio",
    "iframe", "form", "button", "template", "noscript", "object", "embed",
})
VOID_TAGS = frozenset({"br", "hr", "img", "wbr", "source", "input", "meta", "link", "area", "col", "embed", "param", "track"})
BLOCK_TAGS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "pre", "blockquote", "hr", "table"})
# Every other tag, such as div or span, is unwrapped: its content stays and the tag goes.


@dataclass
class _Element:
    tag: str
    href: str | None = None
    children: list[_Element | str] = field(default_factory=list)


@dataclass(frozen=True)
class Excerpt:
    html: str
    media: tuple[CardMedia, ...]


@dataclass(frozen=True)
class CardMedia:
    url: str
    kind: MediaKind


def _lasting_url(url: str) -> str | None:
    """`url`, or the lasting address of a signed GitHub attachment link. None for a link that is not http(s)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    if parts.netloc == "private-user-images.githubusercontent.com":
        # These links are signed and expire after 300 seconds. The attachment address redirects to a fresh link.
        name = parts.path.rsplit("/", 1)[-1].split(".", 1)[0]
        try:
            return f"https://github.com/user-attachments/assets/{uuid.UUID(name.partition('-')[2])}"
        except ValueError:
            return None
    return url.strip()


def _media_path(url: str) -> str:
    """The lower-case path of the file behind `url`. A camo address carries the original address in hex."""
    parts = urlsplit(url)
    if parts.netloc == "camo.githubusercontent.com":
        try:
            return urlsplit(bytes.fromhex(parts.path.rsplit("/", 1)[-1]).decode()).path.lower()
        except ValueError:
            return parts.path.lower()
    return parts.path.lower()


def card_media(tag: str, attrs: dict[str, str | None]) -> CardMedia | None:
    """The image or video that a tag shows, or None for icons, badges, emoji and other tags.

    Limit: a GitHub video attachment link without a file suffix counts as a plain link, because its type is
    only known after a request. Revisit if release notes with such videos show no video on the card.
    """
    if tag == "img":
        source = attrs.get("src") or ""
        if "badge" in source.lower() or "emoji" in (attrs.get("class") or ""):
            return None
        if any(size and size.isdigit() and int(size) < 64 for size in (attrs.get("width"), attrs.get("height"))):
            return None
    elif tag in {"video", "source"}:
        source = attrs.get("src") or ""
    elif tag == "a":
        source = attrs.get("href") or ""
        if not _media_path(source).endswith(VIDEO_SUFFIXES):
            return None
    else:
        return None
    url = _lasting_url(source)
    if url is None:
        return None
    path = _media_path(url)
    if path.endswith(".svg"):
        return None
    if tag != "img" or path.endswith(VIDEO_SUFFIXES):
        return CardMedia(url, "video")
    return CardMedia(url, "gif" if path.endswith(".gif") else "image")


class _ExcerptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Element("root")
        self.media: list[CardMedia] = []
        self._open: list[_Element] = [self.root]
        self._dropped: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.media) < MAX_CARD_MEDIA:
            found = card_media(tag, dict(attrs))
            if found and all(found.url != known.url for known in self.media):
                self.media.append(found)
        if self._dropped or tag in EXCERPT_DROP_TAGS:
            if tag not in VOID_TAGS:
                self._dropped.append(tag)
            return
        if tag not in EXCERPT_KEEP_TAGS:
            return
        href = dict(attrs).get("href") if tag == "a" else None
        element = _Element("code" if tag == "tt" else tag, href if href and urlsplit(href).scheme in {"http", "https"} else None)
        self._open[-1].children.append(element)
        if tag not in VOID_TAGS:
            self._open.append(element)

    def handle_endtag(self, tag: str) -> None:
        if self._dropped:
            if tag in self._dropped:
                del self._dropped[len(self._dropped) - 1 - self._dropped[::-1].index(tag):]
            return
        tag = "code" if tag == "tt" else tag
        for depth in range(len(self._open) - 1, 0, -1):
            if self._open[depth].tag == tag:
                del self._open[depth:]
                return

    def handle_data(self, data: str) -> None:
        if not self._dropped:
            self._open[-1].children.append(data)


def _node_text(node: _Element | str) -> str:
    if isinstance(node, str):
        return node
    return " ".join(_node_text(child) for child in node.children)


def _node_html(node: _Element | str) -> str:
    if isinstance(node, str):
        return html_lib.escape(node, quote=False)
    if node.tag in VOID_TAGS:
        return f"<{node.tag}>"
    href = f' href="{html_lib.escape(node.href)}"' if node.href else ""
    return f"<{node.tag}{href}>{''.join(_node_html(child) for child in node.children)}</{node.tag}>"


def _excerpt_units(root: _Element) -> list[_Element]:
    """The top-level blocks. Loose text and inline tags between blocks become one paragraph."""
    units: list[_Element] = []
    loose = _Element("p")
    for child in root.children:
        if isinstance(child, _Element) and child.tag in BLOCK_TAGS:
            if normalize_text(_node_text(loose)):
                units.append(loose)
            loose = _Element("p")
            units.append(child)
        else:
            loose.children.append(child)
    if normalize_text(_node_text(loose)):
        units.append(loose)
    return units


def _is_ignored_excerpt_block(tag: str, text: str, profile: EnrichmentProfile) -> bool:
    if tag.startswith("h") and tag != "hr":
        return "release notes" in text.lower() or is_simple_version_title(text)
    return is_ignored_release_note_line(tag, text, profile)


def html_excerpt(value: str, profile: EnrichmentProfile, budget: int = EXCERPT_TEXT_BUDGET) -> Excerpt:
    """The first blocks of an HTML body with their formatting, and the images and videos for the card."""
    parser = _ExcerptParser()
    parser.feed(value)
    parser.close()
    parts: list[str] = []
    used = 0
    cut = False
    for unit in _excerpt_units(parser.root):
        text = normalize_text(_node_text(unit))
        if (not text and unit.tag != "hr") or _is_ignored_excerpt_block(unit.tag, text, profile):
            continue
        if unit.tag in {"ul", "ol"}:
            kept: list[_Element | str] = []
            for item in unit.children:
                item_text = normalize_text(_node_text(item))
                if not isinstance(item, _Element) or item.tag != "li" or not item_text or _is_ignored_excerpt_block("li", item_text, profile):
                    continue
                # The first block always shows, even when it alone is over the budget.
                if (parts or kept) and used + len(item_text) > budget:
                    cut = True
                    break
                kept.append(item)
                used += len(item_text)
            if kept:
                parts.append(_node_html(_Element(unit.tag, children=kept)))
            if cut:
                break
            continue
        if parts and used + len(text) > budget:
            cut = True
            break
        parts.append(_node_html(unit))
        used += len(text)
    if cut:
        parts.append("<p>…</p>")
    return Excerpt(html="".join(parts), media=tuple(parser.media))


def is_html(value: str) -> bool:
    return "<" in value and ">" in value


class _TextBlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[HtmlBlock] = []
        self._skip_depth = 0
        self._current_tag: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "footer", "header", "svg"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            # A paragraph inside a list item belongs to the item, so the item keeps its bullet.
            if tag == "p" and self._current_tag == "li":
                return
            self._current_tag = tag
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer", "header", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if self._current_tag == tag:
            text = normalize_text("".join(self._current_text))
            if text:
                self.blocks.append(HtmlBlock(tag=tag, text=text))
            self._current_tag = None
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and self._current_tag is not None:
            self._current_text.append(data)


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def text_blocks(html: str) -> list[HtmlBlock]:
    parser = _TextBlockParser()
    parser.feed(html)
    return parser.blocks


def plain_text(value: str) -> str:
    if not is_html(value):
        return normalize_text(value)
    return normalize_text(" ".join(block.text for block in text_blocks(value)))


def is_simple_version_title(title: str) -> bool:
    normalized = title.strip().lower()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    if not normalized:
        return False
    return all(part.isdigit() for part in normalized.split(".")) and "." in normalized


def feed_label(feed_title: str) -> str | None:
    prefix = "Release notes from "
    if feed_title.startswith(prefix):
        return feed_title[len(prefix) :].strip() or None
    return feed_title.strip() or None


def is_ignored_release_note_line(tag: str, text: str, profile: EnrichmentProfile) -> bool:
    lowered = text.lower()
    if tag.startswith("h"):
        return True
    if is_url_only_line(text):
        return True
    if "full changelog" in lowered or "compare" in lowered:
        return True
    if lowered.startswith("released on "):
        return True
    if lowered.startswith(("follow us on", "last updated:", "downloads:", "release date:")):
        return True
    if lowered in {"happy coding!"} or lowered.startswith("you can still track our progress"):
        return True
    return any(phrase.lower() in lowered for phrase in profile.drop_phrases)


def is_url_only_line(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized.startswith(("http://", "https://")):
        return False
    return " " not in normalized


def first_url_line(html: str) -> str | None:
    for block in text_blocks(html):
        if is_url_only_line(block.text):
            return block.text
    for token in plain_text(html).split():
        if token.startswith(("http://", "https://")):
            return token.rstrip(".,)")
    return None


def first_meaningful_line(html: str, profile: EnrichmentProfile) -> str | None:
    for block in text_blocks(html):
        if not is_ignored_release_note_line(block.tag, block.text, profile):
            return block.text
    return None


def compact_blocks(html: str, profile: EnrichmentProfile) -> str:
    lines: list[str] = []
    content_items = 0
    for block in text_blocks(html):
        if block.tag.startswith("h"):
            lowered_heading = block.text.lower()
            if "release notes" not in lowered_heading and not is_simple_version_title(block.text):
                lines.append(f"**{block.text}**")
            continue
        if is_ignored_release_note_line(block.tag, block.text, profile):
            continue
        if block.tag == "li":
            lines.append(f"- {block.text}")
            content_items += 1
        else:
            lines.append(block.text)
            content_items += 1
        if content_items >= profile.max_items:
            break
    return "\n".join(lines)


def profile_for(feed_url: str, configured_name: str | None = None) -> EnrichmentProfile:
    if configured_name:
        return PROFILES.get(configured_name, PROFILES["default"])
    for needle, profile_name in URL_PROFILE_HINTS.items():
        if needle in feed_url:
            return PROFILES[profile_name]
    return PROFILES["default"]


def classify_quality(title: str, summary: str, content: str) -> list[str]:
    flags: list[str] = []
    summary_text = plain_text(summary)
    content_text = plain_text(content)
    title_text = plain_text(title)
    lowered_summary = summary_text.lower()

    if is_simple_version_title(title):
        flags.append("version_only_title")
    if not summary_text or len(summary_text) < 40:
        flags.append("thin_summary")
    if summary_text and title_text and lowered_summary == title_text.lower():
        flags.append("summary_repeats_title")
    if any(phrase in lowered_summary for phrase in GENERIC_SUMMARY_PHRASES):
        flags.append("generic_summary")
    if len(summary_text) > 1800 or len(content_text) > 1800:
        flags.append("overloaded_content")
    if "appeared first on" in lowered_summary or "the post " in lowered_summary:
        flags.append("html_boilerplate")

    return flags


def enrich_change(
    *,
    title: str,
    summary: str,
    content: str,
    url: str | None,
    feed_title: str,
    profile: EnrichmentProfile,
    fetch_link: Callable[[str], str | None] | None = None,
) -> EnrichmentResult:
    flags = classify_quality(title, summary, content)
    body = content or summary
    excerpt = html_excerpt(body, profile) if is_html(body) else None
    linked_body: str | None = None

    if url and fetch_link and profile.fetch_link_when.intersection(flags):
        linked_body = fetch_link(first_url_line(body) or url)
        if linked_body:
            flags.append("linked_content_fetched")
            body = linked_body

    display_title = title
    if "version_only_title" in flags:
        meaningful_line = first_meaningful_line(body, profile)
        if meaningful_line:
            label = feed_label(feed_title)
            display_title = f"{label} - {meaningful_line}" if label else meaningful_line

    display_summary = summary
    display_content = content
    if linked_body or "version_only_title" in flags or "overloaded_content" in flags or "html_boilerplate" in flags or "generic_summary" in flags or ("thin_summary" in flags and content):
        compact = compact_blocks(body, profile)
        if compact:
            display_summary = compact
            display_content = ""
    # The card shows the excerpt of the entry body with its formatting. A fetched linked page is a whole web page,
    # so its card keeps the text-only summary.
    if excerpt and excerpt.html and not linked_body:
        display_content = excerpt.html

    return EnrichmentResult(
        title=display_title,
        summary=display_summary,
        content=display_content,
        quality_flags=flags,
        profile=profile.name,
        media=excerpt.media if excerpt else (),
    )
