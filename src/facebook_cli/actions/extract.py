from __future__ import annotations

import re
from math import ceil
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


def default_posts_max_scrolls(limit: int) -> int:
    estimated_batch_size = 8
    estimated_scrolls = max(0, ceil(max(limit, 1) / estimated_batch_size) - 1)
    return max(2, estimated_scrolls + 2)


def _scroll_posts_page(page: Page, *, wait_seconds: float, before_count: int) -> None:
    try:
        page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 2))")
    except PlaywrightError:
        try:
            page.mouse.wheel(0, 2500)
        except PlaywrightError:
            return

    timeout_ms = max(250, int(wait_seconds * 1000))
    try:
        page.wait_for_function(
            """([selector, before]) => document.querySelectorAll(selector).length > before""",
            arg=[POST_SELECTOR, before_count],
            timeout=timeout_ms,
        )
    except PlaywrightError:
        page.wait_for_timeout(min(timeout_ms, 750))


def collect_posts(page: Page, *, limit: int = 10) -> list[dict]:
    max_scrolls = default_posts_max_scrolls(limit)
    scroll_wait = 1.5
    posts = []
    seen = set()
    stale_scrolls = 0

    for scroll_index in range(max_scrolls + 1):
        added = 0
        for post in visible_posts(page, limit=max(limit * 2, 20)):
            key = post.get("text")
            if not key or key in seen:
                continue
            seen.add(key)
            posts.append(post)
            added += 1
            if len(posts) >= limit:
                return posts[:limit]

        if scroll_index >= max_scrolls:
            break

        stale_scrolls = stale_scrolls + 1 if added == 0 else 0
        if stale_scrolls >= 2:
            break

        try:
            before = page.locator(POST_SELECTOR).count()
        except PlaywrightError:
            break
        _scroll_posts_page(page, wait_seconds=scroll_wait, before_count=before)

    return posts[:limit]


def collect_group_timeline_posts(page: Page, *, limit: int = 10) -> list[dict]:
    max_scrolls = default_posts_max_scrolls(limit)
    posts = []
    seen = set()
    stale_scrolls = 0

    for scroll_index in range(max_scrolls + 1):
        _expand_group_post_text(page)
        raw_posts = _visible_group_timeline_post_data(page, limit=max(limit * 2, 20))
        added = 0
        for raw in raw_posts:
            post = _group_timeline_post_from_data(raw)
            if not post:
                continue
            key = post.get("post_url") or f"{post.get('author_url')}:{post.get('content')}:{post.get('shared_post')}"
            if key in seen:
                continue
            seen.add(key)
            posts.append(post)
            added += 1
            if len(posts) >= limit:
                return posts[:limit]

        if scroll_index >= max_scrolls:
            break
        stale_scrolls = stale_scrolls + 1 if added == 0 else 0
        if stale_scrolls >= 2:
            break
        try:
            before = page.locator('[data-ad-rendering-role="profile_name"]').count()
            page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 2))")
            page.wait_for_function(
                """before => document.querySelectorAll('[data-ad-rendering-role="profile_name"]').length > before""",
                arg=before,
                timeout=1500,
            )
        except PlaywrightError:
            page.wait_for_timeout(750)

    return posts[:limit]


def _expand_group_post_text(page: Page) -> None:
    try:
        page.evaluate(
            r"""() => {
                const labels = new Set(['See more', 'Ver mais']);
                const candidates = Array.from(document.querySelectorAll('[role="button"], div, span'));
                let clicked = 0;
                for (const node of candidates) {
                    if (clicked >= 20) break;
                    const text = (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim();
                    if (!labels.has(text)) continue;
                    if (!node.closest('[role="article"]')) continue;
                    try {
                        node.click();
                        clicked++;
                    } catch (err) {}
                }
            }"""
        )
        page.wait_for_timeout(250)
    except PlaywrightError:
        return


