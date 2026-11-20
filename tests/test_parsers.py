import json
import re
from pathlib import Path

import pytest

from pulse import router
from pulse.cli import read_urls, render_table
from pulse.extractors import facebook, instagram, meta, tiktok, twitter, youtube
from pulse.models import PostMetrics, PulseError, merge, parse_count

FIX = Path(__file__).parent / "fixtures"


def test_tiktok_parse():
    m = tiktok.parse((FIX / "tiktok_page.html").read_text(), "https://tiktok.com/x")
    assert (m.likes, m.comments, m.shares, m.saves, m.views) == (12345, 321, 45, 678, 987654)
    assert m.author == "someuser"


def test_tiktok_blocked_page():
    with pytest.raises(PulseError):
        tiktok.parse("<html>captcha</html>", "u")


def test_twitter_parse_and_nulls():
    m = twitter.parse(json.loads((FIX / "tweet.json").read_text()), "u")
    assert m.likes == 1500 and m.comments == 42
    assert m.shares is None and m.saves is None and m.views is None


def test_twitter_id_and_token():
    assert twitter.tweet_id("https://x.com/jack/status/20?s=1") == "20"
    tok = twitter.make_token("1800000000000000000")
    assert tok and "." not in tok and "0" not in tok
    with pytest.raises(PulseError):
        twitter.tweet_id("https://x.com/jack")


def test_meta_mapping():
    m = meta.to_metrics({"id": "abc", "like_count": 5, "view_count": 10, "uploader": "bob"}, "instagram", "u")
    assert m.likes == 5 and m.views == 10 and m.author == "bob" and m.saves is None


@pytest.mark.parametrize("url,platform", [
    ("https://www.tiktok.com/@a/video/1", "tiktok"),
    ("https://vm.tiktok.com/abc", "tiktok"),
    ("https://x.com/a/status/1", "twitter"),
    ("https://mobile.twitter.com/a/status/1", "twitter"),
    ("https://www.instagram.com/reel/xyz/", "instagram"),
    ("https://fb.watch/abc", "facebook"),
    ("https://example.com/", None),
    ("https://nottiktok.com/", None),
])
def test_detect_platform(url, platform):
    assert router.detect_platform(url) == platform


def test_cli_helpers(tmp_path):
    f = tmp_path / "l.txt"
    f.write_text("# c\nhttps://a\n\nhttps://b\n")
    assert read_urls(f) == ["https://a", "https://b"]
    m = twitter.parse(json.loads((FIX / "tweet.json").read_text()), "u")
    assert render_table([m]).row_count == 1


def test_parse_count():
    assert parse_count("1,234") == 1234
    assert parse_count("12.5K") == 12500
    assert parse_count("3M") == 3_000_000
    assert parse_count("abc") is None


def test_instagram_og():
    m = instagram.parse((FIX / "instagram_post.html").read_text(), "https://www.instagram.com/p/ABC123/")
    assert (m.likes, m.comments, m.author, m.post_id) == (1234, 56, "someuser", "ABC123")


def test_instagram_abbreviated_and_login_wall():
    page = '<meta property="og:description" content="12K likes, 3 comments - bob on May 1: &quot;x&quot;">'
    m = instagram.parse(page, "https://www.instagram.com/reel/XYZ/")
    assert m.likes == 12000 and m.comments == 3
    with pytest.raises(PulseError):
        instagram.parse("<html></html>", "https://www.instagram.com/p/ABC/")


def test_tiktok_statsv2_saves_and_handle_author():
    url = "https://www.tiktok.com/@exampleuser/video/1"
    m = tiktok.parse((FIX / "tiktok_v2.html").read_text(), url)
    assert m.saves == 98765 and m.likes == 621345 and m.views == 4912345
    assert m.author == "exampleuser"


@pytest.mark.parametrize("url,platform", [
    ("https://www.youtube.com/watch?v=abc", "youtube"),
    ("https://youtu.be/abc", "youtube"),
    ("https://www.youtube.com/shorts/abc", "youtube"),
])
def test_youtube_detect(url, platform):
    assert router.detect_platform(url) == platform


