from __future__ import annotations

import os
import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from facebook_cli.browser import first_visible, human_fill, require_visible, safe_attr, visible_text
from facebook_cli.actions.extract import clean_url
from facebook_cli.conf import FACEBOOK_BASE_URL
from facebook_cli.exceptions import MessengerPinRequiredError

MESSAGES_URL = f"{FACEBOOK_BASE_URL}/messages"

THREAD_LOCATORS = [
    lambda p: p.locator('a[href*="/messages/t/"][role="link"]'),
    lambda p: p.locator('a[href*="/messages/e2ee/t/"][role="link"]'),
]
MESSAGE_LOCATORS = [
    lambda p: p.locator('[aria-label*="Messages in conversation" i] [data-testid="message-container"]'),
    lambda p: p.locator('[aria-label*="Messages in conversation" i] div[role="row"]'),
    lambda p: p.locator('[data-testid="message-container"]'),
    lambda p: p.locator('div[role="row"]'),
    lambda p: p.locator('div[dir="auto"]'),
]
SEARCH_LOCATORS = [
    lambda p: p.get_by_placeholder("Search Messenger"),
    lambda p: p.get_by_placeholder("Search"),
    lambda p: p.locator('input[aria-label*="Search" i]'),
    lambda p: p.locator('div[role="textbox"][aria-label*="Search" i]'),
]
COMPOSER_LOCATORS = [
    lambda p: p.locator('div[role="textbox"][contenteditable="true"][aria-label*="Message" i]'),
    lambda p: p.locator('div[role="textbox"][contenteditable="true"]'),
]
PIN_INPUT_LOCATORS = [
    lambda p: p.locator('div[role="dialog"] input[type="password"]'),
    lambda p: p.locator('div[role="dialog"] input[inputmode="numeric"]'),
    lambda p: p.locator('input[type="password"]'),
    lambda p: p.locator('input[inputmode="numeric"]'),
    lambda p: p.locator('input[autocomplete="one-time-code"]'),
    lambda p: p.get_by_label("PIN"),
    lambda p: p.get_by_label("pin"),
    lambda p: p.get_by_placeholder("PIN"),
    lambda p: p.locator('input[aria-label*="PIN" i]'),
    lambda p: p.locator('input[aria-label*="code" i]'),
]
PIN_DIALOG_LOCATORS = [
    lambda p: p.locator('div[role="dialog"]:has-text("PIN")'),
    lambda p: p.locator('div[role="dialog"]:has-text("pin")'),
    lambda p: p.locator('div[role="dialog"]:has-text("code")'),
    lambda p: p.locator('div[role="dialog"]:has-text("end-to-end encrypted")'),
    lambda p: p.locator('div[role="dialog"]:has(input[type="password"])'),
    lambda p: p.locator('div[role="dialog"]:has(input[inputmode="numeric"])'),
]
PIN_SUBMIT_LOCATORS = [
    lambda p: p.locator('div[role="dialog"] [role="button"]:has-text("Continue")'),
    lambda p: p.locator('div[role="dialog"] [role="button"]:has-text("Submit")'),
    lambda p: p.locator('div[role="dialog"] [role="button"]:has-text("Confirm")'),
    lambda p: p.locator('div[role="dialog"] button:has-text("Continue")'),
    lambda p: p.locator('div[role="dialog"] button:has-text("Submit")'),
    lambda p: p.locator('div[role="dialog"] button:has-text("Confirm")'),
    lambda p: p.get_by_role("button", name="Continue"),
    lambda p: p.get_by_role("button", name="Submit"),
    lambda p: p.get_by_role("button", name="Confirm"),
    lambda p: p.locator('div[role="button"]:has-text("Continue")'),
    lambda p: p.locator('div[role="button"]:has-text("Submit")'),
]


def _messages_url(value: str | None = None) -> str:
    if not value:
        return MESSAGES_URL
    if value.startswith("http://") or value.startswith("https://"):
        return value
    target = value.strip().lstrip("/")
    if target.startswith("messages/"):
        return f"{FACEBOOK_BASE_URL}/{target}"
    return f"{FACEBOOK_BASE_URL}/messages/t/{target}"


def list_threads(session, *, limit: int = 10) -> dict:
    page = session.page
    page.goto(MESSAGES_URL)
    page.wait_for_load_state("domcontentloaded")
    session.wait()
    pin_unlocked = ensure_messenger_unlocked(session)
    return {"url": page.url, "pin_unlocked": pin_unlocked, "threads": _visible_threads(page, limit=limit)}