def _visible_group_timeline_post_data(page: Page, *, limit: int) -> list[dict]:
    try:
        return page.locator('[data-ad-rendering-role="profile_name"]').evaluate_all(
            r"""(profileBlocks, limit) => {
                const cleanLines = text => (text || '')
                    .split(String.fromCharCode(10))
                    .map(line => line.replace(/\s+/g, ' ').trim())
                    .filter(Boolean);
                const hrefOf = link => link ? link.href : null;
                const linkData = link => link ? {
                    text: cleanLines(link.innerText).join(' '),
                    aria: link.getAttribute('aria-label') || '',
                    href: link.href || null,
                } : null;
                const uniqueTexts = nodes => {
                    const out = [];
                    const seen = new Set();
                    for (const node of nodes) {
                        const text = cleanLines(node.innerText).join('\n');
                        if (!text || seen.has(text)) continue;
                        seen.add(text);
                        out.push(text);
                    }
                    return out;
                };
                const nearestDepth = (ancestor, node) => {
                    let depth = 0;
                    for (let cur = node; cur && cur !== ancestor; cur = cur.parentElement) depth++;
                    return depth;
                };
                const out = [];
                const seenCards = new Set();
                const isUsableCard = card => {
                    if (!card) return false;
                    const messages = card.querySelectorAll('[data-ad-rendering-role="story_message"]').length;
                    const buttons = Array.from(card.querySelectorAll('[role="button"]')).map(button => button.getAttribute('aria-label') || '');
                    const hasEngagement = buttons.some(label => /^(Like|Remove Like|React|Leave a comment|Send|Share)|: [0-9,.]+ people?/i.test(label));
                    const hasPostAction = buttons.some(label => /^Actions for this post by /i.test(label));
                    const hasAdEngagement = card.querySelector('[data-ad-rendering-role="like_button"], [data-ad-rendering-role="comment_button"]');
                    return !!(messages && (hasEngagement || hasPostAction || hasAdEngagement));
                };
                const findCard = profileBlock => {
                    const roleArticle = profileBlock.closest('[role="article"]');
                    if (isUsableCard(roleArticle)) return roleArticle;
                    for (let cur = profileBlock; cur && cur !== document.body; cur = cur.parentElement) {
                        if (isUsableCard(cur)) return cur;
                    }
                    return null;
                };

                for (const seedProfileBlock of profileBlocks) {
                    const article = findCard(seedProfileBlock);
                    if (!article || seenCards.has(article)) continue;
                    seenCards.add(article);
                    const profileBlocks = Array.from(article.querySelectorAll('[data-ad-rendering-role="profile_name"]'));
                    const messages = uniqueTexts(Array.from(article.querySelectorAll('[data-ad-rendering-role="story_message"]')));
                    const links = Array.from(article.querySelectorAll('a[href]')).map(linkData).filter(Boolean);
                    const buttons = Array.from(article.querySelectorAll('[role="button"]')).map(button => ({
                        text: cleanLines(button.innerText).join(' '),
                        aria: button.getAttribute('aria-label') || '',
                    }));
                    const hasPostAction = buttons.some(button => /^Actions for this post by /i.test(button.aria));
                    const hasEngagement = buttons.some(button => /^(Like|Remove Like|React|Leave a comment|Send|Share)|: [0-9,.]+ people?/i.test(button.aria));
                    if (!profileBlocks.length || !messages.length || (!hasPostAction && !hasEngagement)) continue;

                    const profileItems = profileBlocks.map(block => {
                        const link = block.querySelector('a[href]');
                        return {
                            name: cleanLines(block.innerText).join(' ') || (link ? link.getAttribute('aria-label') || '' : ''),
                            url: hrefOf(link),
                            depth: nearestDepth(article, block),
                        };
                    }).filter(item => item.name);
                    if (!profileItems.length) continue;
                    profileItems.sort((a, b) => a.depth - b.depth);

                    const storyMessages = Array.from(article.querySelectorAll('[data-ad-rendering-role="story_message"]'));
                    const messageItems = storyMessages.map(node => ({text: cleanLines(node.innerText).join('\n'), depth: nearestDepth(article, node)})).filter(item => item.text);
                    messageItems.sort((a, b) => a.depth - b.depth);

                    const linkPreview = article.querySelector('a[href] [data-ad-rendering-role="title"]')?.closest('a[href]');
                    const linkPreviewRoot = linkPreview ? linkPreview.closest('a[href]') : null;
                    const previewContainer = linkPreviewRoot || article;
                    const previewTitle = previewContainer.querySelector('[data-ad-rendering-role="title"]');
                    const previewMeta = previewContainer.querySelector('[data-ad-rendering-role="meta"]');
                    const previewDescription = previewContainer.querySelector('[data-ad-rendering-role="description"]');
                    const sharedHeader = Array.from(article.querySelectorAll('h4 [data-ad-rendering-role="profile_name"], h4')).find(Boolean);
                    const sharedProfileBlock = profileBlocks.find(block => block.closest('h4')) || null;
                    const sharedLink = sharedProfileBlock ? sharedProfileBlock.querySelector('a[href]') : null;
                    const privacyIcon = Array.from(article.querySelectorAll('svg title')).map(title => title.textContent || '').find(Boolean) || '';
                    const badges = uniqueTexts(Array.from(article.querySelectorAll('[aria-label*="badge details" i], [aria-label*="view badge details" i]')));
                    const images = Array.from(article.querySelectorAll('img[src]')).map(img => ({
                        alt: img.alt || '',
                        src: img.src || '',
                    })).filter(img => img.src && !img.src.startsWith('data:'));

                    out.push({
                        author: profileItems[0],
                        profiles: profileItems,
                        messages: messageItems.map(item => item.text),
                        badges,
                        privacy: privacyIcon,
                        links,
                        buttons,
                        images,
                        link_preview: previewTitle ? {
                            title: cleanLines(previewTitle.innerText).join(' '),
                            domain: previewMeta ? cleanLines(previewMeta.innerText).join(' ') : '',
                            description: previewDescription ? cleanLines(previewDescription.innerText).join('\n') : '',
                            url: linkPreviewRoot ? linkPreviewRoot.href : null,
                        } : null,
                        shared_author: sharedProfileBlock ? {
                            name: cleanLines(sharedProfileBlock.innerText).join(' '),
                            url: hrefOf(sharedLink),
                        } : null,
                    });
                    if (out.length >= limit) break;
                }
                return out;
            }""",
            limit,
        )
    except PlaywrightError:
        return []


