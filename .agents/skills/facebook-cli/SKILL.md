---
name: facebook-cli
description: "Operate Facebook through the facebook-cli command line tool. Drive a real browser profile to read profiles/search/posts/comments, create posts and comments, and read/send Messenger messages. USE FOR: reading the facebook feed, search facebook groups/pages/marketplace, list messenger threads, send facebook message, create facebook post, comment on facebook post, drive facebook from CLI. DO NOT USE FOR: Instagram, WhatsApp, or other social medias."
---

# facebook-cli Operator Skill

`facebook-cli` drives a real Playwright Chromium browser profile to operate
Facebook. It never reads credentials — login is done manually in the browser
window. State is stored locally under `~/.facebook-cli/profiles/<session>`.

## How to invoke the CLI

Always run the CLI from this project root via `uv run`, so it uses the
in-tree source (not a separately installed copy):

```bash
uv run facebook-cli <command> [flags]
```

All `--help` commands and examples below assume this form. For quick shell
verification of a single command's flags, `uv run facebook-cli <cmd> --help`
is authoritative.

## Core conventions (apply to every command)

- Always append `--json` to get structured, parseable output. Without it the
  CLI prints a short human summary only.
- Target a specific profile with `--session <name>` (alias `--name`), or set
  `$FACEBOOK_CLI_SESSION`. Default session is `default`.
- Options and defaults may change; `<command> --help` is always authoritative.
  **Run the relevant `--help` (see categories below) before constructing a
  command you are unsure about.**
- Errors in JSON include `ok: false` and `error.type`. When
  `error.type` is `interactive_authentication_required` or
  `checkpoint_challenge`, a `next_command` field tells you how to recover.
- Commands reuse a per-session background Chromium worker. The first command
  starts the browser; later commands queue through one local socket so only
  one action touches the session at a time. The worker exits after an idle
  period and restarts on next use, reusing the same persistent profile.
- Relevant env vars: `FACEBOOK_CLI_HOME` (state root),
  `FACEBOOK_CLI_HEADLESS` (`1`/`true`/`yes`), `FACEBOOK_CLI_LOG` (log level),
  `FACEBOOK_CLI_MESSENGER_PIN` (only used if a Messenger PIN prompt appears).

## Browser state checks — run these directly

These are the only commands listed inline, because they are cheap, safe,
read-only, and should be run frequently (especially before any action).

| Goal | Command | Notes |
|---|---|---|
| Check login state before acting | `uv run facebook-cli auth status --json` | Returns `authenticated`, `state` (`logged_in` / `login_required` / `checkpoint_required`), and when authenticated the visible `name` and `profile_url`. **Always run this first** when the session state is unknown. |
| Verify session non-interactively | `uv run facebook-cli login --json` | Confirms the current session; returns `interactive_authentication_required` if a login form is visible, without opening a window. |

Recovery flow when `auth status` is not authenticated, or any command returns
`interactive_authentication_required` / `checkpoint_challenge`:

```bash
uv run facebook-cli login --interactive --wait --timeout 300
```

Complete login/checkpoint manually in the opened browser; the command exits
automatically once authenticated. Then re-run `uv run facebook-cli auth status --json` to confirm.

## Command discovery

| When | Run |
|---|---|
| You are unfamiliar with the CLI, want the full list of command groups, or need to confirm a command name exists | `uv run facebook-cli --help` |

## Functional categories — retrieve `--help` per situation

For every task below, run the listed `--help` command(s) first to get the
exact positional args, flags, choices, and defaults, then construct the
real command (always with `--json` for parsing).

### Authentication & manual login
**When:** starting on a fresh session, `auth status` reports not logged in,
or any command errors with `interactive_authentication_required` or
`checkpoint_challenge`.

| Run | To learn about |
|---|---|
| `uv run facebook-cli login --help` | `login` with `--interactive`, `--wait`, `--timeout` (the main manual-login entry point) |
| `uv run facebook-cli auth --help` | The `auth` group and its subcommands |
| `uv run facebook-cli auth status --help` | `auth status` (read-only state check) |
| `uv run facebook-cli auth interactive --help` | `auth interactive` with `--wait`, `--timeout` (alias of `login --interactive`) |

