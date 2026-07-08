from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from facebook_cli.exceptions import (
    AuthenticationError,
    CheckpointChallengeError,
    ElementNotFoundError,
    InteractiveAuthenticationRequired,
    MessengerPinRequiredError,
)
from facebook_cli.session import FacebookSession, clear_profile, session_lock

logger = logging.getLogger("facebook_cli")

_ERROR_TYPES = [
    (CheckpointChallengeError, "checkpoint_challenge"),
    (InteractiveAuthenticationRequired, "interactive_authentication_required"),
    (AuthenticationError, "authentication"),
    (ElementNotFoundError, "element_not_found"),
    (MessengerPinRequiredError, "messenger_pin_required"),
]


def _out(text: str) -> None:
    sys.stdout.write(f"{text}\n")
    sys.stdout.flush()


def _err(text: str) -> None:
    print(text, file=sys.stderr)


def _error_type(exc: Exception) -> str | None:
    for cls, name in _ERROR_TYPES:
        if isinstance(exc, cls):
            return name
    return None


def _render(command: str, result: dict, as_json: bool) -> None:
    if as_json:
        _out(json.dumps(result, ensure_ascii=False, default=str))
        return
    if command == "auth-login":
        _out(f"logged in: {result.get('name') or result.get('profile_url') or result.get('url')}")
    elif command == "auth-status":
        if result.get("authenticated"):
            _out(f"logged in: {result.get('name') or result.get('profile_url') or result.get('url')}")
        else:
            _out(f"not logged in: {result.get('state')}")
    elif command == "profile-read":
        _out("\n".join(x for x in (result.get("name"), result.get("url"), f"{len(result.get('posts') or [])} visible post(s)", "(--json for details)") if x))
    elif command in {"feed-read", "group-posts", "post-read"}:
        posts = result.get("posts") or []
        _out("(no posts)" if not posts else "\n".join(f"{idx + 1}. {(post.get('text') or post.get('content') or '')[:180]}" for idx, post in enumerate(posts)))
    elif command == "group-read":
        _out("\n".join(x for x in (result.get("name"), result.get("url"), result.get("privacy"), result.get("members"), result.get("description")) if x))
    elif command == "post-comments":
        comments = result.get("comments") or []
        _out("(no comments)" if not comments else "\n".join(f"{idx + 1}. {comment.get('author')}: {comment.get('text', '')[:180]}" for idx, comment in enumerate(comments)))
    elif command == "thread-list":
        threads = result.get("threads") or []
        _out(
            "(no threads)"
            if not threads
            else "\n".join(
                f"{idx + 1}. {'[unread] ' if thread.get('unread') else ''}{thread.get('title') or thread.get('url')}"
                f"{f' — {thread.get('preview')}' if thread.get('preview') else ''}"
                for idx, thread in enumerate(threads)
            )
        )
    elif command == "thread-read":
        messages = result.get("messages") or []
        _out("(no messages)" if not messages else "\n".join(f"{idx + 1}. {message.get('text', '')[:240]}" for idx, message in enumerate(messages)))
    elif command in {"message-send", "marketplace-message"}:
        _out("sent" if result.get("sent") else "not sent")
    elif command == "marketplace-read":
        _out("\n".join(x for x in (result.get("title"), result.get("price"), result.get("url"), "(--json for details)") if x))
    elif command == "marketplace-seller":
        seller = result.get("seller") or result
        _out("\n".join(x for x in (seller.get("name"), seller.get("profile_url") or result.get("url"), "(--json for details)") if x))
    elif command == "marketplace-messages":
        messages = result.get("messages") or []
        _out("(no messages)" if not messages else "\n".join(f"{idx + 1}. {message.get('text', '')[:240]}" for idx, message in enumerate(messages)))
    elif command in {"profile-search", "group-search", "post-search", "marketplace-search", "video-search", "reel-search"}:
        results = result.get("results") or []
        _out("(no results)" if not results else "\n".join(f"{item.get('title')} — {item.get('url')}" for item in results))
    elif command == "post-create":
        _out("posted" if result.get("posted") else "not posted")
    elif command == "post-comment":
        _out("commented" if result.get("commented") else "not commented")
    elif command == "session-clear":
        _out(f"cleared {result.get('name')}")
    else:
        _out("\n".join(f"{key}: {value}" for key, value in result.items()))