def _group_timeline_post_from_data(data: dict | None) -> dict | None:
    if not data or not data.get("author"):
        return None
    author = data["author"]
    author_name = _clean_group_timeline_author(author.get("name") or "")
    if not author_name:
        return None

    messages = [message for message in data.get("messages") or [] if message]
    links = data.get("links") or []
    buttons = data.get("buttons") or []
    author_url = clean_url(author.get("url"))
    result = {
        "type": "group_post",
        "author": author_name,
        "content": messages[0] if messages else "",
    }

    post_url = _first_url(links, ("/posts/", "/permalink/", "/photo"))
    if post_url:
        result["post_url"] = post_url

    shared_author = data.get("shared_author") or {}
    link_preview = data.get("link_preview") or None
    if not shared_author.get("name") and ((len(messages) > 1) or link_preview):
        shared_author = _group_timeline_shared_author_from_links(
            links,
            author=author_name,
            author_url=author_url,
            content="\n".join(messages),
            link_preview=link_preview,
        ) or {}
    if shared_author.get("name") or (len(messages) > 1) or link_preview:
        shared_post = {}
        if shared_author.get("name"):
            shared_post["author"] = " ".join(shared_author["name"].split())
        if len(messages) > 1:
            shared_content = _expanded_group_post_content(messages[1], link_preview)
            shared_post["content"] = shared_content
        if link_preview:
            clean_preview = _clean_link_preview(link_preview, shared_post.get("content"), post_url=post_url)
            if clean_preview:
                shared_post["link_preview"] = clean_preview
        result["is_repost"] = True
        result["shared_post"] = shared_post
    else:
        result["is_repost"] = False

    media = _group_post_media(_content_images(data.get("images") or []), links)
    for item in media:
        if _canonical_search_url_key(item.get("url")) == _canonical_search_url_key(post_url):
            item.pop("url", None)
    if media:
        result["has_media"] = True
        result["media"] = media

    reactions = _group_post_reactions(buttons)
    if reactions:
        result["reactions"] = reactions
    comment_count = _group_post_comment_count(buttons)
    if comment_count is not None:
        result["comment_count"] = comment_count

    mentioned = _group_post_mentions(links, author=author_name, author_url=author_url)
    mentioned = [item for item in mentioned if item["name"] in result["content"]]
    shared_author_url = clean_url(shared_author.get("url")) if shared_author else None
    if shared_author_url:
        mentioned = [item for item in mentioned if _canonical_search_url_key(item.get("url")) != _canonical_search_url_key(shared_author_url)]
    if mentioned:
        result["mentioned_users"] = mentioned

    external_links = _group_post_external_links(links, result)
    if external_links:
        result["external_links"] = external_links
    return result


def _clean_group_timeline_author(value: str) -> str:
    parts = [part.strip() for part in " ".join(value.split()).split(" · ") if part.strip()]
    return next((part for part in parts if part.casefold() != "follow"), " ".join(value.split()))


