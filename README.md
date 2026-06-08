# facebook-cli

Drive Facebook from the command line through a real Camoufox browser profile.

This is a small Facebook-oriented sibling of the LinkedIn CLI. It keeps the same
agent-friendly shape: short commands, JSON output on demand, browser state stored
locally, and no SaaS/API key/database.

## Install

```bash
uv sync
uv run python -m camoufox fetch
```

## Quickstart

```bash
facebook-cli login
facebook-cli login --interactive --wait --timeout 300  # if login reports interactive_authentication_required
facebook-cli auth status --json
facebook-cli whoami --json
facebook-cli profile zuck --json
facebook-cli search "open source ai" --limit 10 --json
facebook-cli search "mac studio ultra" --type marketplace --location melbourne --json
facebook-cli search debates --type groups --json
facebook-cli search a --group 456408921819694 --json
facebook-cli search pages --type pages --json
facebook-cli search a --page profile/100057860119506 --json
facebook-cli search reelsearch --type reels --json
facebook-cli posts feed --limit 10 --json
facebook-cli posts profile zuck --limit 5 --json
facebook-cli posts create --text "Hello from facebook-cli"
facebook-cli messages threads --limit 10 --json
facebook-cli messages read --limit 20 --json
facebook-cli messages send "https://www.facebook.com/messages/t/<thread>" --text "Hello from facebook-cli"
```

Use `--session work` or `$FACEBOOK_CLI_SESSION` to keep separate browser
profiles. Profiles are stored in `~/.facebook-cli/profiles/<session>` unless
`$FACEBOOK_CLI_HOME` is set.

Commands reuse a per-session background Camoufox worker by default. The first
command for a session starts the browser, later commands connect to the same
browser instance, and rapid sequential commands are queued through one local
socket so only one action touches the session at a time. The worker exits after
being idle for a while; the next command starts it again using the same
persistent profile.

## Commands

`--session <name>` and `--json` work on every command.

| Command | What it does |
|---|---|
| `login` | Verify the current Facebook session; reports `interactive_authentication_required` if a login form is visible. |
| `login --interactive` | Open Facebook and keep the browser alive while you log in manually. |
| `login --interactive --wait --timeout 300` | Open Facebook, wait for manual login/checkpoint completion, then exit automatically. |
| `auth status` | Report whether the current session is logged in, needs login, or is checkpointed. |
| `auth interactive` | Open Facebook and keep the browser alive while you log in manually. |
| `whoami` | Report the visible account name and profile URL. |
| `profile <id-or-url>` | Open a profile/page and extract visible name, intro, URL, and visible recent post cards. |
| `search <query>` | Search Facebook and return visible results. Supports `--type top|groups|pages|marketplace|videos|reels`, `--location` for Marketplace, and scoped `--group` / `--page` searches. |
| `posts feed` | Extract visible feed posts. |
| `posts profile <id-or-url>` | Extract visible posts from a profile/page timeline. |
| `posts create --text TEXT` | Create a text post using the composer. |
| `messages threads` | List visible Messenger threads with names, preview text, URLs, and best-effort unread flags. |
| `messages read [target]` | Read visible messages from a Messenger thread, URL, path, or thread id. |
| `messages send <target> --text TEXT` | Send one message to an explicit Messenger thread URL/id or recipient search text. |
| `session clear` | Remove the local browser profile for the session. |

Facebook changes DOM labels frequently and varies by locale/account state. The
implementation intentionally favors visible-browser actions and conservative
selectors so failures are easy to debug in the opened Camoufox window.

## Environment

- `FACEBOOK_CLI_SESSION`: default session name.
- `FACEBOOK_CLI_HOME`: state root, default `~/.facebook-cli`.
- `FACEBOOK_CLI_HEADLESS`: set to `1`, `true`, or `yes` for headless mode.
- `FACEBOOK_CLI_LOG`: Python logging level, default `INFO`.
- `FACEBOOK_CLI_MESSENGER_PIN`: optional Messenger PIN/code used only when a
  Messenger PIN prompt is visible.

The CLI does not accept or read Facebook credentials. If the account is not
authenticated, commands return `interactive_authentication_required`; run
`facebook-cli login --interactive --wait --timeout 300`, complete the login
manually in the Camoufox browser, and the command exits automatically once the
session is authenticated.

For agent workflows, prefer `facebook-cli auth status --json` before taking an
action. JSON errors include `ok: false`, an `error.type`, and, when applicable,
`next_command` for the manual browser login flow.