def test_pipeline_and_normalize():
    assert router.pipeline("instagram", "https://www.instagram.com/p/A/")[0] == "instagram"
    assert router.pipeline("instagram", "https://www.instagram.com/reel/A/")[0] == "yt-dlp"
    assert router.pipeline("youtube", "u") == ["yt-dlp"]
    assert router.normalize("https://www.instagram.com/p/A/?utm_source=x&y=1", "instagram") == "https://www.instagram.com/p/A/"
    assert "v=abc" in router.normalize("https://www.youtube.com/watch?v=abc", "youtube")


def test_merge_fills_missing_only():
    a = PostMetrics(platform="x", post_id="1", url="u", likes=5)
    b = PostMetrics(platform="x", post_id="1", url="u", likes=9, views=7, author="z")
    m = merge(a, b)
    assert (m.likes, m.views, m.author) == (5, 7, "z")


def test_facebook_json_beats_og():
    m = facebook.parse((FIX / "facebook_reel.html").read_text(), "https://www.facebook.com/reel/123")
    assert (m.likes, m.shares, m.comments, m.views) == (66712, 5301, 93, 206895)


def test_facebook_og_only_and_wall():
    page = '<meta property="og:description" content="206K views, 66K reactions | caption">'
    m = facebook.parse(page, "https://www.facebook.com/reel/1")
    assert m.views == 206000 and m.likes == 66000
    with pytest.raises(PulseError):
        facebook.parse("<html>log in</html>", "u")


def test_instagram_embed_escaped_json():
    page = (r'<script>"contextJSON":"{\"gql_data\":{\"shortcode_media\":{\"video_view_count\":37900,'
            r'\"owner\":{\"username\":\"example_user\"},\"edge_media_preview_like\":{\"count\":794},'
            r'\"edge_media_to_parent_comment\":{\"count\":1624}}}}"</script>')
    m = instagram.parse(page, "https://www.instagram.com/reel/ABC/", with_author=True)
    assert (m.views, m.likes, m.comments, m.author) == (37900, 794, 1624, "example_user")


def test_instagram_api_and_pk():
    data = {"items": [{"code": "ABC", "like_count": 794, "comment_count": 1624, "play_count": 37900,
                       "media_repost_count": 17, "reshare_count": 493, "user": {"username": "matt"}}]}
    m = instagram.parse_api(data, "u")
    assert (m.views, m.reposts, m.shares, m.author) == (37900, 17, 493, "matt")
    assert instagram.shortcode_to_pk("B") == 1 and instagram.shortcode_to_pk("BA") == 64


def test_fxtwitter_parse():
    data = {"code": 200, "tweet": {"id": "1", "likes": 771, "retweets": 17, "replies": 23,
                                    "views": 73700, "bookmarks": 565, "author": {"screen_name": "d"}}}
    m = twitter.parse_fx(data, "u")
    assert (m.likes, m.reposts, m.comments, m.views, m.saves, m.author) == (771, 17, 23, 73700, 565, "d")


def test_youtube_exact_comments():
    initial = {"contents": [{"itemSectionRenderer": {"sectionIdentifier": "comment-item-section",
               "contents": [{"continuationItemRenderer": {"continuationEndpoint": {
                   "continuationCommand": {"token": "TOK"}}}}]}}]}
    assert youtube.comment_token(initial) == "TOK"
    resp = {"onResponseReceivedEndpoints": [{"reloadContinuationItemsCommand": {"continuationItems": [
        {"commentsHeaderRenderer": {"countText": {"runs": [{"text": "48,802"}, {"text": " Comments"}]}}}]}}]}
    assert youtube.parse_comment_count(resp) == 48802
    small = PostMetrics(platform="youtube", post_id="x", url="u", comments=36)
    assert youtube.refine(small).comments == 36  # under 1000 is already exact, no request made


def test_meta_author_and_counts():
    ig = {"uploader_id": "10000000001", "uploader": "Example User", "channel": "example_user"}
    assert meta.pick_author(ig, "instagram") == "example_user"
    assert meta.pick_author({"uploader_id": "5", "uploader_url": "https://www.instagram.com/mattx/"}, "instagram") == "mattx"
    m = meta.to_metrics({"id": "1", "save_count": 1265, "repost_count": 1651}, "tiktok", "u")
    assert (m.saves, m.shares, m.reposts) == (1265, 1651, None)
    assert meta.to_metrics({"id": "1", "repost_count": 17}, "twitter", "u").reposts == 17


