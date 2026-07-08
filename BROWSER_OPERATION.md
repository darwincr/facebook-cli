# Browser Operation Guide

This CLI drives Facebook through a real Playwright Chromium browser session. All commands
are run via `facebook-cli`.

## General Rules

- Always use `--json` to get structured, parseable output.
- Use `--session <name>` to target a specific session profile (default: `default`).
- Run `<command> --help` to get the current usage, flags, and defaults for any
  command. Options and defaults may change; `--help` is always authoritative.

## Authentication

Sessions start unauthenticated. The CLI never handles credentials — login is
done manually in the browser window.

1. Check state: `facebook-cli auth status --json`
2. If login is needed: `facebook-cli auth login --interactive --wait --timeout 300`
3. Complete login manually in the browser; the command exits automatically.

## Available Domains

For the full list of commands and their options, run:

```bash
facebook-cli --help
```

Each subcommand group also has its own help:

```bash
facebook-cli post --help
facebook-cli thread --help
facebook-cli message --help
facebook-cli auth --help
```

## Key Conventions

- Commands that read data return lists with a `--limit` flag (check `--help` for defaults).
- Commands that perform actions return a status indicating success or failure.
- Errors in JSON output include `ok: false` and an `error.type` field.
- When `error.type` is `interactive_authentication_required`, the agent should
  run `facebook-cli auth login --interactive --wait` and let the user complete login.
- Shell environment variables are primary. Missing values fall back to a local
  gitignored `.env` in the current working directory. Messenger PIN prompts can
  be unlocked with `FACEBOOK_CLI_MESSENGER_PIN` from either source.
- For Messenger, `error.type == "messenger_pin_required"` means a PIN is
  currently required. Successful Messenger JSON includes `pin_status`; do not
  interpret `pin_unlocked: false` as an error.
