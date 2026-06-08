from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import Error as PlaywrightError, Locator, Page

from facebook_cli.browser import safe_attr, visible_text
from facebook_cli.conf import FACEBOOK_BASE_URL

POST_SELECTOR = 'div[role="article"]'
PRICE_RE = re.compile(r"^(?:free|\$|[A-Z]{1,4}\$|[A-Z]{3}\s?\$)", re.IGNORECASE)
_GROUP_META_RE = re.compile(
    r"\b(Public|Private)\s*·\s*"
    r"([\d,.]+\+?\s*[KMB]?)\s*members"
    r"(?:\s*·\s*(.+?))?(?:\s*Join\s*)?$"
)


def clean_url(href: str | None) -> str | None:
    if not href:
        return None
    url = urljoin(FACEBOOK_BASE_URL, href)
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()


def _url_path(href: str) -> str:
    return urlparse(href).path.rstrip("/") or "/"


def _is_search_result_url(href: str, *, search_type: str) -> bool:
    path = _url_path(href)
    if search_type == "marketplace":
        return path.startswith("/marketplace/item/")
    return True


def _is_scoped_search_url(href: str) -> bool:
    path = _url_path(href)
    return path.endswith("/search") and (
        path.startswith("/groups/") or path.startswith("/profile")
    )


def visible_posts(page: Page, *, limit: int = 10) -> list[dict]:
    posts = []
    articles = page.locator(POST_SELECTOR)
    count = min(articles.count(), limit * 3)
    seen = set()
    for index in range(count):
        article = articles.nth(index)
        text = visible_text(article)
        if not text or text in seen:
            continue
        seen.add(text)
        posts.append(_post_from_article(article, text))
        if len(posts) >= limit:
            break
    return posts


def search_results(page: Page, *, limit: int = 10, search_type: str = "groups") -> list[dict]:
    if _is_scoped_search_url(page.url):
        scoped_results = _scoped_search_results(page, limit=limit)
        if scoped_results:
            return scoped_results

    results = []
    seen = set()
    containers = page.locator(
        'div[role="main"] div[role="article"], main div[role="article"], '
        'div[role="main"] div[role="listitem"], main div[role="listitem"]'
    )
    container_count = min(containers.count(), limit * 6)
    for index in range(container_count):
        item = _search_result_from_container(containers.nth(index), search_type=search_type)
        if not item or item["url"] in seen:
            continue
        seen.add(item["url"])
        results.append(item)
        if len(results) >= limit:
            return results

    links = page.locator('div[role="main"] a[role="link"][href], main a[role="link"][href]').or_(
        page.locator('div[role="main"] a[href], main a[href]')
    )
    count = min(links.count(), limit * 20)
    for index in range(count):
        link = links.nth(index)
        text = visible_text(link)
        href = clean_url(safe_attr(link, "href"))
        if not text or not href or href in seen:
            continue
        if not _is_search_result_url(href, search_type=search_type):
            continue
        if _is_search_navigation_link(link, text, href, search_type=search_type):
            continue
        seen.add(href)
        results.append(_search_result_from_link(link, text, href, search_type=search_type))
        if len(results) >= limit:
            break
    return results


def _search_result_from_container(container: Locator, *, search_type: str) -> dict | None:
    text = visible_text(container)
    if not text:
        return None
    links = container.locator('a[role="link"][href], a[href]')
    link_count = min(links.count(), 20)
    for index in range(link_count):
        link = links.nth(index)
        title = visible_text(link)
        href = clean_url(safe_attr(link, "href"))
        if not title or not href:
            continue
        if not _is_search_result_url(href, search_type=search_type):
            continue
        if _is_search_navigation_link(link, title, href, search_type=search_type):
            continue
        result = _search_result_from_link(link, title, href, search_type=search_type)
        if text != title:
            result["text"] = text
        if search_type == "groups":
            _enrich_group_result(result)
        if search_type == "pages":
            _enrich_page_result(result)
        if search_type in ("videos", "reels"):
            _enrich_video_result(result)
        return result
    return None