def _content_images(images: list[dict]) -> list[dict]:
    content = []
    seen = set()
    for image in images:
        src = image.get("src") or ""
        if not src.startswith("http") or "static.xx.fbcdn.net" in src:
            continue
        key = image.get("alt") or src.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        content.append(image)
    return content


def _useful_link_preview_url(href: str | None, *, post_url: str | None) -> str | None:
    url = clean_url(href)
    if not url:
        return None
    if _canonical_search_url_key(url) == _canonical_search_url_key(post_url):
        return None
    path = _url_path(url)
    if path.startswith("/groups/") and not any(part in path for part in ("/posts/", "/permalink/")):
        return None
    return url


def _clean_link_preview(preview: dict, content: str | None, *, post_url: str | None) -> dict:
    title = " ".join((preview.get("title") or "").split())
    domain = " ".join((preview.get("domain") or "").split())
    description = (preview.get("description") or "").strip()
    url = _useful_link_preview_url(preview.get("url"), post_url=post_url)

    if content and _same_text(description, content):
        description = ""
    if _is_noisy_preview_domain(domain):
        domain = ""
    if title and content and _same_text(title, content):
        title = ""

    cleaned = {
        key: value for key, value in {
            "title": title,
            "domain": domain,
            "description": description,
            "url": url,
        }.items() if value
    }
    if not url and _is_low_value_preview_title(title) and (not description or _looks_random_preview_description(description)):
        return {}
    if not url and set(cleaned) <= {"title", "domain"} and _is_low_value_preview_title(title):
        return {}
    return cleaned


def _same_text(left: str | None, right: str | None) -> bool:
    return " ".join((left or "").split()) == " ".join((right or "").split())


def _is_noisy_preview_domain(domain: str | None) -> bool:
    if not domain:
        return False
    normalized = domain.removeprefix("www.")
    name = normalized.split(".", 1)[0]
    has_upper = any(char.isupper() for char in name)
    has_lower = any(char.islower() for char in name)
    has_digit = any(char.isdigit() for char in name)
    return has_digit and has_upper and has_lower


def _is_low_value_preview_title(title: str | None) -> bool:
    return not title or title in {"Darwin", "Facebook"}


def _looks_random_preview_description(description: str | None) -> bool:
    if not description:
        return False
    text = description.strip()
    if len(text) < 20 or " " in text:
        return False
    has_upper = any(char.isupper() for char in text)
    has_lower = any(char.islower() for char in text)
    has_digit = any(char.isdigit() for char in text)
    return has_upper and has_lower and has_digit


def _is_group_chrome_link(href: str, text: str | None) -> bool:
    path = _url_path(href)
    if path in {"/", "/groups", "/reel", "/marketplace", "/gaming/play"}:
        return True
    if path.startswith(("/groups/feed", "/groups/discover")):
        return True
    if text in {"Facebook", "Home", "Groups", "Marketplace", "Reels", "Gaming"}:
        return True
    return False


def _group_timeline_shared_author_from_links(
    links: list[dict],
    *,
    author: str,
    author_url: str | None,
    content: str,
    link_preview: dict | None,
) -> dict | None:
    author_key = _canonical_search_url_key(author_url)
    preview_title = " ".join(((link_preview or {}).get("title") or "").split())
    preview_domain = " ".join(((link_preview or {}).get("domain") or "").split()).casefold()
    for link in links:
        href = clean_url(link.get("href"))
        name = " ".join(((link.get("text") or link.get("aria") or "").split()))
        if not href or not _is_sane_profile_name(name) or name == author:
            continue
        key = _canonical_search_url_key(href)
        if key == author_key:
            continue
        if not _is_profile_or_page_url(href) or _is_group_chrome_link(href, name):
            continue
        if name not in content and name != preview_title and name.casefold().replace(" ", "") not in preview_domain:
            continue
        return {"name": name, "url": href}
    return None


def _expanded_group_post_content(content: str, link_preview: dict | None) -> str:
    preview_description = (link_preview or {}).get("description") or ""
    if not preview_description:
        return content
    marker = "… See more"
    if marker not in content:
        return content
    prefix = content.replace(marker, "").rstrip()
    if prefix and preview_description.startswith(prefix):
        return preview_description
    return content