def test_pipelines():
    assert router.pipeline("instagram", "https://www.instagram.com/reel/A/", has_cookies=True)[0] == "ig-api"
    assert "fxtwitter" not in router.pipeline("twitter", "u", local_only=True)
    assert router.pipeline("facebook", "https://www.facebook.com/reel/1")[0] == "yt-dlp"
    assert router.pipeline("facebook", "https://www.facebook.com/user/posts/pfbid1")[0] == "facebook"


def test_fetch_merges_sources(monkeypatch):
    def fake(name, platform, url, proxy, cookies):
        if name == "tiktok":
            raise PulseError("blocked")
        base = dict(platform="tiktok", post_id="1", url=url)
        if name == "tiktok-ydl":
            return PostMetrics(**base, likes=1, saves=9)
        return PostMetrics(**base, likes=2, comments=3, shares=4, views=5)

    monkeypatch.setattr(router, "_run", fake)
    m = router.fetch("https://www.tiktok.com/@a/video/1?x=1")
    assert (m.likes, m.saves, m.comments, m.views) == (1, 9, 3, 5)


def test_instagram_prefers_plays_over_legacy_views():
    page = r'{"video_view_count":17387,"video_play_count":37900,"like_count":794}'
    m = instagram.parse(page, "https://www.instagram.com/reel/ABC/")
    assert m.views == 37900 and m.likes == 794


def test_debug_scan_counts(capsys):
    from pulse import debug
    debug.enabled = True
    try:
        debug.scan_counts("t", '{"play_count":5,"reshare_count":7,"name":"x"}')
    finally:
        debug.enabled = False
    err = capsys.readouterr().err
    assert "play_count=5" in err and "reshare_count=7" in err


def test_instagram_graphql_reply_shape():
    data = {"graphql": {"shortcode_media": {
        "shortcode": "ABC", "owner": {"username": "matt"}, "video_play_count": 37900, "video_view_count": 17400,
        "edge_media_preview_like": {"count": 797}, "edge_media_to_parent_comment": {"count": 1627}}}}
    m = instagram.parse_api(data, "u")
    assert (m.views, m.likes, m.comments, m.author) == (37900, 797, 1627, "matt")


def test_cookie_loader_httponly_and_domain(tmp_path):
    from pulse import http
    f = tmp_path / "cookies.txt"
    f.write_text(
        "# Netscape HTTP Cookie File\n"
        ".instagram.com\tTRUE\t/\tTRUE\t0\tcsrftoken\tCSRF1\n"
        "#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tSESS1\n"
        ".facebook.com\tTRUE\t/\tTRUE\t0\tc_user\tOTHER\n"
        "# a comment\n\n"
    )
    jar = http.load_cookies(str(f), "https://www.instagram.com/reel/x/")
    assert jar == {"csrftoken": "CSRF1", "sessionid": "SESS1"}
    assert "c_user" in http.load_cookies(str(f))  # no url filter: everything


def test_tiktok_reposts_from_statsv2():
    page = ('<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
            '{"a":{"itemStruct":{"id":"1","author":"123","stats":{"diggCount":1},'
            '"statsV2":{"diggCount":"1","repostCount":"5","collectCount":"9"}}}}</script>')
    m = tiktok.parse(page, "https://www.tiktok.com/@u/video/1")
    assert (m.reposts, m.saves, m.author) == (5, 9, "u")


def test_facebook_author_from_url_and_expected_fields():
    page = '{"reaction_count":{"count":3159},"share_count":{"count":391},"total_comment_count":9}'
    m = facebook.parse(page, "https://www.facebook.com/ExamplePage/posts/pfbid0X")
    assert (m.author, m.likes, m.comments, m.shares, m.views) == ("ExamplePage", 3159, 9, 391, None)
    assert "views" not in router.expected("facebook", "https://www.facebook.com/u/posts/pfbid0X")
    assert "views" in router.expected("facebook", "https://www.facebook.com/reel/1")
    assert "views" not in router.expected("instagram", "https://www.instagram.com/p/A/")
    assert "views" in router.expected("instagram", "https://www.instagram.com/reel/A/")


def test_facebook_tracking_query_stripped():
    u = "https://www.facebook.com/reel/1?rdid=X&share_url=Y"
    assert router.normalize(u, "facebook") == "https://www.facebook.com/reel/1"
    keep = "https://www.facebook.com/permalink.php?story_fbid=1&id=2"
    assert router.normalize(keep, "facebook") == keep


