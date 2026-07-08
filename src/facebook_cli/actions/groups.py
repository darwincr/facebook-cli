from __future__ import annotations

import re

from playwright.sync_api import Error as PlaywrightError

from facebook_cli.actions.posts import group_url
from facebook_cli.browser import first_visible, goto_domcontentloaded, visible_text


def open_group(session, group: str) -> dict:
    page = session.page
    target_url = group_url(group)
    goto_domcontentloaded(page, target_url)
    session.wait()

    header = first_visible(
        page,
        [
            lambda p: p.locator('div[role="main"] h1').first,
            lambda p: p.locator("h1").first,
            lambda p: p.get_by_role("heading").first,
        ],
        timeout_ms=3000,
    )
    details = _group_details(_group_header_text(page))
    if header and not details.get("name"):
        details["name"] = visible_text(header)

    return {
        "group": group,
        "url": page.url,
        "name": details.get("name"),
        "privacy": details.get("privacy"),
        "members": details.get("members"),
        "description": details.get("description"),
    }


def _group_header_text(page) -> str:
    try:
        return page.locator('div[role="main"]').first.inner_text(timeout=1500)
    except PlaywrightError:
        return ""


def _group_details(text: str) -> dict:
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    result = {}
    if lines:
        result["name"] = lines[0]
    joined = " · ".join(lines[:12])
    meta = re.search(r"\b(Public|Private)\s+group\b(?:\s*·\s*([^·]+?members?))?", joined, flags=re.IGNORECASE)
    if not meta:
        meta = re.search(r"\b(Public|Private)\b\s*·\s*([^·]+?members?)", joined, flags=re.IGNORECASE)
    if meta:
        result["privacy"] = meta.group(1).title()
        if len(meta.groups()) > 1 and meta.group(2):
            result["members"] = meta.group(2).strip()
    if "members" not in result:
        members = next((line for line in lines if re.search(r"\bmembers?\b", line, flags=re.IGNORECASE)), None)
        if members:
            result["members"] = members
    description = next(
        (
            line for line in lines
            if len(line) > 40 and not re.search(r"\b(Public|Private|members?|Join group|Invite)\b", line, flags=re.IGNORECASE)
        ),
        None,
    )
    if description:
        result["description"] = description
    return result
