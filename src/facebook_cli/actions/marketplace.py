from __future__ import annotations

import re
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError

from facebook_cli.actions.extract import clean_url
from facebook_cli.actions.messages import ensure_messenger_unlocked
from facebook_cli.browser import first_visible, goto_domcontentloaded, human_fill, require_visible, safe_attr, visible_text
from facebook_cli.conf import FACEBOOK_BASE_URL


CHAT_BUTTON_LOCATORS = [
    lambda p: p.get_by_role("button", name="Message"),
    lambda p: p.get_by_role("button", name="Send message"),
    lambda p: p.locator('[role="button"][aria-label*="Message" i]'),
    lambda p: p.locator('div[role="button"]:has-text("Message")'),
    lambda p: p.locator('button:has-text("Message")'),
]
CHAT_TEXTBOX_LOCATORS = [
    lambda p: p.locator('div[role="dialog"] div[role="textbox"][contenteditable="true"]'),
    lambda p: p.locator('div[role="dialog"] textarea'),
    lambda p: p.locator('div[aria-label*="Marketplace" i] div[role="textbox"][contenteditable="true"]'),
    lambda p: p.locator('div[role="textbox"][contenteditable="true"][aria-label*="Message" i]'),
    lambda p: p.locator('div[role="textbox"][contenteditable="true"]'),
    lambda p: p.locator('textarea[aria-label*="Message" i]'),
]
SEND_BUTTON_LOCATORS = [
    lambda p: p.locator('div[role="dialog"] [role="button"][aria-label="Send Message" i]'),
    lambda p: p.get_by_role("button", name="Send Message", exact=True),
    lambda p: p.locator('div[role="dialog"] [role="button"]:has-text("Send Message")'),
    lambda p: p.locator('div[role="dialog"] [role="button"]:has-text("Send")'),
]

_PROFILE_RATING_COMBINED_RE = re.compile(r"^(\d+\.\d+)\s*\((\d+)\)$")
_PROFILE_RATING_RE = re.compile(r"^\d+\.\d+$")
_PROFILE_REVIEW_COUNT_RE = re.compile(r"^\((\d+)\)$")
_PROFILE_JOINED_RE = re.compile(r"^Joined Facebook in (\d+)$")
_PROFILE_ACTIVE_LISTINGS_RE = re.compile(r"^(\d+)\s+active listings?$")
_PROFILE_STRENGTH_RE = re.compile(r"^(.+?)\s*\((\d+)\)$")
_PROFILE_DATE_RE = re.compile(r"^\d{1,2}\s+[A-Za-z]+\s+\d{4}$")
_PROFILE_STARS_ARIA_RE = re.compile(r"(\d+(?:\.\d+)?)\s+out of\s+5\s+stars", re.IGNORECASE)
_PROFILE_PRICE_RE = re.compile(r"^(AU\$|A\$|\$|€|£|R\$|CA\$|US\$|NZ\$|₹)", re.IGNORECASE)
_PROFILE_LOCATION_RE = re.compile(r",\s*[A-Z]{2,4}\s*$")
_PROFILE_ACTION_LINES = {
    "Follow",
    "Following",
    "Message",
    "View profile",
    "Visit website",
    "See store",
    "Join group",
}
_PROFILE_LISTING_SKIP_LINES = {
    "Available and in stock",
    "Sort by",
    "See more",
    "See all",
    "Filters",
}
_PROFILE_BADGE_SKIP_LINES = {"See badge details"}
_PROFILE_BADGE_INTRO_RE = re.compile(r"^Based on .+ activity on Marketplace$", re.IGNORECASE)


