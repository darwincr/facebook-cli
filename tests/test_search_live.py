"""Live integration tests for search endpoints.

Runs the real CLI against Facebook via the browser session. Requires an
authenticated session already logged in (run ``facebook-cli login`` first).

Usage:
    FACEBOOK_CLI_HEADLESS=1 uv run pytest tests/test_search_live.py -v -s
    # or without headless to watch the browser:
    uv run pytest tests/test_search_live.py -v -s

Each test invokes ``facebook-cli search … --json`` via ``main()`` and asserts
that the command exits cleanly and the JSON payload has the expected shape.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest


def _cli(*args: str, session: str = "default") -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "facebook_cli.cli", *args, "--session", session, "--json"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def _parse(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, (
        f"CLI exited {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="session", autouse=True)
def check_auth():
    r = _cli("auth", "status")
    data = json.loads(r.stdout)
    if not data.get("authenticated"):
        pytest.skip("Not logged in — run: facebook-cli login --interactive --wait")


class TestSearchTypeTop:
    def test_basic_query(self):
        r = _parse(_cli("search", "facebook"))
        assert r["query"] == "facebook"
        assert r["search_type"] == "top"
        assert "results" in r

    def test_explicit_top(self):
        r = _parse(_cli("search", "python", "--type", "top"))
        assert r["search_type"] == "top"
        assert "/search/top/" in r["url"]


class TestSearchTypeGroups:
    def test_groups(self):
        r = _parse(_cli("search", "open source", "--type", "groups"))
        assert r["search_type"] == "groups"
        assert "/search/groups/" in r["url"]


class TestSearchTypePages:
    def test_pages(self):
        r = _parse(_cli("search", "python", "--type", "pages"))
        assert r["search_type"] == "pages"
        assert "/search/pages/" in r["url"]


class TestSearchTypeVideos:
    def test_videos(self):
        r = _parse(_cli("search", "cats", "--type", "videos"))
        assert r["search_type"] == "videos"
        assert "/search/videos/" in r["url"]


class TestSearchTypeReels:
    def test_reels(self):
        r = _parse(_cli("search", "funny", "--type", "reels"))
        assert r["search_type"] == "reels"
        assert "/search/videos/" in r["url"]


class TestSearchTypeMarketplace:
    def test_marketplace_no_location(self):
        r = _parse(_cli("search", "laptop", "--type", "marketplace"))
        assert r["search_type"] == "marketplace"
        assert "/marketplace/" in r["url"]
        assert "/search/" in r["url"]
        assert "results" in r

    def test_marketplace_with_location(self):
        r = _parse(_cli("search", "bike", "--type", "marketplace", "--location", "sydney"))
        assert r["search_type"] == "marketplace"
        assert "/marketplace/sydney/search/" in r["url"]


class TestSearchGroupScoped:
    def test_group_by_id(self):
        r = _parse(_cli("search", "tips", "--group", "456408921819694"))
        assert "/groups/456408921819694/search/" in r["url"]

    def test_group_overrides_type(self):
        r = _parse(_cli("search", "test", "--type", "groups", "--group", "456408921819694"))
        assert "/groups/456408921819694/search/" in r["url"]
        assert "/search/groups/" not in r["url"]

    def test_group_overrides_marketplace(self):
        r = _parse(_cli(
            "search", "test", "--type", "marketplace",
            "--location", "melbourne", "--group", "456408921819694",
        ))
        assert "/groups/456408921819694/search/" in r["url"]
        assert "/marketplace/" not in r["url"]


class TestSearchPageScoped:
    def test_page_by_path(self):
        r = _parse(_cli("search", "hello", "--page", "profile/100057860119506"))
        assert "/profile/100057860119506/search/" in r["url"]

    def test_page_overrides_type(self):
        r = _parse(_cli("search", "test", "--type", "pages", "--page", "profile/100057860119506"))
        assert "/profile/100057860119506/search/" in r["url"]
        assert "/search/pages/" not in r["url"]

    def test_page_overrides_marketplace(self):
        r = _parse(_cli(
            "search", "test", "--type", "marketplace",
            "--location", "melbourne", "--page", "profile/100057860119506",
        ))
        assert "/profile/100057860119506/search/" in r["url"]
        assert "/marketplace/" not in r["url"]


class TestSearchLimit:
    def test_limit_flag(self):
        r = _parse(_cli("search", "python", "--limit", "3"))
        results = r.get("results") or []
        assert len(results) <= 3


class TestSearchUrlLanding:
    """Verify the browser actually lands on a facebook.com URL after navigation."""

    @pytest.mark.parametrize("stype,expected_path", [
        ("top", "/search/top/"),
        ("groups", "/search/groups/"),
        ("pages", "/search/pages/"),
        ("videos", "/search/videos/"),
        ("reels", "/search/videos/"),
    ])
    def test_url_landing(self, stype, expected_path):
        r = _parse(_cli("search", "testquery", "--type", stype))
        assert r["url"].startswith("https://www.facebook.com")
        assert expected_path in r["url"]