def _is_search_navigation_link(link: Locator, text: str, href: str, *, search_type: str) -> bool:
    path = _url_path(href)
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    lowered = " ".join(text.casefold().split())
    tab_labels = {
        "all",
        "posts",
        "people",
        "photos",
        "videos",
        "marketplace",
        "pages",
        "places",
        "groups",
        "events",
        "links",
        "reels",
    }
    if lowered in tab_labels:
        return True
    if any(skip in href for skip in ("/privacy/", "/policies/", "/help/", "l.php?")):
        return True
    if path.startswith("/search/") and ("q" in query or "query" in query):
        return True
    if path in {"/", "/home.php", "/friends", "/watch", "/gaming", "/saved", "/pages", "/groups", "/marketplace"}:
        return True
    if path.startswith(("/groups/feed", "/groups/discover", "/marketplace/category", "/marketplace/categories")):
        return True
    if search_type == "marketplace" and not path.startswith("/marketplace/item"):
        return True
    try:
        return bool(
            link.evaluate(
                """el => !!el.closest('[role="navigation"], [role="banner"], [role="complementary"], nav, header')"""
            )
        )
    except PlaywrightError:
        return False


_VIDEO_DURATION_RE = re.compile(r"^(\d+:\d+(?::\d+)?)\s+")
_VIDEO_VIEWS_RE = re.compile(r"([\d,.]+\s*[KMB]?\s*views)\s*$")


def _dedup_video_content(content: str) -> str:
    mid = len(content) // 2
    for offset in range(min(20, mid)):
        left = content[: mid + offset]
        right = content[mid + offset:]
        if left and right and left.strip() == right.strip():
            return left.strip()
    return content.strip()


def _enrich_video_result(result: dict) -> None:
    text = result.get("text") or ""
    title = result.get("title") or ""
    if not text:
        return

    duration_match = _VIDEO_DURATION_RE.match(text)
    if duration_match:
        result["duration"] = duration_match.group(1)
        text = text[duration_match.end():]

    views_match = _VIDEO_VIEWS_RE.search(text)
    if not views_match:
        return
    result["views"] = views_match.group(1).strip()

    before_views = text[: views_match.start()].rstrip(" ·\u00b7")

    title_pos = before_views.rfind(title) if title else -1
    if title_pos > 0:
        after_title = before_views[title_pos + len(title):].strip()
        before_title = before_views[:title_pos].rstrip()
        if after_title:
            result["timestamp"] = after_title
    else:
        before_title = before_views.rstrip()

    content = before_title.strip()
    if content:
        result["content"] = _dedup_video_content(content)

    result.pop("text", None)


def _enrich_page_result(result: dict) -> None:
    text = result.get("text") or ""
    title = result.get("title") or ""
    remaining = text
    if remaining.startswith(title):
        remaining = remaining[len(title):].strip()
    remaining = re.sub(r"\s*Follow\s*$", "", remaining).strip()
    if not remaining:
        return
    followers_match = re.search(r"\s*·\s*([\d,.]+\s*followers?)\s*", remaining)
    if followers_match:
        category = remaining[: followers_match.start()].strip()
        description = remaining[followers_match.end() :].strip()
        if category:
            result["category"] = category
        result["followers"] = followers_match.group(1).strip()
        if description:
            result["description"] = description
    else:
        result["category"] = remaining
    result.pop("text", None)


def _enrich_group_result(result: dict) -> None:
    text = result.get("text") or result.get("title") or ""
    match = _GROUP_META_RE.search(text)
    if not match:
        return
    result["visibility"] = match.group(1)
    result["members"] = match.group(2).strip()
    if match.group(3):
        result["activity"] = match.group(3).strip()
    result.pop("text", None)


def _search_result_from_link(link: Locator, title: str, href: str, *, search_type: str = "groups") -> dict:
    if search_type == "marketplace":
        lines = _visible_text_lines(link)
        if not lines:
            lines = [title]
        result = _marketplace_result_from_lines(lines)
        result["url"] = href
        return result

    result = {"title": title, "url": href}
    try:
        card_text = link.evaluate(
            """el => {
                const card = el.closest('[role="article"], [role="listitem"], div[data-visualcompletion]') || el;
                return (card.innerText || '').replace(/\\s+/g, ' ').trim();
            }"""
        )
    except PlaywrightError:
        card_text = ""
    if card_text and card_text != title:
        result["text"] = card_text
    if search_type == "groups":
        _enrich_group_result(result)
    if search_type == "pages":
        _enrich_page_result(result)
    if search_type in ("videos", "reels"):
        _enrich_video_result(result)
    return result


