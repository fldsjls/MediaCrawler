"""Internal browser pages are transport plumbing, never collection targets."""
from urllib.parse import urlsplit

INTERNAL_PREVIEW_PATH = '/__mediacrawler_preview__/'


def is_internal_preview_url(url):
    try:
        parts = urlsplit(url)
        return parts.hostname in ('127.0.0.1', 'localhost', '::1') and parts.path.startswith(INTERNAL_PREVIEW_PATH)
    except (TypeError, ValueError):
        return False


def public_pages(context):
    return [page for page in context.pages if not page.is_closed() and not is_internal_preview_url(page.url)]
