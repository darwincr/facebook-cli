from __future__ import annotations

from urllib.parse import urlparse, parse_qs

from facebook_cli.actions.extract import (
    _group_post_result_from_card_data,
    _is_search_result_url,
    _marketplace_result_from_lines,
)
from facebook_cli.actions.profile import search_url
from facebook_cli.cli import _parse_args, build_parser
from facebook_cli.conf import FACEBOOK_BASE_URL

BASE = FACEBOOK_BASE_URL


class TestSearchUrl:
    def test_default_type_top(self):
        url = search_url("open source")
        assert url == f"{BASE}/search/top/?q=open+source"

    def test_type_groups(self):
        url = search_url("debates", search_type="groups")
        assert url == f"{BASE}/search/groups/?q=debates"

    def test_type_pages(self):
        url = search_url("python", search_type="pages")
        assert url == f"{BASE}/search/pages/?q=python"

    def test_type_marketplace_no_location(self):
        url = search_url("mac studio", search_type="marketplace")
        assert url == f"{BASE}/marketplace/search/?query=mac+studio"

    def test_type_marketplace_with_location(self):
        url = search_url("mac studio", search_type="marketplace", location="melbourne")
        assert url == f"{BASE}/marketplace/melbourne/search/?query=mac+studio"

    def test_type_marketplace_with_location_slugged(self):
        url = search_url("bike", search_type="marketplace", location="sydney")
        assert "/marketplace/sydney/search/" in url

    def test_type_videos(self):
        url = search_url("cats", search_type="videos")
        assert url == f"{BASE}/search/videos/?q=cats"

    def test_type_reels(self):
        url = search_url("funny", search_type="reels")
        assert url == f"{BASE}/search/videos/?q=funny"

    def test_special_characters_encoded(self):
        url = search_url("hello world & stuff")
        assert "hello+world+%26+stuff" in url

    def test_group_by_id(self):
        url = search_url("python tips", group="456408921819694")
        assert url == f"{BASE}/groups/456408921819694/search/?q=python+tips"

    def test_group_by_path_with_prefix(self):
        url = search_url("test", group="groups/123456")
        assert url == f"{BASE}/groups/123456/search/?q=test"

    def test_group_by_full_url(self):
        url = search_url("test", group="https://www.facebook.com/groups/987654")
        assert url == f"{BASE}/groups/987654/search/?q=test"

    def test_group_trailing_slash_stripped(self):
        url = search_url("x", group="456408921819694/")
        assert url == f"{BASE}/groups/456408921819694/search/?q=x"

    def test_page_by_path(self):
        url = search_url("hello", page_handle="profile/100057860119506")
        assert url == f"{BASE}/profile/100057860119506/search/?q=hello"

    def test_page_by_full_url(self):
        url = search_url("hello", page_handle="https://www.facebook.com/somepage")
        assert url == f"{BASE}/somepage/search/?q=hello"

    def test_page_trailing_slash_stripped(self):
        url = search_url("x", page_handle="mypage/")
        assert url == f"{BASE}/mypage/search/?q=x"

    def test_group_takes_priority_over_type(self):
        url = search_url("test", search_type="groups", group="12345")
        assert "/groups/12345/search/" in url
        assert "/search/groups/" not in url

    def test_page_takes_priority_over_type(self):
        url = search_url("test", search_type="pages", page_handle="mypage")
        assert "/mypage/search/" in url
        assert "/search/pages/" not in url

    def test_group_takes_priority_over_marketplace(self):
        url = search_url("test", search_type="marketplace", location="melbourne", group="12345")
        assert "/groups/12345/search/" in url
        assert "/marketplace/" not in url

    def test_page_takes_priority_over_marketplace(self):
        url = search_url("test", search_type="marketplace", location="melbourne", page_handle="mypage")
        assert "/mypage/search/" in url
        assert "/marketplace/" not in url

    def test_all_type_choices_have_paths(self):
        for t in ["top", "groups", "pages", "videos", "reels"]:
            url = search_url("x", search_type=t)
            parsed = urlparse(url)
            assert parsed.netloc == "www.facebook.com"
            assert parse_qs(parsed.query).get("q") == ["x"]


