import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from pulse import api, router
from pulse.models import PostMetrics, PulseError, UnsupportedURL

client = TestClient(api.app)
H = {"X-API-Key": "k1"}
URL = "https://www.tiktok.com/@a/video/1"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("PULSE_API_KEYS", "k1")
    for var in ("PULSE_ALLOW_ANONYMOUS", "PULSE_RATE_LIMIT", "PULSE_CACHE_TTL", "PULSE_LOCAL_ONLY",
                "PULSE_PROXY", "PULSE_COOKIES_FILE"):
        monkeypatch.delenv(var, raising=False)
    api._hits.clear()
    api._cache.clear()


def fake_fetch(url, **kw):
    return PostMetrics(platform="tiktok", post_id="1", url=url, author="a", likes=5, comments=6, saves=7, views=8)


def test_key_required_and_server_misconfig(monkeypatch):
    assert client.get("/v1/metrics", params={"url": URL}).status_code == 401
    assert client.get("/v1/metrics", params={"url": URL}, headers={"X-API-Key": "bad"}).status_code == 401
    monkeypatch.delenv("PULSE_API_KEYS")
    assert client.get("/v1/metrics", params={"url": URL}).status_code == 503
    monkeypatch.setenv("PULSE_ALLOW_ANONYMOUS", "1")
    monkeypatch.setattr(router, "fetch", fake_fetch)
    assert client.get("/v1/metrics", params={"url": URL}).status_code == 200


def test_field_selection_and_alias(monkeypatch):
    seen = {}

    def spy(url, **kw):
        seen.update(kw)
        return fake_fetch(url)

    monkeypatch.setattr(router, "fetch", spy)
    j = client.get("/v1/metrics", params={"url": URL, "fields": "likes,bookmarks"}, headers=H).json()
    assert j["likes"] == 5 and j["saves"] == 7
    assert "comments" not in j and "views" not in j and "author" not in j
    assert j["platform"] == "tiktok" and j["cached"] is False and "fetched_at" in j
    assert seen["fields"] == ("likes", "saves")
    full = client.get("/v1/metrics", params={"url": URL}, headers=H).json()
    assert full["views"] == 8 and full["author"] == "a"


def test_bad_field_and_error_mapping(monkeypatch):
    assert client.get("/v1/metrics", params={"url": URL, "fields": "nope"}, headers=H).status_code == 422

    def unsupported(url, **kw):
        raise UnsupportedURL("Unsupported or unrecognized URL")

    def broken(url, **kw):
        raise PulseError("blocked")

    monkeypatch.setattr(router, "fetch", unsupported)
    assert client.get("/v1/metrics", params={"url": "https://example.com/x"}, headers=H).status_code == 400
    monkeypatch.setattr(router, "fetch", broken)
    assert client.get("/v1/metrics", params={"url": URL}, headers=H).status_code == 502


def test_cache_and_rate_limit(monkeypatch):
    calls = []

    def counting(url, **kw):
        calls.append(url)
        return fake_fetch(url)

    monkeypatch.setattr(router, "fetch", counting)
    client.get("/v1/metrics", params={"url": URL}, headers=H)
    second = client.get("/v1/metrics", params={"url": URL}, headers=H).json()
    assert len(calls) == 1 and second["cached"] is True

    monkeypatch.setenv("PULSE_RATE_LIMIT", "3")
    api._hits.clear()
    codes = [client.get("/v1/metrics", params={"url": URL}, headers=H).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_batch_partial_failure(monkeypatch):
    def mixed(url, **kw):
        if "bad" in url:
            raise UnsupportedURL("Unsupported or unrecognized URL")
        return fake_fetch(url)

    monkeypatch.setattr(router, "fetch", mixed)
    r = client.post("/v1/metrics/batch", headers=H,
                    json={"urls": [URL, "https://example.com/bad"], "fields": ["likes"]}).json()
    assert r["results"][0]["ok"] is True and r["results"][0]["data"]["likes"] == 5
    assert r["results"][1] == {"ok": False, "url": "https://example.com/bad", "status": 400,
                               "error": "Unsupported or unrecognized URL"}
    assert client.post("/v1/metrics/batch", headers=H, json={"urls": []}).status_code == 422


def test_server_side_settings_not_request_controlled(monkeypatch):
    seen = {}

    def spy(url, **kw):
        seen.update(kw)
        return fake_fetch(url)

    monkeypatch.setattr(router, "fetch", spy)
    monkeypatch.setenv("PULSE_COOKIES_FILE", "/srv/cookies.txt")
    monkeypatch.setenv("PULSE_LOCAL_ONLY", "1")
    client.get("/v1/metrics", params={"url": URL, "local_only": "false", "cookies": "/etc/passwd"}, headers=H)
    assert seen["cookies"] == "/srv/cookies.txt" and seen["local_only"] is True


def test_meta_endpoints():
    assert client.get("/health").json()["status"] == "ok"
    assert "likes" in client.get("/v1/fields").json()["fields"]


def test_warnings_are_passed_to_the_response(monkeypatch):
    def warns(url, **kw):
        kw["warn"]("careful")
        return fake_fetch(url)

    monkeypatch.setattr(router, "fetch", warns)
    j = client.get("/v1/metrics", params={"url": URL}, headers=H).json()
    assert j["warnings"] == ["careful"]


def test_views_source_in_api_response(monkeypatch):
    def ig(url, **kw):
        return PostMetrics(platform="instagram", post_id="1", url=url, likes=3, views=17387, views_source="public")

    monkeypatch.setattr(router, "fetch", ig)
    both = client.get("/v1/metrics", params={"url": URL, "fields": "views"}, headers=H).json()
    assert both["views"] == 17387 and both["views_source"] == "public"
    api._cache.clear()
    only_likes = client.get("/v1/metrics", params={"url": URL, "fields": "likes"}, headers=H).json()
    assert "views_source" not in only_likes
