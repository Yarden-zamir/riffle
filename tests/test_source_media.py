"""Contract: every plugin fills `metadata.media` from the images and videos that its entries declare."""

import json

from test_network import response
from test_news_sitemap_plugin import WINDOW, source as sitemap_source, urlset, wire as wire  # noqa: F401
from test_source_preview import source, window as window  # noqa: F401

from riffle.enrichment import enrich_change, enrichment_profile, media_from_url, page_media
from riffle.plugins.news_sitemap import NewsSitemapPlugin
from riffle.plugins.x import XPlugin

PROFILE = enrichment_profile("plain")


def media(items) -> list[tuple[str, str]]:
    return [(item.url, item.kind) for item in items]


def enrich(content: str, *, feed_media=(), thumbnails=(), fetch_link=None, summary: str = "A long enough summary about the post to stay as it is."):
    return enrich_change(title="Post", summary=summary, content=content, url="https://blog.example/posts/one",
                         feed_title="Blog", profile=PROFILE, fetch_link=fetch_link, feed_media=feed_media, thumbnails=thumbnails)


def test_body_images_resolve_relative_and_lazy_addresses() -> None:
    body = ('<p>Text</p><img src="/img/a.png"><img src="data:image/gif;base64,R0lG" data-src="b.jpg">'
            '<picture><source srcset="c.webp" type="image/webp"><img srcset="c.jpg 1x, c@2x.jpg 2x"></picture>')

    assert media(enrich(body).media) == [
        ("https://blog.example/img/a.png", "image"),
        ("https://blog.example/posts/b.jpg", "image"),
        ("https://blog.example/posts/c.jpg", "image"),
    ]


def test_feed_media_follow_the_body_and_thumbnails_only_fill_an_empty_card() -> None:
    attached = [media_from_url("https://cdn.example/clip.mp4", hint="video/mp4"), media_from_url("https://cdn.example/talk.mp3", hint="audio/mpeg")]
    thumb = [media_from_url("https://cdn.example/thumb.jpg", hint="image")]

    assert media(enrich('<p>Hi <img src="https://cdn.example/a.png"></p>', feed_media=attached, thumbnails=thumb).media) == [
        ("https://cdn.example/a.png", "image"),
        ("https://cdn.example/clip.mp4", "video"),
    ]
    assert media(enrich("<p>No pictures</p>", thumbnails=thumb).media) == [("https://cdn.example/thumb.jpg", "image")]


def test_a_fetched_linked_page_gives_its_share_image_to_a_card_without_media() -> None:
    page = '<html><head><meta property="og:image" content="/share.png"></head><body><p>Full article text.</p></body></html>'

    enriched = enrich_change(title="v1.2.3", summary="", content="", url="https://blog.example/posts/one", feed_title="Blog",
                             profile=enrichment_profile("linked", fetch_link_when=("thin_summary",)), fetch_link=lambda _: page)

    assert media(enriched.media) == [("https://blog.example/share.png", "image")]


def test_page_media_puts_the_share_video_first_and_skips_svg() -> None:
    page = ('<meta name="twitter:image" content="https://site.example/t.png"><meta property="og:image" content="https://site.example/logo.svg">'
            '<meta property="og:video" content="https://site.example/v.mp4">')

    assert media(page_media(page, "https://site.example/news/a")) == [
        ("https://site.example/v.mp4", "video"),
        ("https://site.example/t.png", "image"),
    ]


def test_x_posts_carry_photos_and_the_best_video_variant(wire, window) -> None:
    tweet = {"id_str": "12", "full_text": "Look", "created_at": "Thu Jul 02 12:00:00 +0000 2026", "extended_entities": {"media": [
        {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/a.jpg"},
        {"type": "video", "media_url_https": "https://pbs.twimg.com/thumb.jpg", "video_info": {"variants": [
            {"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/v.m3u8"},
            {"content_type": "video/mp4", "bitrate": 256000, "url": "https://video.twimg.com/low.mp4"},
            {"content_type": "video/mp4", "bitrate": 2176000, "url": "https://video.twimg.com/high.mp4"},
        ]}},
        "not an object",
    ]}}
    payload = {"props": {"pageProps": {"timeline": {"entries": [{"type": "tweet", "content": {"tweet": tweet}}]}}}}
    wire.responses.append(response(f'<script id="__NEXT_DATA__">{json.dumps(payload)}</script>'.encode()))

    [change] = XPlugin().fetch(source("x", url="https://x.com/Example"), window)

    assert change.metadata["media"] == [
        {"url": "https://pbs.twimg.com/media/a.jpg", "kind": "image"},
        {"url": "https://video.twimg.com/high.mp4", "kind": "video"},
    ]


def test_news_sitemap_entries_carry_their_image_sitemap_pictures(wire) -> None:
    body = urlset(
        "<url><loc>http://news.example/a</loc><news:news><news:publication><news:name>N</news:name></news:publication>"
        "<news:publication_date>2026-10-24T09:00:00Z</news:publication_date><news:title>A</news:title></news:news>"
        "<image:image xmlns:image='http://www.google.com/schemas/sitemap-image/1.1'><image:loc>https://img.example/a.jpg</image:loc></image:image>"
        "</url>"
    )
    wire.responses.append(response(body))

    [change] = NewsSitemapPlugin().fetch(sitemap_source(), WINDOW)

    assert change.metadata["media"] == [{"url": "https://img.example/a.jpg", "kind": "image"}]