def _is_sane_profile_name(value: str | None) -> bool:
    if not value or value.endswith(", view story"):
        return False
    words = value.split()
    if len(words) > 6:
        return False
    if sum(1 for word in words if len(word) == 1) > max(1, len(words) // 2):
        return False
    return any(char.isalpha() for char in value)


def _is_profile_or_page_url(href: str) -> bool:
    path = _url_path(href)
    if path.startswith("/groups/"):
        return "/user/" in path
    if path.startswith(("/stories/", "/photo", "/posts/", "/permalink/", "/watch", "/reel")):
        return False
    if path in {"/", "/groups", "/marketplace", "/gaming/play"}:
        return False
    return True


def _group_post_external_links(links: list[dict], post: dict) -> list[dict]:
    internal_urls = {
        _canonical_search_url_key(post.get("post_url")),
    }
    shared = post.get("shared_post") or {}
    preview = shared.get("link_preview") or {}
    internal_urls.add(_canonical_search_url_key(preview.get("url")))
    for media in post.get("media") or []:
        internal_urls.add(_canonical_search_url_key(media.get("url")))

    useful_links = []
    seen = set()
    for link in links:
        href = clean_url(link.get("href"))
        text = " ".join(((link.get("text") or link.get("aria") or "").split())) or None
        key = _canonical_search_url_key(href)
        if not href or not key or key in seen or key in internal_urls:
            continue
        parsed = urlparse(href)
        if parsed.netloc.endswith("facebook.com") or _is_group_chrome_link(href, text):
            continue
        seen.add(key)
        useful_links.append({"text": text, "url": href})
    return useful_links


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


def default_search_max_scrolls(limit: int) -> int:
    estimated_batch_size = 25
    estimated_scrolls = max(0, ceil(max(limit, 1) / estimated_batch_size) - 1)
    return max(3, estimated_scrolls + 3)


def collect_search_results(
    page: Page,
    *,
    limit: int = 10,
    search_type: str = "groups",
) -> dict:
    max_scrolls = default_search_max_scrolls(limit)
    scroll_wait = 1.5
    results = []
    seen = set()
    stale_scrolls = 0
    exhausted = False
    scrolls = 0

    for scroll_index in range(max_scrolls + 1):
        added = 0
        for item in search_results(page, limit=max(limit * 2, 25), search_type=search_type):
            key = _canonical_search_url_key(item.get("url")) or item.get("url")
            if not key or key in seen:
                continue
            seen.add(key)
            results.append(item)
            added += 1
            if len(results) >= limit:
                return {
                    "results": results[:limit],
                    "result_count": limit,
                    "scrolls": scrolls,
                    "exhausted": False,
                    "max_scrolls": max_scrolls,
                }

        if scroll_index >= max_scrolls:
            break

        stale_scrolls = stale_scrolls + 1 if added == 0 else 0
        if stale_scrolls >= 2:
            exhausted = True
            break

        before = _search_result_link_count(page, search_type=search_type)
        _scroll_search_page(page, wait_seconds=scroll_wait, before_count=before, search_type=search_type)
        scrolls += 1

    if len(results) < limit:
        exhausted = exhausted or stale_scrolls > 0
    return {
        "results": results[:limit],
        "result_count": len(results[:limit]),
        "scrolls": scrolls,
        "exhausted": exhausted,
        "max_scrolls": max_scrolls,
    }


def _search_result_link_count(page: Page, *, search_type: str) -> int:
    if search_type == "marketplace":
        selector = 'a[href*="/marketplace/item/"]'
    else:
        selector = 'div[role="main"] a[href], main a[href]'
    try:
        return page.locator(selector).count()
    except PlaywrightError:
        return 0


def _scroll_search_page(page: Page, *, wait_seconds: float, before_count: int, search_type: str) -> None:
    if search_type == "marketplace":
        selector = 'a[href*="/marketplace/item/"]'
    else:
        selector = 'div[role="main"] a[href], main a[href]'

    try:
        page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 2))")
    except PlaywrightError:
        try:
            page.mouse.wheel(0, 2500)
        except PlaywrightError:
            return

    timeout_ms = max(250, int(wait_seconds * 1000))
    try:
        page.wait_for_function(
            """([selector, before]) => document.querySelectorAll(selector).length > before""",
            arg=[selector, before_count],
            timeout=timeout_ms,
        )
    except PlaywrightError:
        page.wait_for_timeout(min(timeout_ms, 750))


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
        if not href or key in seen or not _is_sane_profile_name(name) or name == author:
            continue
        path = _url_path(href)
        if "/search" in path or "/photo" in path or path.startswith("/marketplace"):
            continue
        if not _is_profile_or_page_url(href):
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
