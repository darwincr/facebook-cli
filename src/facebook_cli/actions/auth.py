from __future__ import annotations

import logging
import os
import sys
import time
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from facebook_cli.browser import first_visible, goto_domcontentloaded, safe_attr, visible_text
from facebook_cli.conf import FACEBOOK_BASE_URL, FACEBOOK_HOME_URL
from facebook_cli.exceptions import AuthenticationError, CheckpointChallengeError, InteractiveAuthenticationRequired

logger = logging.getLogger(__name__)

LOGIN_FORM_LOCATORS = [
    lambda p: p.locator('input[name="email"]'),
    lambda p: p.locator('input#email'),
    lambda p: p.get_by_label("Email address or phone number"),
    lambda p: p.get_by_label("Email or phone"),
]
ACCOUNT_LOCATORS = [
    lambda p: p.locator('a[aria-label*="Your profile" i]'),
    lambda p: p.locator('a[aria-label*="profile" i]'),
    lambda p: p.locator('a[href*="/me/"]'),
    lambda p: p.locator('a[href*="/profile.php"]'),
]
LOGGED_IN_LOCATORS = [
    lambda p: p.get_by_role("navigation", name="Facebook"),
    lambda p: p.get_by_role("button", name="Account"),
    lambda p: p.locator('[aria-label*="Account" i]'),
    lambda p: p.locator('[aria-label*="Create" i]'),
    lambda p: p.locator('[aria-label*="Home" i]'),
    lambda p: p.locator('div[role="feed"]'),
]
PROFILE_NAME_LOCATORS = [
    lambda p: p.locator('h1'),
    lambda p: p.get_by_role("heading").first,
]
PROFILE_IMAGE_LOCATORS = [
    lambda p: p.locator('image[xlink\\:href*="scontent"]'),
    lambda p: p.locator('image[href*="scontent"]'),
    lambda p: p.locator('img[src*="scontent"]'),
]


def _is_checkpoint(url: str) -> bool:
    return any(part in url.lower() for part in ("checkpoint", "two_step", "login/checkpoint", "recover"))


def _is_login_page(url: str) -> bool:
    lower = url.lower()
    return "/login" in lower or "login.php" in lower


def _is_facebook_page(url: str) -> bool:
    return url.lower().startswith(FACEBOOK_BASE_URL)


def _is_profile_url(url: str | None) -> bool:
    if not url:
        return False
    parts = urlsplit(url)
    path = parts.path.strip("/").lower()
    if parts.netloc and not parts.netloc.endswith("facebook.com"):
        return False
    return bool(path) and path not in {"login", "login.php", "home.php", "me"}


def _absolute_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("/"):
        return f"{FACEBOOK_BASE_URL}{url}"
    return url


def _clean_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _profile_link_from_home(page) -> tuple[str | None, str | None]:
    locators = [factory(page) for factory in ACCOUNT_LOCATORS]
    links = locators[0]
    for locator in locators[1:]:
        links = links.or_(locator)

    count = min(links.count(), 20)
    for index in range(count):
        link = links.nth(index)
        href = _clean_url(_absolute_url(safe_attr(link, "href")))
        if not _is_profile_url(href):
            continue
        name = visible_text(link)
        return href, name or None
    return None, None


def ensure_logged_in(session) -> dict:
    try:
        return current_account(session, verify_current_page=False)
    except (AuthenticationError, InteractiveAuthenticationRequired):
        pass

    page = session.page
    goto_domcontentloaded(page, FACEBOOK_HOME_URL)
    if _is_checkpoint(page.url):
        raise CheckpointChallengeError(f"Resolve the Facebook checkpoint manually in Camoufox: {page.url}")

    if first_visible(page, LOGIN_FORM_LOCATORS, timeout_ms=2500) is not None:
        raise InteractiveAuthenticationRequired(
            "Interactive authentication is required. Run `facebook-cli auth interactive`, "
            "complete Facebook login/checkpoint manually in the Camoufox browser, then rerun this command."
        )

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if _is_checkpoint(page.url):
            raise CheckpointChallengeError(f"Resolve the Facebook checkpoint manually in Camoufox: {page.url}")
        if not _is_login_page(page.url) and (
            first_visible(page, ACCOUNT_LOCATORS, timeout_ms=1500)
            or first_visible(page, LOGGED_IN_LOCATORS, timeout_ms=1500)
        ):
            profile_url, name = _profile_link_from_home(page)
            if profile_url:
                return _account_from_profile_page(session, profile_url, fallback_name=name)
            return current_account(session, verify_current_page=False)
        time.sleep(1)

    raise AuthenticationError(f"Facebook did not reach a logged-in page; current URL: {page.url}")