def _verb_auth_login(session, args) -> dict:
    if args.interactive:
        from facebook_cli.actions.auth import interactive_auth

        return interactive_auth(session, wait=args.wait, timeout=args.timeout)

    from facebook_cli.actions.auth import ensure_logged_in

    return ensure_logged_in(session)


def _verb_profile_read(session, args) -> dict:
    from facebook_cli.actions.profile import open_profile

    return open_profile(session, args.handle, limit=args.limit)


def _verb_search(session, args) -> dict:
    from facebook_cli.actions.profile import search

    return search(
        session,
        args.query,
        limit=args.limit,
        search_type=args.search_type,
        location=args.location,
        group=args.group,
        page_handle=args.page,
    )


def _verb_group_read(session, args) -> dict:
    from facebook_cli.actions.groups import open_group

    return open_group(session, args.group)


def _verb_post_read(session, args) -> dict:
    from facebook_cli.actions.posts import read_post

    return read_post(session, args.post_url)


def _verb_feed_read(session, args) -> dict:
    from facebook_cli.actions.posts import feed_posts

    return feed_posts(session, limit=args.limit)


def _verb_group_posts(session, args) -> dict:
    from facebook_cli.actions.posts import group_posts

    return group_posts(session, args.group, limit=args.limit)


def _verb_post_create(session, args) -> dict:
    from facebook_cli.actions.posts import create_post

    return create_post(session, args.text, group=args.group)


def _verb_post_comments(session, args) -> dict:
    from facebook_cli.actions.posts import post_comments

    return post_comments(session, args.post_url, limit=args.limit)


def _verb_post_comment(session, args) -> dict:
    from facebook_cli.actions.posts import comment_on_post

    return comment_on_post(session, args.post_url, args.text)


def _verb_thread_list(session, args) -> dict:
    from facebook_cli.actions.messages import list_threads

    return list_threads(session, limit=args.limit)


def _verb_thread_read(session, args) -> dict:
    from facebook_cli.actions.messages import read_thread

    return read_thread(session, args.target, limit=args.limit)


def _verb_message_send(session, args) -> dict:
    from facebook_cli.actions.messages import send_message

    return send_message(session, args.target, args.text)


def _verb_marketplace_read(session, args) -> dict:
    from facebook_cli.actions.marketplace import read_item

    return read_item(session, args.item)


def _verb_marketplace_seller(session, args) -> dict:
    from facebook_cli.actions.marketplace import read_seller

    return read_seller(session, args.item_or_profile)


def _verb_marketplace_message(session, args) -> dict:
    from facebook_cli.actions.marketplace import message_seller

    return message_seller(session, args.item, args.text, dry_run=args.dry_run)


def _verb_marketplace_messages(session, args) -> dict:
    from facebook_cli.actions.marketplace import read_seller_messages

    return read_seller_messages(session, args.item, limit=args.limit)


def _verb_auth_status(session, args) -> dict:
    from facebook_cli.actions.auth import auth_status

    return auth_status(session)


_VERBS = {
    "auth-status": _verb_auth_status,
    "auth-login": _verb_auth_login,
    "profile-read": _verb_profile_read,
    "profile-search": _verb_search,
    "group-read": _verb_group_read,
    "group-search": _verb_search,
    "group-posts": _verb_group_posts,
    "post-read": _verb_post_read,
    "post-search": _verb_search,
    "post-create": _verb_post_create,
    "post-comments": _verb_post_comments,
    "post-comment": _verb_post_comment,
    "feed-read": _verb_feed_read,
    "marketplace-search": _verb_search,
    "marketplace-read": _verb_marketplace_read,
    "marketplace-seller": _verb_marketplace_seller,
    "marketplace-message": _verb_marketplace_message,
    "marketplace-messages": _verb_marketplace_messages,
    "video-search": _verb_search,
    "reel-search": _verb_search,
    "thread-list": _verb_thread_list,
    "thread-read": _verb_thread_read,
    "message-send": _verb_message_send,
}