def read_thread(session, target: str | None = None, *, limit: int = 20) -> dict:
    page = session.page
    page.goto(_messages_url(target))
    page.wait_for_load_state("domcontentloaded")
    session.wait()
    pin_unlocked = ensure_messenger_unlocked(session)
    _wait_for_conversation(page)
    _scroll_conversation_to_latest(page)
    session.wait(0.4, 0.8)
    return {"target": target, "url": page.url, "pin_unlocked": pin_unlocked, "messages": _visible_messages(page, limit=limit)}


def send_message(session, target: str, text: str) -> dict:
    page = session.page
    if target.startswith("http://") or target.startswith("https://") or target.startswith("messages/"):
        page.goto(_messages_url(target))
        page.wait_for_load_state("domcontentloaded")
        session.wait()
        pin_unlocked = ensure_messenger_unlocked(session)
    else:
        page.goto(MESSAGES_URL)
        page.wait_for_load_state("domcontentloaded")
        session.wait()
        pin_unlocked = ensure_messenger_unlocked(session)
        search = require_visible(page, SEARCH_LOCATORS, label="Messenger search", timeout_ms=8000)
        human_fill(search, target)
        session.wait(1.5, 2.5)
        result = require_visible(
            page,
            [lambda p: p.locator('a[href*="/messages/"][role="link"]'), lambda p: p.get_by_role("link", name=target)],
            label="Messenger search result",
            timeout_ms=8000,
        )
        result.click()
        page.wait_for_load_state("domcontentloaded")
        session.wait()

    composer = require_visible(page, COMPOSER_LOCATORS, label="message composer", timeout_ms=10000)
    human_fill(composer, text)
    composer.press("Enter")
    session.wait(1.0, 2.0)
    return {"sent": True, "target": target, "text": text, "url": page.url, "pin_unlocked": pin_unlocked}


def maybe_unlock_messenger_pin(session) -> bool:
    if not _pin_prompt_visible(session):
        return False

    pin = os.environ.get("FACEBOOK_CLI_MESSENGER_PIN")
    if not pin:
        return False

    page = session.page
    pin_input = first_visible(page, PIN_INPUT_LOCATORS, timeout_ms=1500)
    if pin_input is None:
        return False

    human_fill(pin_input, pin)
    submit = first_visible(page, PIN_SUBMIT_LOCATORS, timeout_ms=1500)
    if submit is not None:
        submit.click()
    else:
        pin_input.press("Enter")
    session.wait(1.5, 3.0)
    return True


def ensure_messenger_unlocked(session) -> bool:
    unlocked = maybe_unlock_messenger_pin(session)
    if _pin_prompt_visible(session):
        if os.environ.get("FACEBOOK_CLI_MESSENGER_PIN"):
            raise MessengerPinRequiredError("Messenger PIN prompt is still visible after submitting the configured PIN")
        raise MessengerPinRequiredError("Messenger PIN prompt is visible; set FACEBOOK_CLI_MESSENGER_PIN or unlock it manually")
    return unlocked


def _pin_prompt_visible(session) -> bool:
    page = session.page
    try:
        return bool(page.evaluate(
            r"""
            () => {
              const visible = (node) => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width > 0 && rect.height > 0;
              };
              const pinInputSelector = 'input[type="password"], input[autocomplete="one-time-code"], input[aria-label*="PIN" i], input[aria-label*="code" i], input[placeholder*="PIN" i], input[placeholder*="code" i]';
              return Array.from(document.querySelectorAll('div[role="dialog"]')).some((dialog) => {
                if (!visible(dialog)) return false;
                const text = (dialog.innerText || dialog.textContent || '').replace(/\s+/g, ' ').trim();
                if (!/(\bPIN\b|\bpin\b|\bcode\b|end-to-end encrypted)/i.test(text)) return false;
                return Array.from(dialog.querySelectorAll(pinInputSelector)).some(visible);
              });
            }
            """
        ))
    except PlaywrightError:
        pass
    return False