def auth_status(session) -> dict:
    try:
        account = ensure_logged_in(session)
    except InteractiveAuthenticationRequired as exc:
        return {
            "authenticated": False,
            "state": "login_required",
            "message": str(exc),
            "next_command": "facebook-cli login --interactive --wait --timeout 300",
        }
    except CheckpointChallengeError as exc:
        return {
            "authenticated": False,
            "state": "checkpoint_required",
            "message": str(exc),
            "next_command": "facebook-cli login --interactive --wait --timeout 300",
        }
    except AuthenticationError as exc:
        return {
            "authenticated": False,
            "state": "unknown",
            "message": str(exc),
        }
    return {"authenticated": True, "state": "logged_in", **account}


def current_account(session, *, verify_current_page: bool = True) -> dict:
    page = session.page
    if verify_current_page:
        goto_domcontentloaded(page, FACEBOOK_HOME_URL)
        if first_visible(page, LOGIN_FORM_LOCATORS, timeout_ms=1000) is not None or _is_login_page(page.url):
            raise InteractiveAuthenticationRequired("Facebook is showing the login form")
        if first_visible(page, LOGGED_IN_LOCATORS, timeout_ms=3000) is None:
            raise AuthenticationError("Could not identify the logged-in account")

    goto_domcontentloaded(page, f"{FACEBOOK_BASE_URL}/me")
    profile_url = _clean_url(page.url)

    if _is_checkpoint(page.url):
        raise CheckpointChallengeError(f"Resolve the Facebook checkpoint manually in Camoufox: {page.url}")
    if not _is_profile_url(profile_url):
        if first_visible(page, LOGIN_FORM_LOCATORS, timeout_ms=1000) is not None or _is_login_page(page.url):
            raise InteractiveAuthenticationRequired("Facebook is showing the login form")
        raise AuthenticationError(f"Could not resolve the Facebook profile URL; current URL: {page.url}")

    return _account_from_profile_page(session, profile_url)


def _account_from_profile_page(session, profile_url: str, *, fallback_name: str | None = None) -> dict:
    page = session.page

    if _clean_url(page.url) != profile_url:
        goto_domcontentloaded(page, profile_url)
    name_locator = first_visible(page, PROFILE_NAME_LOCATORS, timeout_ms=5000)
    name = visible_text(name_locator) if name_locator else fallback_name

    avatar = first_visible(page, PROFILE_IMAGE_LOCATORS, timeout_ms=1000)
    return {
        "name": name,
        "profile_url": profile_url,
        "avatar_url": safe_attr(avatar, "xlink:href") or safe_attr(avatar, "href") or safe_attr(avatar, "src") if avatar else None,
        "url": page.url,
        "authenticated": True,
    }


def interactive_auth(session, wait: bool = False, timeout: int = 300) -> dict:
    page = session.page
    goto_domcontentloaded(page, FACEBOOK_HOME_URL)
    if os.environ.get("FACEBOOK_CLI_WORKER") == "1" and not wait:
        wait = True
    if wait:
        print(
            f"Complete Facebook login/checkpoint in the Camoufox browser. Waiting up to {timeout} seconds...",
            file=sys.stderr,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            page.wait_for_load_state("domcontentloaded")
            if _is_checkpoint(page.url):
                time.sleep(2)
                continue
            if not _is_login_page(page.url) and (
                first_visible(page, ACCOUNT_LOCATORS, timeout_ms=1500)
                or first_visible(page, LOGGED_IN_LOCATORS, timeout_ms=1500)
            ):
                return current_account(session, verify_current_page=False)
            time.sleep(2)
        raise InteractiveAuthenticationRequired(f"Facebook login was not completed within {timeout} seconds")

    print("Complete Facebook login/checkpoint in the Camoufox browser, then press Enter here.", file=sys.stderr)
    input()
    page.wait_for_load_state("domcontentloaded")
    if _is_checkpoint(page.url):
        raise CheckpointChallengeError(f"Facebook is still on a checkpoint page: {page.url}")
    if first_visible(page, LOGIN_FORM_LOCATORS, timeout_ms=1000) is not None or _is_login_page(page.url):
        raise InteractiveAuthenticationRequired("Facebook is still showing the login form")
    return current_account(session)