def _scoped_search_results(page: Page, *, limit: int = 10) -> list[dict]:
    results = []
    seen = set()
    author_links = page.locator(
        'div[role="main"] a[href*="/user/"], div[role="main"] a[href*="facebook.com/"][aria-label], '
        'main a[href*="/user/"], main a[href*="facebook.com/"][aria-label]'
    )
    count = min(author_links.count(), limit * 10)
    for index in range(count):
        data = _group_post_card_data(author_links.nth(index))
        item = _group_post_result_from_card_data(data)
        if not item:
            continue
        key = item.get("post_url") or f"{item.get('author_url')}:{item.get('content')}"
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
        if len(results) >= limit:
            break
    return results


def _group_post_card_data(author_link: Locator) -> dict | None:
    try:
        return author_link.evaluate(
            """author => {
                const cleanLines = text => (text || '')
                    .split(String.fromCharCode(10))
                    .map(s => s.trim())
                    .filter(Boolean);
                const authorName = cleanLines(author.innerText).join(' ') || author.getAttribute('aria-label') || '';
                if (!authorName) return null;

                let card = author;
                for (let i = 0; card && i < 30; i++, card = card.parentElement) {
                    const text = card.innerText || '';
                    const hasPostText = Array.from(card.querySelectorAll('div, span')).some(el => {
                        const lines = cleanLines(el.innerText);
                        return lines.some(line => line.length > 40) && !lines.some(line => line === 'Facebook');
                    });
                    const hasEngagement = Array.from(card.querySelectorAll('[role="button"]')).some(el => {
                        const label = el.getAttribute('aria-label') || '';
                        return label === 'Like' || label === 'Leave a comment' || /: [0-9,.]+ people$/.test(label);
                    });
                    if (text.includes(authorName) && hasPostText && hasEngagement) break;
                }
                if (!card) return null;

                const isHumanLine = line => line.length > 40 && line.split(/\\s+/).filter(part => part.length > 1).length >= 5;
                const contentCandidates = Array.from(card.querySelectorAll('div, span'))
                    .map(el => ({el, lines: cleanLines(el.innerText)}))
                    .map(item => ({...item, humanLineCount: item.lines.filter(isHumanLine).length}))
                    .filter(item => {
                        const text = item.lines.join(' ');
                        return item.humanLineCount
                            && !item.lines.includes('Facebook')
                            && text !== authorName
                            && !item.el.closest('a[href*="/photo/"], a[href*="/groups/"][href*="/search/"]');
                    })
                    .sort((a, b) => b.humanLineCount - a.humanLineCount || a.lines.join(' ').length - b.lines.join(' ').length);
                const contentLines = contentCandidates.length ? contentCandidates[0].lines : [];

                return {
                    author_name: authorName,
                    author_url: author.href || null,
                    lines: cleanLines(card.innerText),
                    content_lines: contentLines,
                    links: Array.from(card.querySelectorAll('a[href]')).map(a => ({
                        text: cleanLines(a.innerText).join(' '),
                        aria: a.getAttribute('aria-label'),
                        href: a.href,
                    })),
                    images: Array.from(card.querySelectorAll('img[src]')).map(img => ({
                        alt: img.alt || '',
                        src: img.src || '',
                    })),
                    buttons: Array.from(card.querySelectorAll('[role="button"]')).map(el => ({
                        text: cleanLines(el.innerText).join(' '),
                        aria: el.getAttribute('aria-label') || '',
                    })),
                };
            }"""
        )
    except PlaywrightError:
        return None


def _group_post_result_from_card_data(data: dict | None) -> dict | None:
    if not data or not data.get("author_name"):
        return None

    content_lines = [line for line in data.get("content_lines") or [] if line]
    if not content_lines:
        return None

    author_url = clean_url(data.get("author_url"))
    content = "\n".join(content_lines)
    result = {
        "type": "group_post",
        "title": data["author_name"],
        "author": data["author_name"],
        "author_url": author_url,
        "content": content,
        "content_lines": content_lines,
    }

    links = data.get("links") or []
    post_url = _first_url(links, ("/photo", "/posts/", "/permalink/"))
    result["url"] = post_url or author_url
    if post_url:
        result["post_url"] = post_url

    mentioned = _group_post_mentions(links, author=data["author_name"], author_url=author_url)
    if mentioned:
        result["mentioned_users"] = mentioned

    media = _group_post_media(data.get("images") or [], links)
    if media:
        result["has_media"] = True
        result["media"] = media

    reactions = _group_post_reactions(data.get("buttons") or [])
    if reactions:
        result["reactions"] = reactions

    comment_count = _group_post_comment_count(data.get("buttons") or [])
    if comment_count is not None:
        result["comment_count"] = comment_count

    return result


