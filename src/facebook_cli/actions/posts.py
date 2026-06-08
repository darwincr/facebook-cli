from __future__ import annotations

from facebook_cli.actions.extract import visible_posts
from facebook_cli.actions.profile import facebook_url
from facebook_cli.browser import human_fill, require_visible
from facebook_cli.conf import FACEBOOK_HOME_URL

COMPOSER_LOCATORS = [
    lambda p: p.get_by_role("button", name="What's on your mind"),
    lambda p: p.locator('[aria-label*="Create a post" i]'),
    lambda p: p.locator('div[role="button"]:has-text("What\'s on your mind")'),
]
EDITOR_LOCATORS = [
    lambda p: p.locator('div[role="dialog"] div[role="textbox"][contenteditable="true"]'),
    lambda p: p.locator('div[role="dialog"] div[contenteditable="true"]'),
]
POST_BUTTON_LOCATORS = [
    lambda p: p.locator('div[role="dialog"] [aria-label="Post"]'),
    lambda p: p.locator('div[role="dialog"] div[role="button"]:has-text("Post")'),
    lambda p: p.get_by_role("button", name="Post"),
]


def feed_posts(session, *, limit: int = 10) -> dict:
    page = session.page
    page.goto(FACEBOOK_HOME_URL)
    page.wait_for_load_state("domcontentloaded")
    session.wait()
    return {"posts": visible_posts(page, limit=limit)}


def profile_posts(session, handle: str, *, limit: int = 10) -> dict:
    page = session.page
    page.goto(facebook_url(handle))
    page.wait_for_load_state("domcontentloaded")
    session.wait()
    return {"handle": handle, "url": page.url, "posts": visible_posts(page, limit=limit)}


def create_post(session, text: str) -> dict:
    page = session.page
    page.goto(FACEBOOK_HOME_URL)
    page.wait_for_load_state("domcontentloaded")
    session.wait()
    require_visible(page, COMPOSER_LOCATORS, label="post composer", timeout_ms=5000).click()
    editor = require_visible(page, EDITOR_LOCATORS, label="post editor", timeout_ms=8000)
    human_fill(editor, text)
    session.wait(0.8, 1.6)
    require_visible(page, POST_BUTTON_LOCATORS, label="post button", timeout_ms=5000).click()
    page.wait_for_load_state("domcontentloaded")
    session.wait(1.5, 3.0)
    return {"posted": True, "text": text}
