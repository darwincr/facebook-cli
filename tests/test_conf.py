from __future__ import annotations

import os

from facebook_cli.conf import load_dotenv_fallback
from facebook_cli.worker import _request_environment


def test_load_dotenv_fallback_sets_missing_env(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("FACEBOOK_CLI_MESSENGER_PIN=123456\n", encoding="utf-8")
    monkeypatch.delenv("FACEBOOK_CLI_MESSENGER_PIN", raising=False)

    load_dotenv_fallback(dotenv)

    assert os.environ["FACEBOOK_CLI_MESSENGER_PIN"] == "123456"


def test_load_dotenv_fallback_does_not_override_shell_env(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("FACEBOOK_CLI_MESSENGER_PIN=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("FACEBOOK_CLI_MESSENGER_PIN", "from-shell")

    load_dotenv_fallback(dotenv)

    assert os.environ["FACEBOOK_CLI_MESSENGER_PIN"] == "from-shell"


def test_load_dotenv_fallback_supports_quotes_comments_and_export(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("# comment\nexport FACEBOOK_CLI_LOG='DEBUG'\nFACEBOOK_CLI_HEADLESS=\"1\"\n", encoding="utf-8")
    monkeypatch.delenv("FACEBOOK_CLI_LOG", raising=False)
    monkeypatch.delenv("FACEBOOK_CLI_HEADLESS", raising=False)

    load_dotenv_fallback(dotenv)

    assert os.environ["FACEBOOK_CLI_LOG"] == "DEBUG"
    assert os.environ["FACEBOOK_CLI_HEADLESS"] == "1"


def test_request_environment_temporarily_applies_client_env(monkeypatch):
    monkeypatch.setenv("FACEBOOK_CLI_MESSENGER_PIN", "worker-old")

    with _request_environment({"FACEBOOK_CLI_MESSENGER_PIN": "client-new", "OTHER": "ignored"}):
        assert os.environ["FACEBOOK_CLI_MESSENGER_PIN"] == "client-new"
        assert "OTHER" not in os.environ

    assert os.environ["FACEBOOK_CLI_MESSENGER_PIN"] == "worker-old"
