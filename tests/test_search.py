from __future__ import annotations

from urllib.parse import urlparse, parse_qs

from facebook_cli.actions.extract import (
    default_search_max_scrolls,
    _group_post_result_from_card_data,
    _group_timeline_post_from_data,
    _is_search_result_url,
    _marketplace_result_from_lines,
)
from facebook_cli.actions.posts import group_url
from facebook_cli.actions.profile import search_url
from facebook_cli.actions.marketplace import marketplace_url
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
        return _parse_args(["post", "search", *argv])

    def test_query_only(self):
        args = self._parse("open source")
        assert args.query == "open source"
        assert args.search_type == "top"
        assert args.group is None
        assert args.page is None

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
            "laptop", "--group", "12345", "--limit", "3", "--json",
        )
        assert args.query == "laptop"
        assert args.search_type == "top"
        assert args.group == "12345"
        assert args.page is None
        assert args.limit == 3
        assert args.json is True

    def test_group_and_page_are_mutually_exclusive(self):
        try:
            self._parse("test", "--group", "12345", "--page", "mypage")
            assert False, "should have raised SystemExit"
        except SystemExit:
            pass

    def test_verb_is_search(self):
        args = self._parse("test")
        assert args.verb == "post-search"

    def test_profile_search(self):
        args = _parse_args(["profile", "search", "pages"])
        assert args.search_type == "pages"
        assert args.verb == "profile-search"

    def test_group_search(self):
        args = _parse_args(["group", "search", "debates"])
        assert args.search_type == "groups"
        assert args.verb == "group-search"

    def test_marketplace_search(self):
        args = _parse_args(["marketplace", "search", "laptop", "--location", "melbourne"])
        assert args.search_type == "marketplace"
        assert args.location == "melbourne"
        assert args.verb == "marketplace-search"

    def test_marketplace_read(self):
        args = _parse_args(["marketplace", "read", "123456"])
        assert args.item == "123456"
        assert args.verb == "marketplace-read"

    def test_marketplace_seller(self):
        args = _parse_args(["marketplace", "seller", "marketplace/item/123456"])
        assert args.item_or_profile == "marketplace/item/123456"
        assert args.verb == "marketplace-seller"

    def test_marketplace_message(self):
        args = _parse_args(["marketplace", "message", "123456", "--text", "hello"])
        assert args.item == "123456"
        assert args.text == "hello"
        assert args.dry_run is False
        assert args.verb == "marketplace-message"

    def test_marketplace_message_dry_run(self):
        args = _parse_args(["marketplace", "message", "123456", "--text", "hello", "--dry-run"])
        assert args.item == "123456"
        assert args.text == "hello"
        assert args.dry_run is True
        assert args.verb == "marketplace-message"

    def test_marketplace_messages(self):
        args = _parse_args(["marketplace", "messages", "123456", "--limit", "8"])
        assert args.item == "123456"
        assert args.limit == 8
        assert args.verb == "marketplace-messages"

    def test_video_search(self):
        args = _parse_args(["video", "search", "cats"])
        assert args.search_type == "videos"
        assert args.verb == "video-search"

    def test_reel_search(self):
        args = _parse_args(["reel", "search", "funny"])
        assert args.search_type == "reels"
        assert args.verb == "reel-search"


class TestPostsCreateCliParsing:
    def _parse(self, *argv):
        return _parse_args(["post", "create", *argv])

    def test_feed_post_by_default(self):
        args = self._parse("--text", "hello")
        assert args.text == "hello"
        assert args.group is None
        assert args.verb == "post-create"

    def test_group_flag(self):
        args = self._parse("--text", "hello", "--group", "456408921819694")
        assert args.group == "456408921819694"


class TestPostsGroupCliParsing:
    def _parse(self, *argv):
        return _parse_args(["group", "posts", *argv])

    def test_group_posts_default_limit(self):
        args = self._parse("456408921819694")
        assert args.group == "456408921819694"
        assert args.limit == 10
        assert args.verb == "group-posts"

    def test_group_posts_custom_limit(self):
        args = self._parse("groups/123", "--limit", "3")
        assert args.limit == 3


class TestPostsCommentsCliParsing:
    def test_comments_command(self):
        args = _parse_args(["post", "comments", "https://www.facebook.com/groups/1/posts/2", "--limit", "25"])
        assert args.post_url == "https://www.facebook.com/groups/1/posts/2"
        assert args.limit == 25
        assert args.verb == "post-comments"

    def test_comment_command(self):
        args = _parse_args(["post", "comment", "https://www.facebook.com/groups/1/posts/2", "--text", "hello"])
        assert args.post_url == "https://www.facebook.com/groups/1/posts/2"
        assert args.text == "hello"
        assert args.verb == "post-comment"

    def test_post_read_command(self):
        args = _parse_args(["post", "read", "https://www.facebook.com/groups/1/posts/2"])
        assert args.post_url == "https://www.facebook.com/groups/1/posts/2"
        assert args.verb == "post-read"