def _first_url(links: list[dict], path_parts: tuple[str, ...]) -> str | None:
    for link in links:
        href = clean_url(link.get("href"))
        if href and any(part in _url_path(href) for part in path_parts):
            return href
    return None


def _group_post_mentions(links: list[dict], *, author: str, author_url: str | None) -> list[dict]:
    mentions = []
    seen = {_canonical_search_url_key(author_url)} if author_url else set()
    for link in links:
        href = clean_url(link.get("href"))
        name = " ".join(((link.get("text") or link.get("aria") or "").split()))
        key = _canonical_search_url_key(href)
        if not href or key in seen or not name or name == author:
            continue
        path = _url_path(href)
        if "/search" in path or "/photo" in path or path.startswith("/marketplace"):
            continue
        seen.add(key)
        mentions.append({"name": name, "url": href})
    return mentions


def _canonical_search_url_key(href: str | None) -> str | None:
    if not href:
        return None
    parsed = urlparse(href)
    return parsed._replace(query="", fragment="").geturl()


def _group_post_media(images: list[dict], links: list[dict]) -> list[dict]:
    photo_url = _first_url(links, ("/photo",))
    media = []
    for image in images:
        src = image.get("src") or ""
        if not src.startswith("http"):
            continue
        item = {"type": "image", "src": src}
        if image.get("alt"):
            item["alt"] = image["alt"]
        if photo_url:
            item["url"] = photo_url
        media.append(item)
    return media


def _group_post_reactions(buttons: list[dict]) -> dict | None:
    reactions = {}
    for button in buttons:
        aria = button.get("aria") or ""
        text = button.get("text") or ""
        if aria == "Like" and text.isdigit():
            reactions["count"] = int(text)
            continue
        match = re.match(r"^([^:]+): ([0-9,.]+) people$", aria)
        if match:
            reactions.setdefault("breakdown", {})[match.group(1)] = _parse_count(match.group(2))
    return reactions or None


def _group_post_comment_count(buttons: list[dict]) -> int | None:
    for button in buttons:
        if button.get("aria") == "Leave a comment":
            return _parse_count(button.get("text") or "0")
    return None


def _parse_count(value: str) -> int:
    cleaned = value.replace(",", "").replace(".", "")
    return int(cleaned) if cleaned.isdigit() else 0


def _visible_text_lines(locator: Locator) -> list[str]:
    try:
        text = locator.inner_text(timeout=1000)
    except PlaywrightError:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def _marketplace_result_from_lines(lines: list[str]) -> dict:
    cleaned = [" ".join(line.split()) for line in lines if line.strip()]
    result = {"title": " ".join(cleaned)}
    if not cleaned:
        return result

    price_count = 0
    while price_count < len(cleaned) and PRICE_RE.match(cleaned[price_count]):
        price_count += 1

    if price_count:
        result["price"] = cleaned[0]
        if price_count > 1:
            result["original_price"] = cleaned[1]
        details = cleaned[price_count:]
        if details:
            result["title"] = details[0]
        if len(details) > 1:
            result["location"] = details[1]
        if len(details) > 2:
            result["metadata"] = details[2:]
        return result

    result["title"] = cleaned[0]
    if len(cleaned) > 1:
        result["location"] = cleaned[1]
    if len(cleaned) > 2:
        result["metadata"] = cleaned[2:]
    return result


def _post_from_article(article: Locator, text: str) -> dict:
    links = []
    try:
        link_count = min(article.locator('a[href]').count(), 12)
        for index in range(link_count):
            link = article.locator('a[href]').nth(index)
            href = clean_url(safe_attr(link, "href"))
            label = visible_text(link) or safe_attr(link, "aria-label")
            if href and {"url": href, "text": label} not in links:
                links.append({"text": label, "url": href})
    except PlaywrightError:
        pass
    return {"text": text, "links": links}