def test_debug_scan_nested_and_string(capsys):
    from pulse import debug
    debug.enabled = True
    try:
        debug.scan_counts("t", '{"reaction_count":{"count":66712},"i18n_share_count":"5.3K","oz_x_count":1}')
    finally:
        debug.enabled = False
    err = capsys.readouterr().err
    assert "reaction_count.count=66712" in err and "i18n_share_count=5.3K" in err and "oz_x" not in err


def test_facebook_reel_fields_seen_in_real_page():
    # field names taken from a real --debug run of a public reel
    page = ('{"likers":{"count":120934},"x":{"likers":{"count":3269}},'
            '"share_count_reduced":"9.4K","total_comment_count":153,"loop_count":5}')
    m = facebook.parse(page, "https://www.facebook.com/reel/1234567890123456")
    assert (m.likes, m.shares, m.comments) == (120934, 9400, 153)


def test_parse_fields_and_select():
    from pulse.models import parse_fields, select
    assert parse_fields("likes, Views") == ("likes", "views")
    assert parse_fields("bookmarks,retweets") == ("saves", "reposts")
    assert parse_fields(None) is None and parse_fields("all") is None and parse_fields(" ") is None
    with pytest.raises(ValueError):
        parse_fields("likes,nope")
    m = PostMetrics(platform="x", post_id="1", url="u", author="a", likes=1, views=2)
    assert select(m, ("likes",)) == {"platform": "x", "post_id": "1", "url": "u", "likes": 1}
    assert list(select(m))[:4] == ["platform", "post_id", "url", "author"]


def test_fetch_stops_when_wanted_fields_are_filled(monkeypatch):
    calls = []

    def fake(name, platform, url, proxy, cookies):
        calls.append(name)
        return PostMetrics(platform="tiktok", post_id="1", url=url, likes=3)

    monkeypatch.setattr(router, "_run", fake)
    m = router.fetch("https://www.tiktok.com/@a/video/1", fields=("likes",))
    assert calls == ["tiktok"] and m.likes == 3


def test_ig_api_only_used_for_fields_that_need_it(monkeypatch):
    calls = []

    def fake(name, platform, url, proxy, cookies):
        calls.append(name)
        return PostMetrics(platform="instagram", post_id="1", url=url, likes=1, comments=2, shares=3, views=4)

    monkeypatch.setattr(router, "_run", fake)
    u = "https://www.instagram.com/reel/ABC/"
    router.fetch(u, cookies="c.txt", fields=("likes", "comments"))
    assert "ig-api" not in calls
    calls.clear()
    router.fetch(u, cookies="c.txt", fields=("shares",))
    assert calls[0] == "ig-api"


def test_youtube_comment_lookup_skipped_when_not_requested(monkeypatch):
    monkeypatch.setattr(router, "_run", lambda *a: PostMetrics(platform="youtube", post_id="abcdefghijk", url="u", likes=1))

    def boom(*a, **k):
        raise AssertionError("refine must not run")

    monkeypatch.setattr(router.youtube, "refine", boom)
    assert router.fetch("https://youtu.be/abcdefghijk", fields=("likes",)).likes == 1


def test_non_http_and_unknown_hosts_rejected_without_requests(monkeypatch):
    from pulse.models import UnsupportedURL

    def no_network(*a, **k):
        raise AssertionError("no request expected")

    monkeypatch.setattr(router.http, "get", no_network)
    for bad in ("ftp://www.tiktok.com/x", "https://example.com/x", "https://tiktok.com@evil.com/x",
                "http://169.254.169.254/latest/meta-data/"):
        with pytest.raises(UnsupportedURL):
            router.fetch(bad)


def test_redirect_to_internal_host_is_blocked(monkeypatch):
    from pulse import http
    calls = []

    class Resp:
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data/"}
        url = "u"
        text = ""

    class FakeSession:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **kw):
            calls.append(url)
            return Resp()

    monkeypatch.setattr(http.cffi, "Session", FakeSession)
    with pytest.raises(PulseError, match="Blocked"):
        http.get("https://t.co/abc")
    assert calls == ["https://t.co/abc"]