class TestNewNounCliParsing:
    def test_profile_read(self):
        args = _parse_args(["profile", "read", "zuck", "--limit", "2"])
        assert args.handle == "zuck"
        assert args.limit == 2
        assert args.verb == "profile-read"

    def test_group_read(self):
        args = _parse_args(["group", "read", "456408921819694"])
        assert args.group == "456408921819694"
        assert args.verb == "group-read"

    def test_feed_read(self):
        args = _parse_args(["feed", "read", "--limit", "4"])
        assert args.limit == 4
        assert args.verb == "feed-read"

    def test_thread_list(self):
        args = _parse_args(["thread", "list", "--limit", "7"])
        assert args.limit == 7
        assert args.verb == "thread-list"

    def test_thread_read(self):
        args = _parse_args(["thread", "read", "messages/t/123", "--limit", "8"])
        assert args.target == "messages/t/123"
        assert args.limit == 8
        assert args.verb == "thread-read"

    def test_message_send(self):
        args = _parse_args(["message", "send", "messages/t/123", "--text", "hello"])
        assert args.target == "messages/t/123"
        assert args.text == "hello"
        assert args.verb == "message-send"

    def test_auth_login(self):
        args = _parse_args(["auth", "login", "--interactive", "--wait", "--timeout", "9"])
        assert args.interactive is True
        assert args.wait is True
        assert args.timeout == 9
        assert args.verb == "auth-login"


class TestGroupUrl:
    def test_group_by_id(self):
        assert group_url("456408921819694") == f"{BASE}/groups/456408921819694"

    def test_group_by_path_with_prefix(self):
        assert group_url("groups/123456") == f"{BASE}/groups/123456"

    def test_group_by_full_url(self):
        assert group_url("https://www.facebook.com/groups/987654") == f"{BASE}/groups/987654"

    def test_group_trailing_slash_stripped(self):
        assert group_url("456408921819694/") == f"{BASE}/groups/456408921819694"


class TestSearchScrollingDefaults:
    def test_default_max_scrolls_buffers_estimated_batches(self):
        assert default_search_max_scrolls(25) == 3
        assert default_search_max_scrolls(50) == 4
        assert default_search_max_scrolls(100) == 6

    def test_default_max_scrolls_handles_small_limits(self):
        assert default_search_max_scrolls(1) == 3


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


class TestMarketplaceUrl:
    def test_item_id(self):
        assert marketplace_url("123456") == f"{BASE}/marketplace/item/123456"

    def test_item_path(self):
        assert marketplace_url("marketplace/item/123456") == f"{BASE}/marketplace/item/123456"

    def test_profile_path(self):
        assert marketplace_url("profile/123456") == f"{BASE}/marketplace/profile/123456"

    def test_full_url(self):
        url = "https://www.facebook.com/marketplace/item/123456/"
        assert marketplace_url(url) == url


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


class TestGroupTimelinePostParsing:
    def test_parses_direct_group_timeline_post(self):
        result = _group_timeline_post_from_data({
            "author": {
                "name": "Adão Mamedes",
                "url": "https://www.facebook.com/groups/456408921819694/user/100046201956364/?x=1",
            },
            "messages": ["Na manhã de 15 de setembro de 1963, quatro meninas entraram em uma igreja."],
            "badges": ["Group expert", "All-star contributor"],
            "privacy": "Shared with Private group",
            "links": [
                {"text": "Adão Mamedes", "href": "https://www.facebook.com/groups/456408921819694/user/100046201956364/?x=1"},
                {"text": "photo", "href": "https://www.facebook.com/photo/?fbid=1561236048759779&set=gm.2183943222399580"},
            ],
            "buttons": [
                {"aria": "Like", "text": "1"},
                {"aria": "Leave a comment", "text": "3"},
            ],
        })

        assert result["author"] == "Adão Mamedes"
        assert result["content"] == "Na manhã de 15 de setembro de 1963, quatro meninas entraram em uma igreja."
        assert result["author_badges"] == ["Group expert", "All-star contributor"]
        assert result["privacy"] == "Shared with Private group"
        assert result["is_repost"] is False
        assert result["post_url"] == "https://www.facebook.com/photo/?fbid=1561236048759779&set=gm.2183943222399580"
        assert result["reactions"] == {"count": 1}
        assert result["comment_count"] == 3

    def test_parses_reposted_group_timeline_post(self):
        result = _group_timeline_post_from_data({
            "author": {
                "name": "Flavio Terra",
                "url": "https://www.facebook.com/groups/456408921819694/user/100002145610003/",
            },
            "messages": [
                "Projeto sionista não tem aprovação do Conselho Nacional dos Direitos Humanos",
                "Parecer do CNDH afirma que PL 1424 restringe a liberdade de expressão.",
            ],
            "shared_author": {
                "name": "Opera Mundi",
                "url": "https://www.facebook.com/operamundi.br",
            },
            "link_preview": {
                "title": "Conselho de Direitos Humanos pede rejeição de projeto que criminaliza críticas a Israel",
                "domain": "operamundi.uol.com.br",
                "url": "https://operamundi.uol.com.br/example",
            },
            "links": [],
            "buttons": [],
        })

        assert result["author"] == "Flavio Terra"
        assert result["content"] == "Projeto sionista não tem aprovação do Conselho Nacional dos Direitos Humanos"
        assert result["is_repost"] is True
        assert result["shared_post"]["author"] == "Opera Mundi"
        assert result["shared_post"]["content"] == "Parecer do CNDH afirma que PL 1424 restringe a liberdade de expressão."
        assert result["shared_post"]["link_preview"]["domain"] == "operamundi.uol.com.br"
