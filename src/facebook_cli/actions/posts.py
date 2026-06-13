from __future__ import annotations

from facebook_cli.actions.extract import collect_group_timeline_posts, collect_posts
from facebook_cli.actions.profile import _facebook_path, facebook_url
from facebook_cli.browser import human_fill, require_visible
from facebook_cli.conf import FACEBOOK_BASE_URL
from facebook_cli.conf import FACEBOOK_HOME_URL

COMPOSER_LOCATORS = [
    lambda p: p.get_by_role("button", name="What's on your mind"),
    lambda p: p.get_by_role("button", name="Write something"),
    lambda p: p.locator('[aria-label*="Create a post" i]'),
    lambda p: p.locator('div[role="button"]:has-text("What\'s on your mind")'),
    lambda p: p.locator('div[role="button"]:has-text("Write something")'),
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
COMMENT_BOX_LOCATORS = [
    lambda p: p.locator('div[role="textbox"][contenteditable="true"][aria-label*="Write a comment" i]'),
    lambda p: p.locator('div[role="textbox"][contenteditable="true"][aria-label*="comment" i]'),
    lambda p: p.locator('form div[role="textbox"][contenteditable="true"]'),
    lambda p: p.locator('div[role="textbox"][contenteditable="true"]'),
]
COMMENT_BUTTON_LOCATORS = [
    lambda p: p.locator('[aria-label="Leave a comment"]'),
    lambda p: p.locator('[aria-label*="Comment" i][role="button"]'),
    lambda p: p.locator('div[role="button"]:has-text("Comment")'),
]
MORE_COMMENTS_LOCATORS = [
    lambda p: p.locator('div[role="button"]:has-text("View more comments")'),
    lambda p: p.locator('div[role="button"]:has-text("View previous comments")'),
    lambda p: p.locator('div[role="button"]:has-text("See more comments")'),
    lambda p: p.locator('[role="button"][aria-label*="more comments" i]'),
]


def feed_posts(session, *, limit: int = 10) -> dict:
    page = session.page
    page.goto(FACEBOOK_HOME_URL)
    page.wait_for_load_state("domcontentloaded")
    session.wait()
    return {"posts": collect_posts(page, limit=limit)}


def profile_posts(session, handle: str, *, limit: int = 10) -> dict:
    page = session.page
    page.goto(facebook_url(handle))
    page.wait_for_load_state("domcontentloaded")
    session.wait()
    return {"handle": handle, "url": page.url, "posts": collect_posts(page, limit=limit)}


def group_url(group: str) -> str:
    target = _facebook_path(group)
    if not target.startswith("groups/"):
        target = f"groups/{target}"
    return f"{FACEBOOK_BASE_URL}/{target.rstrip('/')}"


def group_posts(session, group: str, *, limit: int = 10) -> dict:
    page = session.page
    target_url = group_url(group)
    page.goto(target_url)
    page.wait_for_load_state("domcontentloaded")
    session.wait()
    return {"group": group, "url": page.url, "posts": collect_group_timeline_posts(page, limit=limit)}


def create_post(session, text: str, *, group: str | None = None) -> dict:
    page = session.page
    target_url = group_url(group) if group else FACEBOOK_HOME_URL
    page.goto(target_url)
    page.wait_for_load_state("domcontentloaded")
    session.wait()
    require_visible(page, COMPOSER_LOCATORS, label="post composer", timeout_ms=5000).click()
    editor = require_visible(page, EDITOR_LOCATORS, label="post editor", timeout_ms=8000)
    human_fill(editor, text)
    session.wait(0.8, 1.6)
    require_visible(page, POST_BUTTON_LOCATORS, label="post button", timeout_ms=5000).click()
    page.wait_for_load_state("domcontentloaded")
    session.wait(1.5, 3.0)
    result = {"posted": True, "text": text, "url": page.url}
    if group:
        result["group"] = group
    return result


def post_comments(session, post_url: str, *, limit: int = 50) -> dict:
    page = session.page
    page.goto(facebook_url(post_url))
    page.wait_for_load_state("domcontentloaded")
    session.wait()
    _expand_visible_comments(page, limit=limit)
    return {"post_url": post_url, "url": page.url, "comments": _collect_visible_comments(page, limit=limit)}


def comment_on_post(session, post_url: str, text: str) -> dict:
    page = session.page
    page.goto(facebook_url(post_url))
    page.wait_for_load_state("domcontentloaded")
    session.wait()

    try:
        require_visible(page, COMMENT_BUTTON_LOCATORS, label="comment button", timeout_ms=3000).click()
        session.wait(0.5, 1.0)
    except Exception:  # noqa: BLE001
        pass

    editor = require_visible(page, COMMENT_BOX_LOCATORS, label="comment editor", timeout_ms=8000)
    human_fill(editor, text)
    session.wait(0.5, 1.0)
    editor.press("Enter")
    session.wait(1.5, 3.0)
    return {"commented": True, "post_url": post_url, "url": page.url, "text": text}


def _expand_visible_comments(page, *, limit: int) -> None:
    rounds = max(1, min(6, (limit // 10) + 1))
    for _ in range(rounds):
        clicked = False
        for factory in MORE_COMMENTS_LOCATORS:
            locator = factory(page).first
            try:
                locator.wait_for(state="visible", timeout=800)
                locator.click()
                page.wait_for_timeout(1000)
                clicked = True
                break
            except Exception:  # noqa: BLE001
                continue
        if not clicked:
            break


def _collect_visible_comments(page, *, limit: int) -> list[dict]:
    try:
        comments = page.locator('[aria-label*="Comment by" i], div[role="article"]').evaluate_all(
            r"""(nodes, limit) => {
                const cleanLines = text => (text || '')
                    .split(String.fromCharCode(10))
                    .map(line => line.trim())
                    .filter(Boolean);
                const actionText = new Set([
                    'Like', 'Reply', 'Share', 'Send', 'Edited', 'Author', 'Follow',
                    'Hide', 'Report', 'See translation', 'See original'
                ]);
                const isTimestamp = line => /^(?:Just now|Yesterday|\d+\s*(?:s|m|h|d|w|mo|y|sec|min|hr|hrs|day|days|week|weeks|month|months|year|years))$/i.test(line);
                const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
                const out = [];
                const seen = new Set();

                for (const node of nodes) {
                    const label = node.getAttribute('aria-label') || '';
                    const lines = cleanLines(node.innerText);
                    if (!lines.length) continue;

                    const hasReply = Array.from(node.querySelectorAll('[role="button"], a')).some(el => normalize(el.innerText) === 'Reply');
                    const labelledComment = /^Comment by\s+/i.test(label);
                    if (!labelledComment && !hasReply) continue;
                    if (lines.some(line => /write a comment/i.test(line))) continue;

                    let author = labelledComment ? label.replace(/^Comment by\s+/i, '').trim() : lines[0];
                    author = normalize(author);
                    const contentLines = lines.filter(line => {
                        const normalized = normalize(line);
                        return normalized
                            && normalized !== author
                            && !actionText.has(normalized)
                            && !isTimestamp(normalized)
                            && !/^Like\s+Reply/i.test(normalized)
                            && !/^\d+$/.test(normalized);
                    });
                    const content = contentLines.join('\n').trim();
                    if (!author || !content) continue;

                    const link = Array.from(node.querySelectorAll('a[href]')).find(a => /comment_id=|reply_comment_id=/.test(a.href));
                    const key = `${author}:${content}`;
                    if (seen.has(key)) continue;
                    seen.add(key);
                    out.push({author, text: content, url: link ? link.href : null});
                    if (out.length >= limit) break;
                }
                return out;
            }""",
            limit,
        )
    except Exception:  # noqa: BLE001
        return []

    return [comment for comment in comments if comment.get("text")][:limit]