def _error_payload(exc: Exception, error_type: str) -> dict:
    payload = {
        "ok": False,
        "authenticated": False,
        "error": {
            "type": error_type,
            "message": str(exc),
        },
    }
    if error_type in {"interactive_authentication_required", "checkpoint_challenge"}:
        payload["state"] = "login_required" if error_type == "interactive_authentication_required" else "checkpoint_required"
        payload["next_command"] = "facebook-cli auth login --interactive --wait --timeout 300"
    return payload


def _execute_verb(args, session) -> int:
    try:
        _render(args.verb, _VERBS[args.verb](session, args), args.json)
        return 0
    except Exception as exc:  # noqa: BLE001
        error_type = _error_type(exc)
        if error_type is None:
            raise
        if args.json:
            _out(json.dumps(_error_payload(exc, error_type), ensure_ascii=False, default=str))
            return 1
        _err(f"error: {error_type}: {exc}")
        return 1


def _run_verb_local(args) -> int:
    with session_lock(args.name):
        session = FacebookSession(args.name)
        with session:
            return _execute_verb(args, session)


def _run_verb(args, argv: list[str]) -> int:
    if os.environ.get("FACEBOOK_CLI_WORKER") == "1":
        return _run_verb_local(args)
    from facebook_cli.worker import run_via_worker

    return run_via_worker(args.name, argv)


