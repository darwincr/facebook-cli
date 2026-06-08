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
    if command in {"login", "auth-interactive"}:
        _out(f"logged in: {result.get('name') or result.get('profile_url') or result.get('url')}")
    elif command == "auth-status":
        if result.get("authenticated"):
            _out(f"logged in: {result.get('name') or result.get('profile_url') or result.get('url')}")
        else:
            _out(f"not logged in: {result.get('state')}")
    elif command == "whoami":
        _out(f"{result.get('name')} {result.get('profile_url') or ''}".strip())
    elif command == "profile":
        _out("\n".join(x for x in (result.get("name"), result.get("url"), f"{len(result.get('posts') or [])} visible post(s)", "(--json for details)") if x))
    elif command in {"posts-feed", "posts-profile"}:
        posts = result.get("posts") or []
        _out("(no posts)" if not posts else "\n".join(f"{idx + 1}. {post.get('text', '')[:180]}" for idx, post in enumerate(posts)))
    elif command == "messages-threads":
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
    elif command == "messages-read":
        messages = result.get("messages") or []
        _out("(no messages)" if not messages else "\n".join(f"{idx + 1}. {message.get('text', '')[:240]}" for idx, message in enumerate(messages)))
    elif command == "messages-send":
        _out("sent" if result.get("sent") else "not sent")
    elif command == "search":
        results = result.get("results") or []
        _out("(no results)" if not results else "\n".join(f"{item.get('title')} — {item.get('url')}" for item in results))
    elif command == "posts-create":
        _out("posted" if result.get("posted") else "not posted")
    elif command == "session-clear":
        _out(f"cleared {result.get('name')}")
    else:
        _out("\n".join(f"{key}: {value}" for key, value in result.items()))


def _verb_login(session, args) -> dict:
    if args.interactive:
        from facebook_cli.actions.auth import interactive_auth

        return interactive_auth(session, wait=args.wait, timeout=args.timeout)

    from facebook_cli.actions.auth import ensure_logged_in

    return ensure_logged_in(session)


def _verb_whoami(session, args) -> dict:
    from facebook_cli.actions.auth import current_account

    return current_account(session)


def _verb_profile(session, args) -> dict:
    from facebook_cli.actions.profile import open_profile

    return open_profile(session, args.handle, limit=args.limit)


def _verb_search(session, args) -> dict:
    from facebook_cli.actions.profile import search

    return search(
        session,
        args.query,
        limit=args.limit,
        search_type=args.type,
        location=args.location,
        group=args.group,
        page_handle=args.page,
    )


def _verb_posts_feed(session, args) -> dict:
    from facebook_cli.actions.posts import feed_posts

    return feed_posts(session, limit=args.limit)


def _verb_posts_profile(session, args) -> dict:
    from facebook_cli.actions.posts import profile_posts

    return profile_posts(session, args.handle, limit=args.limit)


def _verb_posts_create(session, args) -> dict:
    from facebook_cli.actions.posts import create_post

    return create_post(session, args.text)


def _verb_messages_threads(session, args) -> dict:
    from facebook_cli.actions.messages import list_threads

    return list_threads(session, limit=args.limit)


def _verb_messages_read(session, args) -> dict:
    from facebook_cli.actions.messages import read_thread

    return read_thread(session, args.target, limit=args.limit)


def _verb_messages_send(session, args) -> dict:
    from facebook_cli.actions.messages import send_message

    return send_message(session, args.target, args.text)


def _verb_auth_interactive(session, args) -> dict:
    from facebook_cli.actions.auth import interactive_auth

    return interactive_auth(session, wait=args.wait, timeout=args.timeout)


def _verb_auth_status(session, args) -> dict:
    from facebook_cli.actions.auth import auth_status

    return auth_status(session)