def test_cli_fields_option(monkeypatch):
    from typer.testing import CliRunner

    from pulse.cli import app

    def fake(url, **kw):
        return PostMetrics(platform="tiktok", post_id="1", url=url, author="a", likes=5, comments=6, views=8)

    monkeypatch.setattr(router, "fetch", fake)
    r = CliRunner().invoke(app, ["https://www.tiktok.com/@a/video/1", "--json", "--fields", "likes"])
    assert r.exit_code == 0
    assert json.loads(r.stdout) == {"platform": "tiktok", "post_id": "1", "url": "https://www.tiktok.com/@a/video/1", "likes": 5}
    assert CliRunner().invoke(app, ["https://x", "--fields", "nope"]).exit_code != 0



def test_instagram_legacy_views_warning(monkeypatch):
    def fake(name, platform, url, proxy, cookies):
        return PostMetrics(platform="instagram", post_id="1", url=url, likes=1, comments=2, views=17000)

    monkeypatch.setattr(router, "_run", fake)
    warnings = []
    router.fetch("https://www.instagram.com/reel/ABC/", warn=warnings.append)
    assert len(warnings) == 1 and "legacy" in warnings[0]
    warnings.clear()
    router.fetch("https://www.instagram.com/reel/ABC/", cookies="c.txt", warn=warnings.append)
    assert warnings == []  # ig-api succeeded, the number is the app's


EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]")
TEXT_SUFFIXES = {".py", ".md", ".toml", ".txt", ".html", ".json", ".yml", ".yaml"}
TEXT_NAMES = {"Dockerfile", ".gitignore", ".dockerignore", ".env.example"}
SKIP_DIRS = {"venv", ".venv", "__pycache__", ".git", ".pytest_cache", ".ruff_cache", "pulse-debug"}


def test_no_emoji_anywhere_and_code_is_ascii():
    root = Path(__file__).resolve().parent.parent
    for p in root.rglob("*"):
        rel = p.relative_to(root).parts
        if not p.is_file() or SKIP_DIRS & set(rel):
            continue
        if p.suffix not in TEXT_SUFFIXES and p.name not in TEXT_NAMES:
            continue
        text = p.read_text(encoding="utf-8")
        assert not EMOJI.search(text), f"emoji in {p}"
        assert all(ord(c) < 128 for c in text), f"non-ASCII character in {p}"


def test_views_source_set_for_instagram(monkeypatch):
    def fake(name, platform, url, proxy, cookies):
        return PostMetrics(platform="instagram", post_id="1", url=url, likes=1, comments=2, views=17000)

    monkeypatch.setattr(router, "_run", fake)
    u = "https://www.instagram.com/reel/ABC/"
    assert router.fetch(u).views_source == "public"
    assert router.fetch(u, cookies="c.txt").views_source == "app"  # ig-api supplied the views
    assert router.fetch(u, fields=("likes",)).views_source is None  # views not requested, nothing to label


def test_views_source_not_set_elsewhere(monkeypatch):
    monkeypatch.setattr(router, "_run", lambda *a: PostMetrics(platform="tiktok", post_id="1", url="u", views=5))
    assert router.fetch("https://www.tiktok.com/@a/video/1", fields=("views",)).views_source is None


def test_views_source_follows_views_in_selection():
    from pulse.models import select
    m = PostMetrics(platform="instagram", post_id="1", url="u", likes=1, views=2, views_source="public")
    assert select(m, ("views",))["views_source"] == "public"
    assert "views_source" not in select(m, ("likes",))
    assert select(m)["views_source"] == "public"


def test_table_and_csv_show_views_source(tmp_path):
    import io

    from rich.console import Console

    from pulse.cli import render_table, write_report
    pub = PostMetrics(platform="instagram", post_id="1", url="u", views=17387, views_source="public")
    app = PostMetrics(platform="instagram", post_id="2", url="u", views=38354, views_source="app")
    buf = io.StringIO()
    Console(file=buf, width=200).print(render_table([pub, app]))
    text = buf.getvalue()
    assert "17,387 (public)" in text and "38,354" in text and "38,354 (" not in text

    out = tmp_path / "r.csv"
    write_report([pub, app], out)
    lines = out.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    assert header[header.index("views") + 1] == "views_source"
    assert lines[1].endswith("17387,public") and lines[2].endswith("38354,app")
    out2 = tmp_path / "r2.csv"
    write_report([pub], out2, ("likes",))
    assert "views_source" not in out2.read_text(encoding="utf-8")
