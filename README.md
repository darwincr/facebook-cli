# facebook-cli

Drive Facebook from the command line through a real browser profile.

`facebook-cli` keeps browser state locally, emits JSON on demand, and does not
use Facebook credentials, SaaS APIs, API keys, or a database.

## Install

```bash
uv tool install "git+https://github.com/darwincr/facebook-cli.git@main"
uv run python -m playwright install chromium
facebook-cli --help
```

## Quickstart

```bash
facebook-cli auth status --json
facebook-cli auth login --interactive --wait --timeout 300
facebook-cli profile read zuck --json
facebook-cli profile search "open source ai" --limit 10 --json
facebook-cli group read 456408921819694 --json
facebook-cli group search debates --json
facebook-cli group posts 456408921819694 --limit 10 --json
facebook-cli post read "https://www.facebook.com/groups/<group>/posts/<post>" --json
facebook-cli post search a --group 456408921819694 --json
facebook-cli post search a --page profile/100057860119506 --json
facebook-cli post create --text "Hello from facebook-cli"
facebook-cli post create --group 456408921819694 --text "Hello group from facebook-cli"
facebook-cli post comments "https://www.facebook.com/groups/<group>/posts/<post>" --limit 50 --json
facebook-cli post comment "https://www.facebook.com/groups/<group>/posts/<post>" --text "Hello comment" --json
facebook-cli feed read --limit 10 --json
facebook-cli marketplace search "mac studio ultra" --location melbourne --json
facebook-cli marketplace read "https://www.facebook.com/marketplace/item/<item>" --json
facebook-cli marketplace seller "https://www.facebook.com/marketplace/item/<item>" --json
facebook-cli marketplace message "https://www.facebook.com/marketplace/item/<item>" --text "Is this still available?" --dry-run --json
facebook-cli marketplace message "https://www.facebook.com/marketplace/item/<item>" --text "Is this still available?" --json
facebook-cli marketplace thread list --limit 20 --json
facebook-cli thread read "https://www.facebook.com/messages/t/<thread>" --limit 20 --json
facebook-cli video search cats --json
facebook-cli reel search funny --json
facebook-cli thread list --limit 10 --json
facebook-cli thread read "https://www.facebook.com/messages/t/<thread>" --limit 20 --json
facebook-cli message send "https://www.facebook.com/messages/t/<thread>" --text "Hello from facebook-cli"
```

Use `--session work` or `$FACEBOOK_CLI_SESSION` to keep separate browser
profiles. Profiles are stored in `~/.facebook-cli/profiles/<session>` unless
`$FACEBOOK_CLI_HOME` is set.

Environment variables from the shell are the primary source. If a variable is
not set in the shell, the CLI falls back to a local `.env` file in the current
working directory. `.env` is gitignored and is intended for workstation-local
values such as `FACEBOOK_CLI_MESSENGER_PIN`.

Commands reuse a per-session background Playwright Chromium worker by default.
The first command for a session starts the browser, later commands connect to
the same browser instance, and rapid sequential commands are queued through one
local socket so only one action touches the session at a time. The worker exits
after being idle for a while; the next command starts it again using the same
persistent profile.

## Commands

`--session <name>` and `--json` work on every leaf command.

| Command | What it does |
|---|---|
| `auth status` | Report whether the current session is logged in, needs login, or is checkpointed. JSON output includes visible account details when authenticated. |
| `auth login` | Verify the current Facebook session; reports `interactive_authentication_required` if a login form is visible. |
| `auth login --interactive --wait --timeout 300` | Open Facebook, wait for manual login/checkpoint completion, then exit automatically. |
| `session clear` | Delete the local browser profile for the session, including saved Facebook login state. |
| `profile read <handle> [--limit N]` | Open a profile/page and extract visible name, intro, URL, and visible recent post cards. |
| `profile search <q> [--limit N]` | Search Facebook pages/profiles. |
| `group read <id>` | Open a group and extract visible name, privacy, members, and description from the group header. |
| `group search <q> [--limit N]` | Search Facebook groups. |
| `group posts <id> [--limit N]` | Extract visible posts from a group timeline. |
| `post read <url>` | Open a post permalink and extract the visible post. |
| `post search <q> [--group G \| --page P] [--limit N]` | Search posts globally or scoped inside a specific group/page. |
| `post create --text TEXT [--group GROUP]` | Create a text post using the composer. With `--group`, post to a group id, path, or URL instead of your feed. |
| `post comments <url> [--limit N]` | Extract visible comments from a post permalink. |
| `post comment <url> --text TEXT` | Add a comment to a post permalink. |
| `feed read [--limit N]` | Extract visible feed posts. |
| `marketplace search <q> [--location L]` | Search Marketplace listings. |
| `marketplace read <item>` | Open a Marketplace listing URL/id and extract visible title, price, seller, details, and images. |
| `marketplace seller <item-or-profile>` | Read visible seller details from a listing or Marketplace seller profile. |
| `marketplace message <item> --text TEXT [--dry-run]` | Open a listing's seller chat and send a message. With `--dry-run`, inspect the chat UI and report what would be sent without typing or sending. |
| `marketplace thread list [--limit N]` | List visible Marketplace Messenger threads by opening Messages and applying the Marketplace thread filter. |
| `video search <q>` | Search Facebook videos. |
| `reel search <q>` | Search Facebook reels. |
| `thread list [--limit N]` | List visible Messenger threads with names, preview text, URLs, and best-effort unread flags. |
| `thread read <target> [--limit N]` | Read visible messages from a Messenger thread URL, path, or thread id. |
| `message send <target> --text TEXT` | Send one message to an explicit Messenger thread URL/id or recipient search text. |

Facebook changes DOM labels frequently and varies by locale/account state. The
implementation intentionally favors visible-browser actions and conservative
selectors so failures are easy to debug in the opened browser window.

## Environment

- `FACEBOOK_CLI_SESSION`: default session name.
- `FACEBOOK_CLI_HOME`: state root, default `~/.facebook-cli`.
- `FACEBOOK_CLI_HEADLESS`: set to `1`, `true`, or `yes` for headless mode.
- `FACEBOOK_CLI_LOG`: Python logging level, default `INFO`.
- `FACEBOOK_CLI_MESSENGER_PIN`: optional Messenger PIN/code used only when a Messenger PIN prompt is visible. Shell env wins over `.env`.

Messenger commands return `error.type: "messenger_pin_required"` when a PIN is
currently required and cannot be supplied. Successful Messenger commands include
`pin_status`: `not_required` when no PIN prompt was active for that command, or
`unlocked_with_env_pin` when the CLI used `FACEBOOK_CLI_MESSENGER_PIN` during
the command. The older boolean `pin_unlocked` is kept for compatibility.

## Testing

When a user asks an agent to validate the project, run both the unit tests and
the live integration tests unless the user explicitly asks for a narrower check:

```bash
uv run pytest tests/test_search.py -v
uv run pytest tests/test_search_live.py -v -s
```

The live integration tests use the configured default browser profile and expect
that profile to already be authenticated with Facebook.

The CLI does not accept or read Facebook credentials. If the account is not
`facebook-cli auth login --interactive --wait --timeout 300`, complete the login
manually in the browser, and the command exits automatically once the session is

For agent workflows, prefer `facebook-cli auth status --json` before taking an
`next_command` for the manual browser login flow.