class TestSearchCliParsing:
    def _parse(self, *argv):
        return _parse_args(["search", *argv])

    def test_query_only(self):
        args = self._parse("open source")
        assert args.query == "open source"
        assert args.type == "top"
        assert args.location is None
        assert args.group is None
        assert args.page is None

    def test_type_top(self):
        args = self._parse("test", "--type", "top")
        assert args.type == "top"

    def test_type_groups(self):
        args = self._parse("debates", "--type", "groups")
        assert args.type == "groups"

    def test_type_pages(self):
        args = self._parse("pages", "--type", "pages")
        assert args.type == "pages"

    def test_type_marketplace(self):
        args = self._parse("laptop", "--type", "marketplace")
        assert args.type == "marketplace"

    def test_type_videos(self):
        args = self._parse("cats", "--type", "videos")
        assert args.type == "videos"

    def test_type_reels(self):
        args = self._parse("funny", "--type", "reels")
        assert args.type == "reels"

    def test_invalid_type_rejected(self):
        try:
            self._parse("test", "--type", "invalid")
            assert False, "should have raised SystemExit"
        except SystemExit:
            pass

    def test_location_flag(self):
        args = self._parse("laptop", "--type", "marketplace", "--location", "melbourne")
        assert args.location == "melbourne"

    def test_location_without_type(self):
        args = self._parse("laptop", "--location", "melbourne")
        assert args.location == "melbourne"
        assert args.type == "top"

    def test_group_flag(self):
        args = self._parse("python", "--group", "456408921819694")
        assert args.group == "456408921819694"

    def test_page_flag(self):
        args = self._parse("hello", "--page", "profile/100057860119506")
        assert args.page == "profile/100057860119506"

    def test_limit_default(self):
        args = self._parse("test")
        assert args.limit == 10

    def test_limit_custom(self):
        args = self._parse("test", "--limit", "5")
        assert args.limit == 5

    def test_all_flags_combined(self):
        args = self._parse(
            "laptop", "--type", "marketplace", "--location", "melbourne",
            "--group", "12345", "--page", "mypage", "--limit", "3", "--json",
        )
        assert args.query == "laptop"
        assert args.type == "marketplace"
        assert args.location == "melbourne"
        assert args.group == "12345"
        assert args.page == "mypage"
        assert args.limit == 3
        assert args.json is True

    def test_verb_is_search(self):
        args = self._parse("test")
        assert args.verb == "search"

    def test_search_help_choices_in_parser(self):
        parser = build_parser()
        subparsers_action = None
        for a in parser._actions:
            if hasattr(a, "choices") and "search" in (a.choices or {}):
                subparsers_action = a
                break
        assert subparsers_action is not None
        search_parser = subparsers_action.choices["search"]
        action = None
        for a in search_parser._actions:
            if getattr(a, "dest", None) == "type":
                action = a
                break
        assert action is not None
        assert set(action.choices) == {"top", "groups", "pages", "marketplace", "videos", "reels"}


class TestSearchResultUrlFiltering:
    def test_marketplace_allows_item_links(self):
        assert _is_search_result_url(
            "https://www.facebook.com/marketplace/item/123456789/",
            search_type="marketplace",
        )

    def test_marketplace_rejects_sidebar_links(self):
        urls = [
            "https://www.facebook.com/marketplace/",
            "https://www.facebook.com/marketplace/create/",
            "https://www.facebook.com/marketplace/melbourne/search/?category_id=479353692612078&query=Electronics",
            "https://www.facebook.com/marketplace/melbourne/free/",
            "https://www.facebook.com/marketplace/melbourne/propertyrentals/",
        ]
        for url in urls:
            assert not _is_search_result_url(url, search_type="marketplace")

    def test_non_marketplace_keeps_existing_url_behavior(self):
        assert _is_search_result_url("https://www.facebook.com/search/top/?q=python", search_type="top")


