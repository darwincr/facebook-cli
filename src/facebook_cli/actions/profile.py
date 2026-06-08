from __future__ import annotations

from urllib.parse import quote_plus, urlparse

from facebook_cli.actions.extract import visible_posts
from facebook_cli.browser import first_visible, visible_text
from facebook_cli.conf import FACEBOOK_BASE_URL


def facebook_url(value: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        return value
    handle = value.strip().lstrip("/")
    return f"{FACEBOOK_BASE_URL}/{handle}"


def open_profile(session, handle: str, *, limit: int = 5) -> dict:
    page = session.page
    url = facebook_url(handle)
    page.goto(url)
    page.wait_for_load_state("domcontentloaded")
    session.wait()
    name = first_visible(page, [lambda p: p.locator('h1'), lambda p: p.get_by_role("heading").first], timeout_ms=3000)
    intro = first_visible(page, [lambda p: p.locator('div[aria-label="Intro"]'), lambda p: p.locator('text=Intro').locator('..')], timeout_ms=1000)
    return {
        "handle": handle,
        "url": page.url,
        "name": visible_text(name) if name else None,
        "intro": visible_text(intro) if intro else None,
        "posts": visible_posts(page, limit=limit),
    }


SEARCH_PATHS = {
    "groups": "/search/groups/",
    "pages": "/search/pages/",
    "videos": "/search/videos/",
    "reels": "/search/videos/",
}


def _facebook_path(value: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        return parsed.path.strip("/")
    return value.strip().lstrip("/")


def search_url(
    query: str,
    *,
    search_type: str = "groups",
    location: str | None = None,
    group: str | None = None,
    page_handle: str | None = None,
) -> str:
    encoded = quote_plus(query)
    if group:
        target = _facebook_path(group)
        if not target.startswith("groups/"):
            target = f"groups/{target}"
        return f"{FACEBOOK_BASE_URL}/{target.rstrip('/')}/search/?q={encoded}"
    if page_handle:
        target = _facebook_path(page_handle)
        return f"{FACEBOOK_BASE_URL}/{target.rstrip('/')}/search/?q={encoded}"
    if search_type == "marketplace":
        place = f"/{location.strip('/')}" if location else ""
        return f"{FACEBOOK_BASE_URL}/marketplace{place}/search/?query={encoded}"
    path = SEARCH_PATHS[search_type]
    return f"{FACEBOOK_BASE_URL}{path}?q={encoded}"


def search(
    session,
    query: str,
    *,
    limit: int = 10,
    search_type: str = "groups",
    location: str | None = None,
    group: str | None = None,
    page_handle: str | None = None,
) -> dict:
    from facebook_cli.actions.extract import search_results

    page = session.page
    url = search_url(query, search_type=search_type, location=location, group=group, page_handle=page_handle)
    page.goto(url)
    page.wait_for_load_state("domcontentloaded")
    session.wait()
    return {"query": query, "search_type": search_type, "url": page.url, "results": search_results(page, limit=limit, search_type=search_type)}