_VERBS = {
    "login": _verb_login,
    "whoami": _verb_whoami,
    "profile": _verb_profile,
    "search": _verb_search,
    "posts-feed": _verb_posts_feed,
    "posts-profile": _verb_posts_profile,
    "posts-create": _verb_posts_create,
    "messages-threads": _verb_messages_threads,
    "messages-read": _verb_messages_read,
    "messages-send": _verb_messages_send,
    "auth-interactive": _verb_auth_interactive,
    "auth-status": _verb_auth_status,
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
        payload["next_command"] = "facebook-cli login --interactive --wait --timeout 300"
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

    parser = argparse.ArgumentParser(prog="facebook-cli", description="Drive Facebook through Camoufox")
    sub = parser.add_subparsers(dest="cmd", required=True)

    session_cmd = sub.add_parser("session", help="Manage local browser session state")
    session_sub = session_cmd.add_subparsers(dest="subcmd", required=True)
    session_sub.add_parser("clear", parents=[common], help="Delete the local browser profile for a session")

    p_login = sub.add_parser("login", parents=[common], help="Log in or verify the current Facebook session")
    p_login.add_argument(
        "--interactive",
        action="store_true",
        help="Open Facebook and wait while you complete login/checkpoint manually",
    )
    p_login.add_argument(
        "--wait",
        action="store_true",
        help="With --interactive, poll until login completes instead of waiting for Enter",
    )
    p_login.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Maximum seconds to wait with --interactive --wait (default: 300)",
    )
    sub.add_parser("whoami", parents=[common], help="Report the visible logged-in account")

    auth_cmd = sub.add_parser("auth", help="Authenticate the persistent browser profile")
    auth_sub = auth_cmd.add_subparsers(dest="auth_cmd", required=True)
    auth_sub.add_parser("status", parents=[common], help="Report the current authentication state")
    p_auth_interactive = auth_sub.add_parser(
        "interactive",
        parents=[common],
        help="Open Facebook and wait while you log in manually",
    )
    p_auth_interactive.add_argument(
        "--wait",
        action="store_true",
        help="Poll until login completes instead of waiting for Enter",
    )
    p_auth_interactive.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Maximum seconds to wait with --wait (default: 300)",
    )

    p_profile = sub.add_parser("profile", parents=[common], help="Open a profile/page and extract visible details")
    p_profile.add_argument("handle", help="Facebook handle, path, or full URL")
    p_profile.add_argument("--limit", type=int, default=5, help="Maximum visible posts to return (default: 5)")

    p_search = sub.add_parser("search", parents=[common], help="Search Facebook and list visible results")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument(
        "--type",
        choices=["groups", "pages", "marketplace", "videos", "reels"],
        default="groups",
        help="Search surface to use (default: groups)",
    )
    p_search.add_argument(
        "--location",
        help="Marketplace location slug, for example 'melbourne' with --type marketplace",
    )
    p_search.add_argument("--group", help="Search inside a group id, path, or URL")
    p_search.add_argument("--page", help="Search inside a page/profile id, path, or URL")
    p_search.add_argument("--limit", type=int, default=10, help="Maximum results to return (default: 10)")

    posts_cmd = sub.add_parser("posts", help="Read or create Facebook posts")
    posts_sub = posts_cmd.add_subparsers(dest="posts_cmd", required=True)

    p_posts_feed = posts_sub.add_parser("feed", parents=[common], help="List visible feed posts")
    p_posts_feed.add_argument("--limit", type=int, default=10, help="Maximum visible posts to return (default: 10)")

    p_posts_profile = posts_sub.add_parser("profile", parents=[common], help="List visible profile/page posts")
    p_posts_profile.add_argument("handle", help="Facebook handle, path, or full URL")
    p_posts_profile.add_argument("--limit", type=int, default=10, help="Maximum visible posts to return (default: 10)")

    p_posts_create = posts_sub.add_parser("create", parents=[common], help="Create a text post")
    p_posts_create.add_argument("--text", required=True, help="Post body text")

    messages_cmd = sub.add_parser("messages", help="Read and send Facebook Messenger messages")
    messages_sub = messages_cmd.add_subparsers(dest="messages_cmd", required=True)

    p_messages_threads = messages_sub.add_parser("threads", parents=[common], help="List visible Messenger threads")
    p_messages_threads.add_argument("--limit", type=int, default=10, help="Maximum visible threads to return (default: 10)")

    p_messages_read = messages_sub.add_parser("read", parents=[common], help="Read visible messages from a thread")
    p_messages_read.add_argument("target", nargs="?", help="Thread URL, /messages path, thread id, or omit for the open/default thread")
    p_messages_read.add_argument("--limit", type=int, default=20, help="Maximum visible messages to return (default: 20)")

    p_messages_send = messages_sub.add_parser("send", parents=[common], help="Send one message to an explicit target")
    p_messages_send.add_argument("target", help="Thread URL, /messages path, thread id, or recipient search text")
    p_messages_send.add_argument("--text", required=True, help="Message text to send")
    return parser


def _configure_logging() -> None:
    import os

    level = os.environ.get("FACEBOOK_CLI_LOG", "INFO").upper()
    logging.basicConfig(level=level, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _parse_args(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "auth":
        args.verb = f"auth-{args.auth_cmd}"
    elif args.cmd == "posts":
        args.verb = f"posts-{args.posts_cmd}"
    elif args.cmd == "messages":
        args.verb = f"messages-{args.messages_cmd}"
    else:
        args.verb = args.cmd
    return args


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    args = _parse_args(argv)
    _configure_logging()
    if args.cmd == "session":
        return _cmd_session_clear(args)
    return _run_verb(args, argv)


if __name__ == "__main__":
    raise SystemExit(main())
