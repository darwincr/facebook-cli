from __future__ import annotations

import os
from pathlib import Path

FACEBOOK_BASE_URL = "https://www.facebook.com"
FACEBOOK_LOGIN_URL = f"{FACEBOOK_BASE_URL}/login"
FACEBOOK_HOME_URL = f"{FACEBOOK_BASE_URL}/"

BROWSER_DEFAULT_TIMEOUT_MS = 30_000
BROWSER_LOGIN_TIMEOUT_MS = 60_000
HUMAN_TYPE_DELAY_MS = 65
DEFAULT_MIN_PACE_S = 1.2
DEFAULT_MAX_PACE_S = 2.8
WORKER_IDLE_TIMEOUT_S = 900


def load_dotenv_fallback(path: Path | None = None) -> None:
    dotenv = path or Path.cwd() / ".env"
    try:
        lines = dotenv.read_text().splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        key, value = _dotenv_pair(line)
        if key and key not in os.environ:
            os.environ[key] = value


def _dotenv_pair(line: str) -> tuple[str | None, str]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None, ""
    if stripped.startswith("export "):
        stripped = stripped.removeprefix("export ").lstrip()
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None, ""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def facebook_cli_home() -> Path:
    return Path(os.environ.get("FACEBOOK_CLI_HOME") or Path.home() / ".facebook-cli")


def browser_headless() -> bool:
    return os.environ.get("FACEBOOK_CLI_HEADLESS", "").lower() in {"1", "true", "yes", "on"}