def _cmd_session_clear(args) -> int:
    from facebook_cli.worker import stop_worker

    stop_worker(args.name)
    with session_lock(args.name):
        clear_profile(args.name)
    _render("session-clear", {"name": args.name, "cleared": True}, args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    import os

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--session", "--name", dest="name",
        default=os.environ.get("FACEBOOK_CLI_SESSION", "default"),
        help="Session/profile name (default: $FACEBOOK_CLI_SESSION or 'default')",
    )
    common.add_argument("--json", action="store_true", help="Emit full JSON instead of a short summary")

    parser = argparse.ArgumentParser(prog="facebook-cli", description="Drive Facebook through Playwright Chromium")
    sub = parser.add_subparsers(dest="cmd", required=True)

    auth_cmd = sub.add_parser("auth", help="Authenticate the persistent browser profile")
    auth_sub = auth_cmd.add_subparsers(dest="auth_cmd", required=True)
    auth_sub.add_parser("status", parents=[common], help="Report the current authentication state").set_defaults(verb="auth-status")
    p_auth_login = auth_sub.add_parser("login", parents=[common], help="Log in or verify the current Facebook session")
    p_auth_login.add_argument("--interactive", action="store_true", help="Open Facebook while you complete login/checkpoint manually")
    p_auth_login.add_argument(
        "--wait",
        action="store_true",
        help="With --interactive, poll until login completes instead of waiting for Enter",
    )
    p_auth_login.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Maximum seconds to wait with --interactive --wait (default: 300)",
    )
    p_auth_login.set_defaults(verb="auth-login")

    session_cmd = sub.add_parser("session", help="Manage local browser session state")
    session_sub = session_cmd.add_subparsers(dest="session_cmd", required=True)
    session_sub.add_parser("clear", parents=[common], help="Delete the local browser profile for a session").set_defaults(verb="session-clear")

    profile_cmd = sub.add_parser("profile", help="Read or search Facebook profiles/pages")
    profile_sub = profile_cmd.add_subparsers(dest="profile_cmd", required=True)
    p_profile_read = profile_sub.add_parser("read", parents=[common], help="Open a profile/page and extract visible details")
    p_profile_read.add_argument("handle", help="Facebook handle, path, or full URL")
    p_profile_read.add_argument("--limit", type=int, default=5, help="Maximum visible posts to return (default: 5)")
    p_profile_read.set_defaults(verb="profile-read")
    p_profile_search = profile_sub.add_parser("search", parents=[common], help="Search Facebook pages/profiles")
    _add_search_args(p_profile_search)
    p_profile_search.set_defaults(verb="profile-search", search_type="pages", location=None, group=None, page=None)

    group_cmd = sub.add_parser("group", help="Read, search, or list Facebook group posts")
    group_sub = group_cmd.add_subparsers(dest="group_cmd", required=True)
    p_group_read = group_sub.add_parser("read", parents=[common], help="Open a group and extract visible details")
    p_group_read.add_argument("group", help="Facebook group id, path, or full URL")
    p_group_read.set_defaults(verb="group-read")
    p_group_search = group_sub.add_parser("search", parents=[common], help="Search Facebook groups")
    _add_search_args(p_group_search)
    p_group_search.set_defaults(verb="group-search", search_type="groups", location=None, group=None, page=None)
    p_group_posts = group_sub.add_parser("posts", parents=[common], help="List visible group posts")
    p_group_posts.add_argument("group", help="Facebook group id, path, or full URL")
    p_group_posts.add_argument("--limit", type=int, default=10, help="Maximum visible posts to return (default: 10)")
    p_group_posts.set_defaults(verb="group-posts")

    post_cmd = sub.add_parser("post", help="Read, search, create, or comment on posts")
    post_sub = post_cmd.add_subparsers(dest="post_cmd", required=True)
    p_post_read = post_sub.add_parser("read", parents=[common], help="Read a single post permalink")
    p_post_read.add_argument("post_url", help="Facebook post URL, permalink, or path")
    p_post_read.set_defaults(verb="post-read")
    p_post_search = post_sub.add_parser("search", parents=[common], help="Search posts, optionally scoped to a group or page")
    _add_search_args(p_post_search)
    post_search_scope = p_post_search.add_mutually_exclusive_group()
    post_search_scope.add_argument("--group", help="Search inside a group id, path, or URL")
    post_search_scope.add_argument("--page", help="Search inside a page/profile id, path, or URL")
    p_post_search.set_defaults(verb="post-search", search_type="top", location=None)
    p_post_create = post_sub.add_parser("create", parents=[common], help="Create a text post")
    p_post_create.add_argument("--text", required=True, help="Post body text")
    p_post_create.add_argument("--group", help="Post to a group id, path, or URL instead of your feed")
    p_post_create.set_defaults(verb="post-create")
    p_post_comments = post_sub.add_parser("comments", parents=[common], help="List visible comments for a post")
    p_post_comments.add_argument("post_url", help="Facebook post URL, permalink, or path")
    p_post_comments.add_argument("--limit", type=int, default=50, help="Maximum visible comments to return (default: 50)")
    p_post_comments.set_defaults(verb="post-comments")
    p_post_comment = post_sub.add_parser("comment", parents=[common], help="Add a comment to a post")
    p_post_comment.add_argument("post_url", help="Facebook post URL, permalink, or path")
    p_post_comment.add_argument("--text", required=True, help="Comment text to send")
    p_post_comment.set_defaults(verb="post-comment")

    feed_cmd = sub.add_parser("feed", help="Read the Facebook home feed")
    feed_sub = feed_cmd.add_subparsers(dest="feed_cmd", required=True)
    p_feed_read = feed_sub.add_parser("read", parents=[common], help="List visible feed posts")
    p_feed_read.add_argument("--limit", type=int, default=10, help="Maximum visible posts to return (default: 10)")
    p_feed_read.set_defaults(verb="feed-read")

    marketplace_cmd = sub.add_parser("marketplace", help="Search and operate Facebook Marketplace")
    marketplace_sub = marketplace_cmd.add_subparsers(dest="marketplace_cmd", required=True)
    p_marketplace_search = marketplace_sub.add_parser("search", parents=[common], help="Search Marketplace listings")
    _add_search_args(p_marketplace_search)
    p_marketplace_search.add_argument("--location", help="Marketplace location slug, for example 'melbourne'")
    p_marketplace_search.set_defaults(verb="marketplace-search", search_type="marketplace", group=None, page=None)
    p_marketplace_read = marketplace_sub.add_parser("read", parents=[common], help="Open a Marketplace listing and extract visible details")
    p_marketplace_read.add_argument("item", help="Marketplace item URL, /marketplace/item path, or item id")
    p_marketplace_read.set_defaults(verb="marketplace-read")
    p_marketplace_seller = marketplace_sub.add_parser("seller", parents=[common], help="Open a listing or Marketplace seller profile and extract visible seller details")
    p_marketplace_seller.add_argument("item_or_profile", help="Marketplace item/profile URL, path, or item id")
    p_marketplace_seller.set_defaults(verb="marketplace-seller")
    p_marketplace_message = marketplace_sub.add_parser("message", parents=[common], help="Send a message to the seller from a Marketplace listing")
    p_marketplace_message.add_argument("item", help="Marketplace item URL, /marketplace/item path, or item id")
    p_marketplace_message.add_argument("--text", required=True, help="Message text to send")
    p_marketplace_message.add_argument("--dry-run", action="store_true", help="Open and inspect the seller chat without sending the message")
    p_marketplace_message.set_defaults(verb="marketplace-message")
    p_marketplace_messages = marketplace_sub.add_parser("messages", parents=[common], help="Read visible seller chat messages from a Marketplace listing")
    p_marketplace_messages.add_argument("item", help="Marketplace item URL, /marketplace/item path, or item id")
    p_marketplace_messages.add_argument("--limit", type=int, default=20, help="Maximum visible messages to return (default: 20)")
    p_marketplace_messages.set_defaults(verb="marketplace-messages")

    video_cmd = sub.add_parser("video", help="Search Facebook videos")
    video_sub = video_cmd.add_subparsers(dest="video_cmd", required=True)
    p_video_search = video_sub.add_parser("search", parents=[common], help="Search videos")
    _add_search_args(p_video_search)
    p_video_search.set_defaults(verb="video-search", search_type="videos", location=None, group=None, page=None)

    reel_cmd = sub.add_parser("reel", help="Search Facebook reels")
    reel_sub = reel_cmd.add_subparsers(dest="reel_cmd", required=True)
    p_reel_search = reel_sub.add_parser("search", parents=[common], help="Search reels")
    _add_search_args(p_reel_search)
    p_reel_search.set_defaults(verb="reel-search", search_type="reels", location=None, group=None, page=None)

    thread_cmd = sub.add_parser("thread", help="List or read Messenger threads")
    thread_sub = thread_cmd.add_subparsers(dest="thread_cmd", required=True)
    p_thread_list = thread_sub.add_parser("list", parents=[common], help="List visible Messenger threads")
    p_thread_list.add_argument("--limit", type=int, default=10, help="Maximum visible threads to return (default: 10)")
    p_thread_list.set_defaults(verb="thread-list")
    p_thread_read = thread_sub.add_parser("read", parents=[common], help="Read visible messages from a thread")
    p_thread_read.add_argument("target", help="Thread URL, /messages path, thread id, or recipient search text")
    p_thread_read.add_argument("--limit", type=int, default=20, help="Maximum visible messages to return (default: 20)")
    p_thread_read.set_defaults(verb="thread-read")

    message_cmd = sub.add_parser("message", help="Send Messenger messages")
    message_sub = message_cmd.add_subparsers(dest="message_cmd", required=True)
    p_message_send = message_sub.add_parser("send", parents=[common], help="Send one message to an explicit target")
    p_message_send.add_argument("target", help="Thread URL, /messages path, thread id, or recipient search text")
    p_message_send.add_argument("--text", required=True, help="Message text to send")
    p_message_send.set_defaults(verb="message-send")
    return parser


def _add_search_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", type=int, default=10, help="Maximum results to return (default: 10)")


def _configure_logging() -> None:
    import os

    level = os.environ.get("FACEBOOK_CLI_LOG", "INFO").upper()
    logging.basicConfig(level=level, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _parse_args(argv=None):
    return build_parser().parse_args(argv)


def main(argv=None) -> int:
    from facebook_cli.conf import load_dotenv_fallback

    load_dotenv_fallback()
    argv = sys.argv[1:] if argv is None else list(argv)
    args = _parse_args(argv)
    _configure_logging()
    if args.cmd == "session":
        return _cmd_session_clear(args)
    return _run_verb(args, argv)


if __name__ == "__main__":
    raise SystemExit(main())
