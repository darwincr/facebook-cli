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


def facebook_cli_home() -> Path:
    return Path(os.environ.get("FACEBOOK_CLI_HOME") or Path.home() / ".facebook-cli")


def browser_headless() -> bool:
    return os.environ.get("FACEBOOK_CLI_HEADLESS", "").lower() in {"1", "true", "yes", "on"}