def _wait_for_conversation(page, *, timeout_ms: int = 12000) -> None:
    try:
        page.wait_for_function(
            r"""
            () => {
              const visible = (node) => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width > 0 && rect.height > 0;
              };
              const hasComposer = Array.from(document.querySelectorAll('div[role="textbox"][contenteditable="true"]'))
                .some((node) => visible(node) && /message/i.test(node.getAttribute('aria-label') || node.textContent || ''));
              const hasConversation = Array.from(document.querySelectorAll('[aria-label*="Messages in conversation" i], [role="main"]'))
                .some((node) => visible(node) && (node.innerText || node.textContent || '').trim().length > 0);
              return hasComposer || hasConversation;
            }
            """,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        return


def _scroll_conversation_to_latest(page) -> None:
    try:
        page.evaluate(
            r"""
            () => {
              const candidates = Array.from(document.querySelectorAll('[aria-label*="Messages in conversation" i], [role="main"], div'));
              const scrollables = candidates
                .filter((node) => {
                  const rect = node.getBoundingClientRect();
                  if (!rect || rect.width <= 0 || rect.height <= 0) return false;
                  if (rect.right < Math.min(Math.max(320, window.innerWidth * 0.28), 520)) return false;
                  return node.scrollHeight > node.clientHeight + 40;
                })
                .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
              for (const node of scrollables.slice(0, 3)) {
                node.scrollTop = node.scrollHeight;
              }
            }
            """
        )
    except PlaywrightError:
        return


def _visible_threads(page, *, limit: int) -> list[dict]:
    rich_threads = _visible_threads_from_dom(page, limit=limit)
    if rich_threads:
        return rich_threads

    threads = []
    seen = set()
    for factory in THREAD_LOCATORS:
        links = factory(page)
        try:
            count = min(links.count(), limit * 4)
        except PlaywrightError:
            continue
        for index in range(count):
            link = links.nth(index)
            href = clean_url(safe_attr(link, "href"))
            raw_text = visible_text(link)
            if not href or href in seen:
                continue
            seen.add(href)
            title = _thread_title(raw_text)
            threads.append(
                {
                    "title": title,
                    "preview": _thread_preview(raw_text, title),
                    "timestamp": _thread_timestamp(raw_text),
                    "unread": False,
                    "url": href,
                }
            )
            if len(threads) >= limit:
                return threads
    return threads


def _visible_threads_from_dom(page, *, limit: int) -> list[dict]:
    try:
        items = page.evaluate(
            r"""
            (limit) => {
              const links = Array.from(document.querySelectorAll('a[href*="/messages/t/"], a[href*="/messages/e2ee/t/"]'));
              const seen = new Set();
              const rows = [];
              for (const link of links) {
                const href = link.href;
                if (!href || seen.has(href)) continue;
                const rect = link.getBoundingClientRect();
                if (!rect || rect.width <= 0 || rect.height <= 0) continue;
                if (rect.left > Math.min(520, window.innerWidth * 0.45)) continue;
                if (rect.bottom < 0 || rect.top > window.innerHeight) continue;

                const raw = (link.innerText || link.textContent || '').replace(/\s+/g, ' ').trim();
                if (!raw) continue;
                seen.add(href);

                const aria = link.getAttribute('aria-label') || '';
                const parts = [];
                const partSeen = new Set();
                for (const node of Array.from(link.querySelectorAll('span, div'))) {
                  const nodeRect = node.getBoundingClientRect();
                  if (!nodeRect || nodeRect.width <= 0 || nodeRect.height <= 0) continue;
                  const text = (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim();
                  if (!text || text.length > 220 || partSeen.has(text)) continue;
                  if (raw !== text && raw.includes(text)) {
                    partSeen.add(text);
                    parts.push(text);
                  }
                }
                const weighted = Array.from(link.querySelectorAll('span, div')).map((node) => {
                  const nodeRect = node.getBoundingClientRect();
                  if (!nodeRect || nodeRect.width <= 0 || nodeRect.height <= 0) return null;
                  const text = (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim();
                  if (!text || text.length > 220) return null;
                  const weight = Number.parseInt(window.getComputedStyle(node).fontWeight, 10) || 400;
                  return { text, weight };
                }).filter(Boolean);
                const unread = weighted.some(({ text, weight }) => weight >= 600 && text !== raw && !/^\d+[mhdwy]$/.test(text));
                rows.push({ href, raw, aria, parts, unread, top: rect.top });
                if (rows.length >= limit) break;
              }
              return rows.sort((a, b) => a.top - b.top).map(({ href, raw, aria, parts, unread }) => ({ href, raw, aria, parts, unread }));
            }
            """,
            limit,
        )
    except PlaywrightError:
        return []

    threads = []
    seen = set()
    for item in items:
        href = clean_url(item.get("href"))
        raw_text = item.get("raw") or item.get("aria") or ""
        parts = _clean_thread_parts(item.get("parts") or [])
        if not href or href in seen:
            continue
        seen.add(href)
        title = _thread_title_from_parts(parts) or _thread_title(raw_text)
        threads.append(
            {
                "title": title,
                "preview": _thread_preview_from_parts(parts) or _thread_preview(raw_text, title),
                "timestamp": _thread_timestamp(raw_text),
                "unread": bool(item.get("unread")),
                "url": href,
            }
        )
    return threads


def _clean_thread_parts(parts: list[str]) -> list[str]:
    cleaned = []
    for part in parts:
        text = " ".join(str(part).split())
        if not text or text in cleaned:
            continue
        if any(existing and existing != text and text in existing for existing in cleaned):
            continue
        cleaned = [existing for existing in cleaned if existing not in text]
        cleaned.append(text)
    return cleaned


def _is_thread_time(text: str) -> bool:
    return bool(text) and text[-1:] in {"m", "h", "d", "w", "y"} and any(char.isdigit() for char in text)


def _thread_title_from_parts(parts: list[str]) -> str | None:
    for part in parts:
        if _is_thread_time(part) or part.lower().startswith("unread message:"):
            continue
        return part
    return None


def _thread_preview_from_parts(parts: list[str]) -> str | None:
    title = _thread_title_from_parts(parts)
    preview_parts = []
    for part in parts:
        if part == title or _is_thread_time(part):
            continue
        preview_parts.append(part.removeprefix("Unread message:").strip())
    return " · ".join(part for part in preview_parts if part) or None


def _thread_parts(text: str | None) -> list[str]:
    if not text:
        return []
    parts = [part.strip() for part in text.split("  ") if part.strip()]
    if len(parts) > 1:
        return parts
    return [part.strip() for part in text.split(" · ") if part.strip()]


def _thread_title(text: str | None) -> str | None:
    parts = _thread_parts(text)
    return parts[0] if parts else None


def _thread_timestamp(text: str | None) -> str | None:
    parts = _thread_parts(text)
    if parts and _is_thread_time(parts[-1]):
        return parts[-1]
    return None


def _thread_preview(text: str | None, title: str | None = None) -> str | None:
    if not text:
        return None
    preview = " ".join(text.split())
    if title and preview.startswith(title):
        preview = preview[len(title):].strip()
    timestamp = _thread_timestamp(text)
    if timestamp and preview.endswith(f"· {timestamp}"):
        preview = preview[: -len(f"· {timestamp}")].strip()
    preview = preview.removeprefix("Unread message:").strip()
    return preview or None


def _visible_messages(page, *, limit: int) -> list[dict]:
    deadline = time.monotonic() + 5
    while True:
        pane_messages = _visible_conversation_pane_messages(page, limit=limit)
        if pane_messages or time.monotonic() >= deadline:
            break
        page.wait_for_timeout(300)

    if pane_messages:
        return pane_messages

    messages = []
    seen = set()
    for factory in MESSAGE_LOCATORS:
        locators = factory(page)
        try:
            count = min(locators.count(), limit * 6)
        except PlaywrightError:
            continue
        start = max(0, count - limit * 3)
        for index in range(start, count):
            locator = locators.nth(index)
            text = visible_text(locator)
            if not text or text in seen:
                continue
            seen.add(text)
            messages.append({"text": text})
            if len(messages) >= limit:
                return messages
        if messages:
            return messages[-limit:]
    return messages[-limit:]


def _visible_conversation_pane_messages(page, *, limit: int) -> list[dict]:
    try:
        return page.evaluate(
            r"""
            (limit) => {
              const minX = Math.min(Math.max(320, window.innerWidth * 0.28), 520);
              const isVisible = (node) => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width > 0 && rect.height > 0 && rect.bottom >= 0 && rect.top <= window.innerHeight;
              };
              const textOf = (node) => (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim();
              const parseAriaLabel = (value) => {
                const label = (value || '').replace(/\s+/g, ' ').trim();
                const match = label.match(/^At\s+(.+),\s+([^:,]+):\s*(.+)$/);
                if (!match) return null;
                return { datetime: match[1], sender: match[2], text: match[3] };
              };
              const chromeText = /^(Chats|Search Messenger|Marketplace|Sponsored|Active now|People|Communities|Message|Type a message|Send|Like|Attach a file|Choose a sticker|Choose a GIF|Choose an emoji|Voice clip|More actions)$/i;
              const timestampText = /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)(day)?\s+\d{1,2}:\d{2}$|^(Today|Yesterday)\s+\d{1,2}:\d{2}$|^\d{1,2}:\d{2}$|^\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(\s+\d{1,2}:\d{2})?$/i;
              const roots = Array.from(document.querySelectorAll('[aria-label*="Messages in conversation" i], [role="log"], [role="main"]'))
                .filter((node) => {
                  if (!isVisible(node)) return false;
                  const rect = node.getBoundingClientRect();
                  if (rect.right < minX || rect.width < 120 || rect.height < 120) return false;
                  return textOf(node).length > 0;
                })
                .sort((a, b) => {
                  const aRect = a.getBoundingClientRect();
                  const bRect = b.getBoundingClientRect();
                  const aScore = (a.getAttribute('aria-label') || '').match(/Messages in conversation/i) ? 1_000_000 : 0;
                  const bScore = (b.getAttribute('aria-label') || '').match(/Messages in conversation/i) ? 1_000_000 : 0;
                  return (bScore + bRect.width * bRect.height) - (aScore + aRect.width * aRect.height);
                });
              const root = roots[0];
              if (!root) return [];

              const timestampNodes = Array.from(root.querySelectorAll('span, div'))
                .map((node) => {
                  if (!isVisible(node)) return null;
                  const text = textOf(node);
                  if (!text) return null;
                  const className = String(node.className || '');
                  if (!timestampText.test(text) && !(className.includes('x186z157') && className.includes('xk50ysn'))) return null;
                  const rect = node.getBoundingClientRect();
                  return { text, top: rect.top, left: rect.left };
                })
                .filter(Boolean)
                .sort((a, b) => a.top - b.top || a.left - b.left);

              const selectors = [
                '[data-testid="message-container"]',
                '[role="row"]',
                '[dir="auto"]',
                'span[dir="auto"]',
                'div[aria-label]'
              ];
              const nodes = Array.from(root.querySelectorAll(selectors.join(',')));
              const seen = new Set();
              const items = [];
              for (const node of nodes) {
                const rect = node.getBoundingClientRect();
                if (!rect || rect.width <= 0 || rect.height <= 0) continue;
                if (rect.right < minX) continue;
                if (rect.bottom < 0 || rect.top > window.innerHeight) continue;
                if (node.closest('[contenteditable="true"], input, textarea, [role="button"], button, nav, header')) continue;
                if (node.closest('a[href*="/messages/t/"], a[href*="/messages/e2ee/t/"]')) continue;
                const rawText = textOf(node);
                if (!rawText || rawText.length < 2) continue;
                if (chromeText.test(rawText)) continue;
                if (timestampText.test(rawText)) continue;

                const visibleChildren = Array.from(node.children || []).filter(isVisible);
                if (visibleChildren.some((child) => textOf(child) === rawText)) continue;
                if (rawText.includes('Search Messenger') || rawText.startsWith('Chats ')) continue;
                const timestamp = timestampNodes
                  .filter((stamp) => stamp.top <= rect.top + 2)
                  .slice(-1)[0];
                const labelled = node.closest('[aria-label]');
                const ariaLabel = labelled ? (labelled.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim() : '';
                const parsedLabel = parseAriaLabel(ariaLabel);
                const text = parsedLabel && parsedLabel.text ? parsedLabel.text : rawText;
                const dedupeKey = ariaLabel || text;
                if (seen.has(dedupeKey)) continue;
                seen.add(dedupeKey);
                const direction = parsedLabel && parsedLabel.sender === 'You' ? 'outgoing' : (rect.left > window.innerWidth * 0.55 ? 'outgoing' : 'incoming');
                items.push({
                  text,
                  timestamp: timestamp ? timestamp.text : (parsedLabel ? parsedLabel.datetime : null),
                  datetime: parsedLabel ? parsedLabel.datetime : null,
                  sender: parsedLabel ? parsedLabel.sender : null,
                  direction,
                  aria_label: ariaLabel && ariaLabel !== text && ariaLabel.length < 240 ? ariaLabel : null,
                  top: rect.top,
                  left: rect.left,
                });
              }
              return items
                .sort((a, b) => a.top - b.top || a.left - b.left)
                .slice(-limit)
                .map(({ text, timestamp, datetime, sender, direction, aria_label }) => ({ text, timestamp, datetime, sender, direction, aria_label }));
            }
            """,
            limit,
        )
    except PlaywrightError:
        return []