### Session & profile lifecycle
**When:** resetting state, clearing a corrupt/stale profile, removing a
saved login, or debugging "wrong account is logged in".

| Run | To learn about |
|---|---|
| `uv run facebook-cli session --help` | The `session` group |
| `uv run facebook-cli session clear --help` | `session clear` — deletes the local browser profile for a session |

### Looking up a person or page
**When:** you have a handle/path/URL and want the profile's name, intro,
URL, and visible recent post cards.

| Run | To learn about |
|---|---|
| `uv run facebook-cli profile --help` | `profile <handle>` with `--limit` (visible posts to return) |

### Searching Facebook
**When:** finding groups, pages, Marketplace listings, videos, or reels by
query; or searching scoped inside a specific group or page.

| Run | To learn about |
|---|---|
| `uv run facebook-cli search --help` | `search <query>` with `--type` (`top`/`groups`/`pages`/`marketplace`/`videos`/`reels`), `--location` (Marketplace slug), `--group`, `--page`, `--limit` |

### Reading feed, timeline, and group posts
**When:** extracting post lists from your home feed, a profile/page
timeline, or a group timeline.

| Run | To learn about |
|---|---|
| `uv run facebook-cli posts --help` | The `posts` group and all subcommands |
| `uv run facebook-cli posts feed --help` | `posts feed` — your home feed, with `--limit` |
| `uv run facebook-cli posts profile --help` | `posts profile <handle>` — a profile/page timeline |
| `uv run facebook-cli posts group --help` | `posts group <group>` — a group timeline |

### Reading comments on a post
**When:** you have a post URL/permalink/path and want its visible comments.

| Run | To learn about |
|---|---|
| `uv run facebook-cli posts comments --help` | `posts comments <post_url>` with `--limit` (default 50) |

### Writing posts and comments
**When:** publishing a text post to your feed or a group, or adding a
comment to a post. These are **write** actions — confirm the target and
text before running.

| Run | To learn about |
|---|---|
| `uv run facebook-cli posts create --help` | `posts create --text TEXT [--group GROUP]` |
| `uv run facebook-cli posts comment --help` | `posts comment <post_url> --text TEXT` |

### Messenger conversations
**When:** listing Messenger threads, reading messages from a thread, or
sending a message.

| Run | To learn about |
|---|---|
| `uv run facebook-cli messages --help` | The `messages` group and all subcommands |
| `uv run facebook-cli messages threads --help` | `messages threads` — list conversations, with `--limit` |
| `uv run facebook-cli messages read --help` | `messages read [target]` — read visible messages; `target` is a thread URL, `/messages` path, thread id, or omit for the open/default thread |
| `uv run facebook-cli messages send --help` | `messages send <target> --text TEXT` — `target` is a thread URL/path/id or recipient search text |

## Operating patterns

- **Before any action:** `uv run facebook-cli auth status --json`. If not
  authenticated, run the recovery flow above before retrying.
- **Read before write:** when posting/commenting/messaging, first read the
  target (e.g. `posts comments`, `messages read`) to confirm context, then
  perform the write.
- **Always parse `--json`:** short text output is for humans only and omits
  fields like URLs, ids, and unread flags.
- **One action at a time per session:** the worker serializes commands per
  session; do not run concurrent commands against the same `--session`.
- **Selectors are conservative on purpose:** Facebook DOM varies by
  locale/account; failures surface clearly. If a read returns fewer items
  than expected, the visible browser window (in non-headless mode) is the
  debugging surface.

## Cross-references

- Project README: `README.md` — install, quickstart, command table, env vars.
- Browser operation guide: `BROWSER_OPERATION.md` — operating conventions
  and the authentication flow.
- Development tasks: see `AGENTS.md` (use `uv run`, `uv sync`).