def marketplace_url(value: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        return value
    target = value.strip().lstrip("/")
    if target.startswith("marketplace/"):
        return f"{FACEBOOK_BASE_URL}/{target}"
    if target.startswith("item/") or target.startswith("profile/"):
        return f"{FACEBOOK_BASE_URL}/marketplace/{target}"
    if target.isdigit():
        return f"{FACEBOOK_BASE_URL}/marketplace/item/{target}"
    return f"{FACEBOOK_BASE_URL}/{target}"


def _marketplace_item_id(value: str) -> str:
    path = urlparse(value if value.startswith(("http://", "https://")) else f"{FACEBOOK_BASE_URL}/{value.strip().lstrip('/')}").path
    for segment in reversed(path.split("/")):
        if segment.isdigit():
            return segment
    return value


def read_item(session, item: str) -> dict:
    page = session.page
    url = marketplace_url(item)
    goto_domcontentloaded(page, url)
    _wait_for_marketplace_item(page)
    session.wait()
    data = _marketplace_item_data(page)
    data.update({"item": _marketplace_item_id(item), "url": page.url})
    return data


def read_seller(session, item_or_profile: str) -> dict:
    page = session.page
    url = marketplace_url(item_or_profile)
    goto_domcontentloaded(page, url)
    session.wait()

    if _is_marketplace_item_url(page.url):
        item_data = _marketplace_item_data(page)
        seller = item_data.get("seller") or {}
        if seller.get("profile_url"):
            goto_domcontentloaded(page, seller["profile_url"])
            session.wait()
            return {
                "item": item_or_profile,
                "seller": seller,
                "profile": _marketplace_profile_data(page),
                "url": page.url,
            }
        return {"item": item_or_profile, "url": page.url, "seller": seller}

    return {"target": item_or_profile, "url": page.url, **_marketplace_profile_data(page)}


def message_seller(session, item: str, text: str, *, dry_run: bool = False) -> dict:
    page = session.page
    goto_domcontentloaded(page, marketplace_url(item))
    _wait_for_marketplace_item(page)
    session.wait()
    pin_unlocked = _maybe_unlock_messenger(session)
    if dry_run:
        chat_opened = _try_open_seller_chat(page, session)
        textbox = first_visible(page, CHAT_TEXTBOX_LOCATORS, timeout_ms=2500)
        return {
            "sent": False,
            "dry_run": True,
            "item": _marketplace_item_id(item),
            "text": text,
            "would_send": text,
            "url": page.url,
            "thread_url": _current_thread_url(page),
            "chat_opened": chat_opened,
            "composer_found": textbox is not None,
            "suggested_message": _textbox_text(textbox) if textbox is not None else _suggested_message_text(page),
            "visible_message_texts": _visible_message_ui_texts(page),
            "pin_unlocked": pin_unlocked,
            "pin_status": "unlocked_with_env_pin" if pin_unlocked else "not_required",
        }
    _open_seller_chat(page, session)
    textbox = require_visible(page, CHAT_TEXTBOX_LOCATORS, label="seller message textbox", timeout_ms=10000)
    human_fill(textbox, text)
    send_button = first_visible(page, SEND_BUTTON_LOCATORS, timeout_ms=1000)
    if send_button is not None:
        send_button.click()
    else:
        textbox.press("Enter")
    session.wait(1.0, 2.0)
    return {
        "sent": True,
        "item": _marketplace_item_id(item),
        "text": text,
        "url": page.url,
        "thread_url": _current_thread_url(page),
        "pin_unlocked": pin_unlocked,
        "pin_status": "unlocked_with_env_pin" if pin_unlocked else "not_required",
    }


def read_seller_messages(session, item: str, *, limit: int = 20) -> dict:
    page = session.page
    goto_domcontentloaded(page, marketplace_url(item))
    _wait_for_marketplace_item(page)
    session.wait()
    pin_unlocked = _maybe_unlock_messenger(session)
    _open_seller_chat(page, session)
    messages = _visible_marketplace_messages(page, limit=limit)
    return {
        "item": _marketplace_item_id(item),
        "url": page.url,
        "thread_url": _current_thread_url(page),
        "pin_unlocked": pin_unlocked,
        "pin_status": "unlocked_with_env_pin" if pin_unlocked else "not_required",
        "messages": messages,
    }


def _wait_for_marketplace_item(page) -> None:
    try:
        page.wait_for_selector('a[href*="/marketplace/profile/"], [role="main"]', timeout=12000)
    except PlaywrightError:
        pass


def _is_marketplace_item_url(url: str) -> bool:
    return urlparse(url).path.rstrip("/").startswith("/marketplace/item/")


def _marketplace_item_data(page) -> dict:
    data = _marketplace_page_data(page)
    all_lines = data.get("main_lines") or []
    lines = _listing_lines(all_lines)
    seller = _seller_from_links(data.get("links") or [])
    seller = _seller_from_lines(all_lines, seller)
    result = {
        "title": _first_heading(data) or _best_line(lines, skip_price=True),
        "price": _first_price_line(lines),
        "seller": seller,
        "details": lines,
    }
    description = _description_from_lines(lines, result.get("title"), result.get("price"))
    if description:
        result["description"] = description
    images = _listing_images(data.get("images") or [])
    if images:
        result["images"] = images
    result = {key: value for key, value in result.items() if value}
    messaged = _messaged_from_lines(all_lines)
    if messaged is not None:
        result["messaged"] = messaged
    return result


def _marketplace_profile_data(page) -> dict:
    dialog = _marketplace_profile_dialog(page)
    if dialog is None:
        data = _marketplace_page_data(page)
        lines = data.get("main_lines") or []
        name = _seller_profile_name(data, lines)
        result = {
            "profile_url": page.url,
            "profile_available": bool(name),
        }
        if name:
            result["name"] = name
        if lines:
            result["details"] = lines
        if data.get("links"):
            result["links"] = data["links"]
        return result

    data = _dialog_data(dialog)
    return _parse_seller_profile_modal(data, page.url)


def _marketplace_profile_dialog(page):
    """Return the visible Marketplace seller-profile modal dialog locator, or None."""
    try:
        page.wait_for_selector('div[role="dialog"]', state="attached", timeout=8000)
    except PlaywrightError:
        return None
    try:
        page.wait_for_function(
            r"""
            () => {
              const dialogs = Array.from(document.querySelectorAll('div[role="dialog"]'));
              return dialogs.some(d => {
                const rect = d.getBoundingClientRect();
                if (rect.width < 200 || rect.height < 200) return false;
                const text = d.innerText || '';
                return text.includes("'s listings") || text.includes('Joined Facebook') || text.includes('Rating and strengths') || text.includes('Reviews of ');
              });
            }
            """,
            timeout=8000,
        )
    except PlaywrightError:
        pass
    dialogs = page.locator('div[role="dialog"]')
    try:
        count = dialogs.count()
    except PlaywrightError:
        return None
    fallback = None
    for i in range(count):
        d = dialogs.nth(i)
        try:
            box = d.bounding_box()
        except PlaywrightError:
            continue
        if not box or box["width"] < 200 or box["height"] < 200:
            continue
        try:
            text = d.inner_text(timeout=1500)
        except PlaywrightError:
            text = ""
        if any(marker in text for marker in ("'s listings", "Joined Facebook", "Rating and strengths", "Reviews of ")):
            return d
        if fallback is None:
            fallback = d
    return fallback


def _dialog_data(dialog) -> dict:
    try:
        return dialog.evaluate(
            r"""
            el => {
              const cleanLines = text => (text || '')
                .split(String.fromCharCode(10))
                .map(line => line.replace(/\s+/g, ' ').trim())
                .filter(Boolean);
              const seenLinks = new Set();
              const links = Array.from(el.querySelectorAll('a[href]')).map(link => {
                const href = link.href || '';
                const text = cleanLines(link.innerText || link.textContent).join(' ') || link.getAttribute('aria-label') || '';
                return { text, href };
              }).filter(link => {
                if (!link.href || seenLinks.has(link.href)) return false;
                seenLinks.add(link.href);
                return true;
              });
              const seenImages = new Set();
              const images = Array.from(el.querySelectorAll('img[src]')).map(img => ({
                alt: img.alt || '',
                src: img.src || '',
              })).filter(img => {
                if (!img.src || img.src.startsWith('data:') || img.src.includes('static.xx.fbcdn.net') || seenImages.has(img.src)) return false;
                seenImages.add(img.src);
                return true;
              });
              const starRatings = Array.from(el.querySelectorAll('[aria-label*="out of 5 stars" i]'))
                .map(node => {
                  const aria = node.getAttribute('aria-label') || '';
                  const rect = node.getBoundingClientRect();
                  return { aria, visible: rect.width > 0 && rect.height > 0 };
                })
                .filter(s => s.visible && !/average/i.test(s.aria))
                .map(s => s.aria);
              return {
                headings: Array.from(el.querySelectorAll('h1, h2, h3, h4, span[role="heading"]')).map(node => cleanLines(node.innerText || node.textContent).join(' ')).filter(Boolean),
                main_lines: cleanLines(el.innerText || el.textContent),
                links,
                images,
                star_ratings: starRatings,
              };
            }
            """
        )
    except PlaywrightError:
        return {"headings": [], "main_lines": [], "links": [], "images": [], "star_ratings": []}


def _profile_section_kind(heading: str) -> str | None:
    if heading == "Badge":
        return "badge"
    if heading == "Rating and strengths":
        return "rating"
    if heading == "About":
        return "about"
    if heading.startswith("Reviews of "):
        return "reviews"
    if heading.endswith("listings") and "'s " in heading:
        return "listings"
    return None


def _parse_seller_profile_modal(data: dict, url: str) -> dict:
    lines = data.get("main_lines") or []
    headings = data.get("headings") or []
    links = data.get("links") or []
    star_ratings = data.get("star_ratings") or []

    section_marks = []
    for heading in headings:
        kind = _profile_section_kind(heading)
        if not kind:
            continue
        for idx, line in enumerate(lines):
            if line == heading:
                section_marks.append((idx, kind, heading))
                break
    section_marks.sort(key=lambda t: t[0])

    header_end = section_marks[0][0] if section_marks else len(lines)
    header_lines = lines[:header_end]

    sections: dict[str, list[str]] = {}
    for i, (idx, kind, _heading) in enumerate(section_marks):
        end = section_marks[i + 1][0] if i + 1 < len(section_marks) else len(lines)
        sections[kind] = lines[idx + 1 : end]

    result: dict = {"profile_url": url, "profile_available": False}

    name = None
    rating = None
    review_count = None
    for line in header_lines:
        m = _PROFILE_RATING_COMBINED_RE.match(line)
        if m:
            rating = float(m.group(1))
            review_count = int(m.group(2))
            continue
        if _PROFILE_JOINED_RE.match(line) or _PROFILE_ACTIVE_LISTINGS_RE.match(line) or line in _PROFILE_ACTION_LINES:
            continue
        if name is None:
            name = line

    if name:
        result["name"] = name
        result["profile_available"] = True
    if rating is not None:
        result["rating"] = rating
    if review_count is not None:
        result["review_count"] = review_count

    facebook_profile_url = None
    for link in links:
        href = clean_url(link.get("href") or "")
        if not href:
            continue
        path = urlparse(href).path
        if link.get("text") == "View profile" or path.startswith("/profile.php") or path.startswith("/people/"):
            facebook_profile_url = href
            break
    if facebook_profile_url:
        result["facebook_profile_url"] = facebook_profile_url

    badges = _parse_profile_badges(sections.get("badge") or [])
    if badges:
        result["badges"] = badges

    strengths = _parse_profile_strengths(sections.get("rating") or [], rating, review_count)
    if strengths:
        result["strengths"] = strengths
    if rating is None or review_count is None:
        for line in sections.get("rating") or []:
            if _PROFILE_RATING_RE.match(line) and rating is None:
                rating = float(line)
                result["rating"] = rating
            m = _PROFILE_REVIEW_COUNT_RE.match(line)
            if m and review_count is None:
                review_count = int(m.group(1))
                result["review_count"] = review_count

    reviews = _parse_profile_reviews(sections.get("reviews") or [], star_ratings)
    if reviews:
        result["reviews"] = reviews

    listings = _parse_profile_listings(sections.get("listings") or [], links)
    if listings:
        result["listings"] = listings

    return result


def _parse_profile_badges(badge_lines: list[str]) -> list[dict]:
    badges: list[dict] = []
    current_name = None
    for line in badge_lines:
        if line in _PROFILE_BADGE_SKIP_LINES or _PROFILE_BADGE_INTRO_RE.match(line):
            continue
        lowered = line.casefold()
        if "rating from" in lowered or "-star" in lowered or "based on" in lowered:
            if current_name is not None:
                badges.append({"name": current_name, "description": line})
                current_name = None
            else:
                badges.append({"description": line})
        else:
            if current_name is not None:
                badges.append({"name": current_name})
            current_name = line
    if current_name is not None:
        badges.append({"name": current_name})
    return badges


def _parse_profile_strengths(rating_lines: list[str], rating, review_count) -> list[dict]:
    strengths: list[dict] = []
    for line in rating_lines:
        if _PROFILE_RATING_RE.match(line):
            continue
        if _PROFILE_REVIEW_COUNT_RE.match(line):
            continue
        if line.endswith("'s strengths") or line == "Strengths":
            continue
        m = _PROFILE_STRENGTH_RE.match(line)
        if m:
            strengths.append({"name": m.group(1).strip(), "count": int(m.group(2))})
    return strengths


def _parse_profile_reviews(review_lines: list[str], star_ratings: list[str] | None = None) -> list[dict]:
    reviews: list[dict] = []
    i = 0
    n = len(review_lines)
    while i < n:
        line = review_lines[i]
        if _PROFILE_DATE_RE.match(line) and i > 0:
            reviewer = review_lines[i - 1]
            date = line
            notable: list[str] = []
            j = i + 1
            while j < n and review_lines[j] != "Like":
                if review_lines[j] == "Notable:":
                    j += 1
                    continue
                notable.append(review_lines[j].lstrip("· ").strip())
                j += 1
            if j < n and review_lines[j] == "Like":
                j += 1
                if j < n and review_lines[j].isdigit():
                    j += 1
            entry: dict = {"reviewer": reviewer, "date": date}
            if notable:
                entry["notable"] = notable
            reviews.append(entry)
            i = j
        else:
            i += 1

    if star_ratings:
        for idx, review in enumerate(reviews):
            if idx < len(star_ratings):
                m = _PROFILE_STARS_ARIA_RE.search(star_ratings[idx])
                if m:
                    value = float(m.group(1))
                    review["rating"] = int(value) if value.is_integer() else value
    return reviews


def _is_profile_price_line(line: str) -> bool:
    if line.casefold() == "free":
        return True
    if _PROFILE_PRICE_RE.match(line):
        return True
    return "$" in line[:8] or "€" in line[:8] or "£" in line[:8]


def _parse_profile_listings(listing_lines: list[str], links: list[dict]) -> list[dict]:
    listings: list[dict] = []
    current: dict | None = None
    for line in listing_lines:
        if line in _PROFILE_LISTING_SKIP_LINES:
            continue
        if _is_profile_price_line(line):
            if current is not None and current.get("title"):
                listings.append(current)
                current = None
            if current is None:
                current = {"price": line}
            elif "original_price" not in current:
                current["original_price"] = line
            continue
        if _PROFILE_LOCATION_RE.search(line):
            if current is not None and "location" not in current:
                current["location"] = line
            continue
        if current is None:
            current = {}
        if "title" not in current:
            current["title"] = line
        elif "location" not in current:
            current["title"] = current["title"] + " " + line
    if current is not None and current.get("title"):
        listings.append(current)

    for listing in listings:
        title = listing.get("title") or ""
        for link in links:
            href = clean_url(link.get("href") or "")
            if not href or "/marketplace/item/" not in urlparse(href).path:
                continue
            if title and title in (link.get("text") or ""):
                listing["url"] = href
                break
    return listings


def _marketplace_seller(page) -> dict:
    return _seller_from_links((_marketplace_page_data(page).get("links") or []))


def _marketplace_page_data(page) -> dict:
    try:
        return page.evaluate(
            r"""
            () => {
              const cleanLines = text => (text || '')
                .split(String.fromCharCode(10))
                .map(line => line.replace(/\s+/g, ' ').trim())
                .filter(Boolean);
              const main = document.querySelector('[role="main"]') || document.body;
              const seenLinks = new Set();
              const links = Array.from(main.querySelectorAll('a[href]')).map(link => {
                const href = link.href || '';
                const text = cleanLines(link.innerText || link.textContent).join(' ') || link.getAttribute('aria-label') || '';
                return { text, href };
              }).filter(link => {
                if (!link.href || seenLinks.has(link.href)) return false;
                seenLinks.add(link.href);
                return true;
              });
              const seenImages = new Set();
              const images = Array.from(main.querySelectorAll('img[src]')).map(img => ({
                alt: img.alt || '',
                src: img.src || '',
              })).filter(img => {
                if (!img.src || img.src.startsWith('data:') || img.src.includes('static.xx.fbcdn.net') || seenImages.has(img.src)) return false;
                seenImages.add(img.src);
                return true;
              });
              return {
                title: document.title || '',
                headings: Array.from(main.querySelectorAll('h1, h2')).map(node => cleanLines(node.innerText || node.textContent).join(' ')).filter(Boolean),
                main_lines: cleanLines(main.innerText || main.textContent),
                links,
                images,
              };
            }
            """
        )
    except PlaywrightError:
        return {"main_lines": [], "links": [], "images": [], "headings": []}


def _seller_from_links(links: list[dict]) -> dict:
    for link in links:
        href = clean_url(link.get("href"))
        if not href:
            continue
        path = urlparse(href).path.rstrip("/")
        if not path.startswith("/marketplace/profile/"):
            continue
        name = " ".join((link.get("text") or "").split())
        seller = {"profile_url": href}
        if name and name.casefold() not in {"seller details", "seller information", "view seller profile"}:
            seller["name"] = name
        return seller
    return {}


def _seller_from_lines(lines: list[str], seller: dict) -> dict:
    if seller.get("name"):
        return seller
    for marker in ("Seller details", "Seller information"):
        try:
            index = lines.index(marker)
        except ValueError:
            continue
        for candidate in lines[index + 1 : index + 5]:
            value = " ".join(candidate.split())
            if not value or value.startswith("(") or "rated on Marketplace" in value or value.startswith("Joined Facebook"):
                continue
            return {**seller, "name": value}
    return seller


def _listing_lines(lines: list[str]) -> list[str]:
    stop_markers = {
        "Sponsored",
        "Seller information",
        "Seller details",
        "Send seller a message",
        "Today's picks",
        "Related items",
        "More from seller",
    }
    skip_markers = {
        "Message",
        "Message again",
        "Details",
    }
    out = []
    for line in lines:
        value = " ".join(line.split())
        if value in stop_markers:
            break
        if value in skip_markers:
            continue
        out.append(value)
    return out


def _messaged_from_lines(lines: list[str]) -> bool | None:
    normalized = [" ".join(line.split()) for line in lines]
    if "Message again" in normalized:
        return True
    if "Message" in normalized:
        return False
    return None


def _listing_images(images: list[dict]) -> list[dict]:
    out = []
    for image in images:
        alt = image.get("alt") or ""
        src = image.get("src") or ""
        if not src or src.endswith("/images/video/play_48dp.png"):
            continue
        if not alt:
            continue
        if " in Melbourne," in alt or " in " in alt and alt.startswith(("Mtb ", "Gaming ", "DELL ", "Tesla ", "Porsche ", "MacBook ", "Dell ", "Keychron ")):
            continue
        out.append(image)
        if len(out) >= 8:
            break
    return out


def _seller_profile_name(data: dict, lines: list[str]) -> str | None:
    ignored = {"marketplace", "today's picks", "seller details", "seller information"}
    for heading in data.get("headings") or []:
        value = " ".join(heading.split())
        if value and value.casefold() not in ignored:
            return value
    for marker in ("Seller details", "Seller information"):
        try:
            index = lines.index(marker)
        except ValueError:
            continue
        for candidate in lines[index + 1 : index + 5]:
            value = " ".join(candidate.split())
            if value and value.casefold() not in ignored and not value.startswith("("):
                return value
    return None


def _first_heading(data: dict) -> str | None:
    for heading in data.get("headings") or []:
        if heading and heading.casefold() != "marketplace":
            return heading
    return None


def _first_price_line(lines: list[str]) -> str | None:
    for line in lines:
        if line.casefold() == "free" or line.startswith("$") or "$" in line[:8]:
            return line
    return None


def _best_line(lines: list[str], *, skip_price: bool = False) -> str | None:
    ignored = {"marketplace", "seller details", "details", "description", "send seller a message"}
    for line in lines:
        value = " ".join(line.split())
        if not value or value.casefold() in ignored:
            continue
        if skip_price and _first_price_line([value]) == value:
            continue
        return value
    return None


def _description_from_lines(lines: list[str], title: str | None, price: str | None) -> str | None:
    markers = {"description", "seller's description"}
    for index, line in enumerate(lines):
        if line.casefold() in markers:
            tail = [value for value in lines[index + 1 :] if value not in {title, price}]
            return "\n".join(tail[:8]) or None
    return None


def _open_seller_chat(page, session) -> None:
    if first_visible(page, CHAT_TEXTBOX_LOCATORS, timeout_ms=500) is not None:
        return
    button = require_visible(page, CHAT_BUTTON_LOCATORS, label="seller message button", timeout_ms=10000)
    button.click()
    session.wait(1.0, 2.0)
    require_visible(page, CHAT_TEXTBOX_LOCATORS, label="seller message textbox", timeout_ms=10000)


def _try_open_seller_chat(page, session) -> bool:
    if first_visible(page, CHAT_TEXTBOX_LOCATORS, timeout_ms=500) is not None:
        return True
    button = first_visible(page, CHAT_BUTTON_LOCATORS, timeout_ms=5000)
    if button is None:
        return False
    try:
        button.click()
    except PlaywrightError:
        return False
    session.wait(1.0, 2.0)
    return True


def _textbox_text(locator) -> str | None:
    value = visible_text(locator)
    if value:
        return value
    try:
        value = locator.input_value(timeout=1000)
    except PlaywrightError:
        value = None
    return value or None


def _suggested_message_text(page) -> str | None:
    candidates = _visible_message_ui_texts(page)
    for text in candidates:
        lowered = text.casefold()
        if "available" in lowered or "still" in lowered or "interested" in lowered:
            return text
    return None


def _visible_message_ui_texts(page) -> list[str]:
    try:
        return page.evaluate(
            r"""
            () => {
              const clean = text => (text || '').replace(/\s+/g, ' ').trim();
              const visible = node => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width > 0 && rect.height > 0 && rect.bottom >= 0 && rect.top <= window.innerHeight;
              };
              const roots = Array.from(document.querySelectorAll('div[role="dialog"], [aria-label*="message" i], [aria-label*="chat" i], [role="main"]'))
                .filter(node => visible(node) && /message|send|available|interested|chat/i.test(clean(node.innerText || node.textContent)));
              const root = roots[0];
              if (!root) return [];
              const seen = new Set();
              const out = [];
              for (const node of Array.from(root.querySelectorAll('div, span, textarea, [role="button"], [role="textbox"]'))) {
                if (!visible(node)) continue;
                const text = clean(node.innerText || node.textContent || node.value || node.getAttribute('aria-label') || '');
                if (!text || text.length > 240 || seen.has(text)) continue;
                seen.add(text);
                out.push(text);
              }
              return out.slice(0, 30);
            }
            """
        )
    except PlaywrightError:
        return []


def _maybe_unlock_messenger(session) -> bool:
    try:
        return ensure_messenger_unlocked(session)
    except PlaywrightError:
        return False


def _current_thread_url(page) -> str | None:
    try:
        href = page.locator('a[href*="/messages/t/"], a[href*="/messages/e2ee/t/"]').first
        url = clean_url(safe_attr(href, "href"))
    except PlaywrightError:
        return None
    if not url:
        return None
    path = urlparse(url).path.rstrip("/")
    if path in {"/messages/t", "/messages/e2ee/t"}:
        return None
    return url


def _visible_marketplace_messages(page, *, limit: int) -> list[dict]:
    try:
        items = page.evaluate(
            r"""
            (limit) => {
              const clean = text => (text || '').replace(/\s+/g, ' ').trim();
              const visible = node => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width > 0 && rect.height > 0;
              };
              const roots = Array.from(document.querySelectorAll('div[role="dialog"], [aria-label*="conversation" i], [aria-label*="chat" i], [role="log"]'))
                .filter(node => visible(node) && clean(node.innerText || node.textContent));
              const root = roots.find(node => node.querySelector('[contenteditable="true"], textarea, [data-testid="message-container"], [role="row"]'));
              if (!root) return [];
              const chrome = /^(Message|Send|Marketplace|Details|Description|Seller details|Type a message|Attach a file|Choose a sticker|Choose an emoji)$/i;
              const seen = new Set();
              const messages = [];
              for (const node of Array.from(root.querySelectorAll('[data-testid="message-container"], [role="row"], div[dir="auto"], span[dir="auto"]'))) {
                if (!visible(node) || node.closest('[contenteditable="true"], input, textarea, [role="button"], button')) continue;
                const text = clean(node.innerText || node.textContent);
                if (!text || text.length < 2 || chrome.test(text) || seen.has(text)) continue;
                const children = Array.from(node.children || []).filter(visible);
                if (children.some(child => clean(child.innerText || child.textContent) === text)) continue;
                seen.add(text);
                const rect = node.getBoundingClientRect();
                messages.push({ text, direction: rect.left > window.innerWidth * 0.55 ? 'outgoing' : 'incoming', top: rect.top, left: rect.left });
              }
              return messages
                .sort((a, b) => a.top - b.top || a.left - b.left)
                .slice(-limit)
                .map(({ text, direction }) => ({ text, direction }));
            }
            """,
            limit,
        )
    except PlaywrightError:
        return []
    return items or []
