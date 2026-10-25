"""Read Google News sitemaps. Some news sites, such as Reuters, publish one for search engines but no RSS or Atom feed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any
from xml.etree import ElementTree

from riffle.models import ChangeInput, Source, TimeWindow
from riffle.network import MAX_ENTRIES, PublicFetcher, PublicFetchError, validate_public_url, validate_source_config
from riffle.plugin import PluginConfigError
from riffle.plugins.rss_atom import _matches_filters

SITEMAP = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
NEWS = "{http://www.google.com/schemas/sitemap-news/0.9}"
# An index lists its newest sitemap first. Reading 8 children leaves room in the 12-request budget for redirects.
# Revisit when a source publishes more than 8 sitemap pages of news inside one refresh window.
MAX_CHILD_SITEMAPS = 8


@dataclass(frozen=True)
class NewsEntry:
    url: str
    title: str
    published_at: datetime
    publication: str
    keywords: str


def _string_list_config(config: dict[str, Any], key: str) -> list[str]:
    value = config.get(key, [])
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise PluginConfigError(f"news-sitemap config {key!r} must be a string or list of strings")


def _parse_time(value: str) -> datetime | None:
    """W3C datetime: a date, or a date and time with a zone. A value without a zone counts as UTC."""
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if len(value.strip()) == 10:
        parsed = datetime.combine(parsed.date(), time(), tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _root(content: bytes) -> ElementTree.Element:
    # Sitemaps never declare a document type. Refusing one keeps entity expansion out of the parser.
    if b"<!DOCTYPE" in content[:4096].upper() or b"<!ENTITY" in content.upper():
        raise PublicFetchError("Sitemap declares a document type")
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError:
        raise PublicFetchError("Sitemap could not be parsed") from None


def _text(element: ElementTree.Element, path: str) -> str:
    found = element.find(path)
    return " ".join((found.text or "").split()) if found is not None else ""


def child_sitemaps(root: ElementTree.Element) -> list[str]:
    """The child sitemap URLs of a sitemap index, in document order. Any other document has none."""
    if root.tag != f"{SITEMAP}sitemapindex":
        return []
    return [loc for item in root.iter(f"{SITEMAP}sitemap") if (loc := _text(item, f"{SITEMAP}loc"))]


def news_entries(root: ElementTree.Element) -> list[NewsEntry]:
    """The news entries of a sitemap. Entries without a URL, a news title or a valid publication date are skipped."""
    if root.tag != f"{SITEMAP}urlset":
        return []
    entries = []
    for item in root.iter(f"{SITEMAP}url"):
        news = item.find(f"{NEWS}news")
        loc = _text(item, f"{SITEMAP}loc")
        # Change URLs hold at most 2000 characters, and only web links render as links.
        if news is None or not loc.startswith(("https://", "http://")) or len(loc) > 2000:
            continue
        title = _text(news, f"{NEWS}title")
        published_at = _parse_time(_text(news, f"{NEWS}publication_date"))
        if not title or published_at is None:
            continue
        entries.append(NewsEntry(
            url=loc,
            title=title,
            published_at=published_at,
            publication=_text(news, f"{NEWS}publication/{NEWS}name"),
            keywords=_text(news, f"{NEWS}keywords"),
        ))
    return entries


def is_news_sitemap(content: bytes) -> bool:
    """True for a urlset with news entries, or for a sitemap index. Discovery uses this to propose the plugin."""
    try:
        root = _root(content)
    except PublicFetchError:
        return False
    return bool(child_sitemaps(root)) or bool(news_entries(root))


class NewsSitemapPlugin:
    key = "news-sitemap"
    name = "News sitemap"
    description = "Fetches article titles and dates from a Google News sitemap or sitemap index."
    config_schema: dict[str, object] = {
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string", "format": "uri"},
            "user_agent": {"type": "string"},
            "profile": {"type": "string"},
            "include_any": {
                "description": "Only keep entries containing at least one of these case-insensitive terms.",
                "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
            },
            "exclude_any": {
                "description": "Drop entries containing any of these case-insensitive terms.",
                "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
            },
        },
        "additionalProperties": False,
    }

    def fetch(self, source: Source, window: TimeWindow) -> list[ChangeInput]:
        validate_source_config(source)
        url = source.config.get("url")
        if not isinstance(url, str) or not url.strip():
            raise PluginConfigError("news-sitemap source config requires a non-empty url")
        include_any = _string_list_config(source.config, "include_any")
        exclude_any = _string_list_config(source.config, "exclude_any")
        client = PublicFetcher(user_agent=source.config.get("user_agent", "riffle/0.1"))
        response = client.get(url)
        root = _root(response.content)
        children = child_sitemaps(root)
        entries = news_entries(root)
        if not children and not entries and root.tag != f"{SITEMAP}urlset":
            raise PublicFetchError("Source is not a sitemap")
        for child in children[:MAX_CHILD_SITEMAPS]:
            page = news_entries(_root(client.get(str(validate_public_url(child, base_url=response.url))).content))
            entries.extend(page)
            # Pages run from new to old by last change, so one page can hold an old story that was updated.
            # Only a page whose newest story is older than the window means the next pages are older still.
            if not page or max(entry.published_at for entry in page) < window.start:
                break

        changes: list[ChangeInput] = []
        seen: set[str] = set()
        for entry in sorted(entries, key=lambda entry: entry.published_at, reverse=True):
            client.check_deadline()
            if entry.url in seen or not window.start <= entry.published_at <= window.end:
                continue
            seen.add(entry.url)
            if not _matches_filters("\n".join([entry.title, entry.url, entry.keywords]), include_any, exclude_any):
                continue
            changes.append(ChangeInput(
                external_id=entry.url,
                title=entry.title[:500],
                url=entry.url,
                published_at=entry.published_at,
                metadata={"feed_url": url, "publication": entry.publication, "keywords": entry.keywords},
            ))
            if len(changes) == MAX_ENTRIES:
                break
        client.check_deadline()
        return changes
