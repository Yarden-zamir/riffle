from html import escape

from riffle.models import SharedProfile


def share_page_html(index_html: str, shared: SharedProfile | None) -> str:
    """Add crawler-readable metadata using only the public share projection."""
    title = "Riffle"
    description = "Follow your sources in one feed with Riffle."
    if shared is not None:
        byline = f"{shared.shared_by}'s " if shared.shared_by else ""
        title = f"{byline}{shared.name} desk on Riffle"
        count = len(shared.sources)
        description = f"{count} {'source' if count == 1 else 'sources'}. Import them into your own Riffle feed."

    title, description = escape(title, quote=True), escape(description, quote=True)
    tags = f"""<title>{title}</title>
    <meta name="description" content="{description}" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="Riffle" />
    <meta property="og:title" content="{title}" />
    <meta property="og:description" content="{description}" />
    <meta name="twitter:card" content="summary" />
    <meta name="twitter:title" content="{title}" />
    <meta name="twitter:description" content="{description}" />"""
    return index_html.replace("<title>Riffle</title>", tags, 1)