class TestMarketplaceResultParsing:
    def test_splits_price_title_and_location(self):
        result = _marketplace_result_from_lines([
            "AU$2,200",
            "Macbook Pro M5",
            "Melbourne, VIC",
        ])

        assert result == {
            "price": "AU$2,200",
            "title": "Macbook Pro M5",
            "location": "Melbourne, VIC",
        }

    def test_keeps_extra_lines_as_metadata(self):
        result = _marketplace_result_from_lines([
            "AU$1,850",
            "Preowned Apple Mac Studio 32GB 512GB 10 Core",
            "Melbourne, VIC",
            "Listed 2 days ago",
        ])

        assert result == {
            "price": "AU$1,850",
            "title": "Preowned Apple Mac Studio 32GB 512GB 10 Core",
            "location": "Melbourne, VIC",
            "metadata": ["Listed 2 days ago"],
        }

    def test_splits_discounted_price_title_and_location(self):
        result = _marketplace_result_from_lines([
            "AU$150",
            "AU$200",
            "iMac 27inch 2009 late",
            "Melbourne, VIC",
        ])

        assert result == {
            "price": "AU$150",
            "original_price": "AU$200",
            "title": "iMac 27inch 2009 late",
            "location": "Melbourne, VIC",
        }

    def test_handles_missing_price(self):
        result = _marketplace_result_from_lines([
            "Mac Studio M1 Ultra",
            "Melbourne, VIC",
        ])

        assert result == {
            "title": "Mac Studio M1 Ultra",
            "location": "Melbourne, VIC",
        }


class TestGroupPostResultParsing:
    def test_parses_group_post_card_fields(self):
        result = _group_post_result_from_card_data({
            "author_name": "Darwin CR",
            "author_url": "https://www.facebook.com/groups/456408921819694/user/100002200046699/?__tn__=-UC%2CP-R",
            "content_lines": [
                "Segundo as fontes que eu considero honestas, este é o triste retrato do conflito na Ucrania em termos de perdas",
                "Alexandre Nunes o que as suas fontes mais confiaveis dizem pra voce sobre as perdas nesse conflito?",
            ],
            "links": [
                {
                    "text": "Darwin CR",
                    "href": "https://www.facebook.com/groups/456408921819694/user/100002200046699/?__tn__=-UC%2CP-R",
                },
                {
                    "text": "Alexandre Nunes",
                    "href": "https://www.facebook.com/groups/456408921819694/user/100002424879392/?__tn__=-]K-R",
                },
                {
                    "text": "",
                    "href": "https://www.facebook.com/photo/?fbid=10039645609452007&set=gm.1874793993314506",
                },
            ],
            "images": [
                {
                    "alt": "No photo description available.",
                    "src": "https://scontent.fsyd3-2.fna.fbcdn.net/example.jpg",
                },
                {"alt": "", "src": "data:image/svg+xml,ignored"},
            ],
            "buttons": [
                {"aria": "Like", "text": "4"},
                {"aria": "Leave a comment", "text": "21"},
                {"aria": "Like: 2 people", "text": ""},
                {"aria": "Sad: 2 people", "text": ""},
            ],
        })

        assert result is not None
        assert result["type"] == "group_post"
        assert result["author"] == "Darwin CR"
        assert result["title"] == "Darwin CR"
        assert result["content_lines"] == [
            "Segundo as fontes que eu considero honestas, este é o triste retrato do conflito na Ucrania em termos de perdas",
            "Alexandre Nunes o que as suas fontes mais confiaveis dizem pra voce sobre as perdas nesse conflito?",
        ]
        assert result["mentioned_users"] == [
            {
                "name": "Alexandre Nunes",
                "url": "https://www.facebook.com/groups/456408921819694/user/100002424879392/?__tn__=-]K-R",
            }
        ]
        assert result["has_media"] is True
        assert result["media"] == [
            {
                "type": "image",
                "src": "https://scontent.fsyd3-2.fna.fbcdn.net/example.jpg",
                "alt": "No photo description available.",
                "url": "https://www.facebook.com/photo/?fbid=10039645609452007&set=gm.1874793993314506",
            }
        ]
        assert result["reactions"] == {"count": 4, "breakdown": {"Like": 2, "Sad": 2}}
        assert result["comment_count"] == 21
