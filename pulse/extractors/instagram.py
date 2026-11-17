"""Native Instagram parsers (photo posts, embed pages, and the logged-in JSON API)."""
from __future__ import annotations

import json
import re
from typing import Optional

from .. import debug, http
from ..models import PostMetrics, PulseError, merge, parse_count, to_int
from ..util import meta_content

_CODE_RE = re.compile(r"/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
_LD_RE = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
_NUM = r"(\d[\d.,]*\s?[KMBkmb]?)"
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
API_HEADERS = {
    "X-IG-App-ID": "936619743392459",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.instagram.com/",
    "Accept": "*/*",
}


def _key(name: str):
    # tolerate JSON embedded inside an escaped string (\"key\":123)
    return re.compile(r'\\*"%s\\*"\s*:\s*(\d+)' % name)


_RAW = {
    "likes": [_key("like_count"),
              re.compile(r'\\*"edge_media_preview_like\\*"\s*:\s*\{\s*\\*"count\\*"\s*:\s*(\d+)')],
    "comments": [_key("comment_count"),
                 re.compile(r'\\*"edge_media_to_(?:parent_)?comment\\*"\s*:\s*\{\s*\\*"count\\*"\s*:\s*(\d+)')],
    "views": [_key("play_count"), _key("video_play_count"), _key("ig_play_count"),
              _key("video_view_count"), _key("view_count")],
}
_USER_RE = re.compile(r'\\*"username\\*"\s*:\s*\\*"([\w.]+)\\*"')


def shortcode_to_pk(code: str) -> int:
    pk = 0
    for ch in code:
        pk = pk * 64 + _ALPHABET.index(ch)
    return pk


def _from_og(page: str) -> dict:
    desc = meta_content(page, "og:description")
    if not desc:
        return {}
    head = desc.split(" - ", 1)[0]  # "1,234 likes, 56 comments"
    out: dict = {}
    m = re.search(_NUM + r"\s+likes?", head, re.I)
    if m:
        out["likes"] = parse_count(m.group(1))
    m = re.search(_NUM + r"\s+comments?", head, re.I)
    if m:
        out["comments"] = parse_count(m.group(1))
    m = re.search(r" - ([\w.]+)(?: \(@[\w.]+\))? on ", desc)
    if m:
        out["author"] = m.group(1)
    return out


def _from_ld(page: str) -> dict:
    out: dict = {}
    for raw in _LD_RE.findall(page):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict):
                continue
            for stat in node.get("interactionStatistic") or []:
                t = stat.get("interactionType")
                t = t.get("@type", "") if isinstance(t, dict) else str(t)
                n = to_int(stat.get("userInteractionCount"))
                if "Like" in t:
                    out.setdefault("likes", n)
                elif "Comment" in t:
                    out.setdefault("comments", n)
                elif "Watch" in t or "View" in t:
                    out.setdefault("views", n)
    return out


def _from_raw_json(page: str, with_author: bool = False) -> dict:
    out: dict = {}
    for key, rxs in _RAW.items():
        for rx in rxs:
            m = rx.search(page)
            if m:
                out[key] = int(m.group(1))
                break
    if with_author:
        m = _USER_RE.search(page)
        if m:
            out["author"] = m.group(1)
    return out


def _build(merged: dict, url: str) -> PostMetrics:
    if not any(merged.get(k) is not None for k in ("likes", "comments", "views")):
        raise PulseError("No engagement data on the page (login wall or hidden counts)")
    code = _CODE_RE.search(url)
    return PostMetrics(
        platform="instagram",
        post_id=code.group(1) if code else "",
        url=url,
        author=merged.get("author"),
        likes=merged.get("likes"),
        comments=merged.get("comments"),
        views=merged.get("views"),
    )


def parse(page: str, url: str, with_author: bool = False) -> PostMetrics:
    merged: dict = {}
    for source in (_from_ld, _from_og, lambda p: _from_raw_json(p, with_author)):  # earlier wins
        for k, v in source(page).items():
            if v is not None:
                merged.setdefault(k, v)
    return _build(merged, url)


def _parse_graphql(media: dict, url: str) -> PostMetrics:
    comments = media.get("edge_media_to_parent_comment") or media.get("edge_media_to_comment") or {}
    plays = media.get("video_play_count")
    return PostMetrics(
        platform="instagram",
        post_id=str(media.get("shortcode") or ""),
        url=url,
        author=(media.get("owner") or {}).get("username"),
        likes=to_int((media.get("edge_media_preview_like") or {}).get("count")),
        comments=to_int(comments.get("count")),
        views=to_int(plays if plays is not None else media.get("video_view_count")),
    )


def parse_api(data: dict, url: str) -> PostMetrics:
    """Response of /api/v1/media/<pk>/info/ (needs a logged-in session)."""
    gql = ((data or {}).get("graphql") or {}).get("shortcode_media")
    if gql:
        return _parse_graphql(gql, url)
    items = (data or {}).get("items") or []
    if not items:
        raise PulseError("Instagram API returned no item")
    it = items[0]
    debug.log("instagram api count-like fields: " + str(
        {k: v for k, v in it.items() if isinstance(v, int) and not isinstance(v, bool)}))
    views = next((to_int(it[k]) for k in ("play_count", "ig_play_count", "view_count")
                  if it.get(k) is not None), None)
    return PostMetrics(
        platform="instagram",
        post_id=str(it.get("code") or ""),
        url=url,
        author=(it.get("user") or {}).get("username"),
        likes=to_int(it.get("like_count")),
        comments=to_int(it.get("comment_count")),
        reposts=to_int(it.get("media_repost_count")),
        shares=to_int(it.get("reshare_count")),
        views=views,
    )


def extract(url: str, *, proxy: Optional[str] = None, cookies: Optional[str] = None) -> PostMetrics:
    code = _CODE_RE.search(url)
    if not code:
        raise PulseError("Could not find an Instagram shortcode in the URL")
    headers = {"Accept-Language": "en-US,en;q=0.9"}
    result: Optional[PostMetrics] = None
    err: Optional[PulseError] = None

    try:
        resp = http.get(url, proxy=proxy, cookies_file=cookies, headers=headers)
        if "/accounts/login" in str(resp.url):
            raise PulseError("Instagram redirected to login; use --cookies with your browser session")
        debug.dump("instagram-page.html", resp.text)
        debug.scan_counts("instagram page", resp.text)
        result = parse(resp.text, url)
    except PulseError as e:
        err = e

    if result is None or result.views is None or result.likes is None:
        try:  # the embed page exposes view counts and exact like/comment counts
            eresp = http.get(f"https://www.instagram.com/p/{code.group(1)}/embed/captioned/",
                             proxy=proxy, cookies_file=cookies, headers=headers)
            debug.dump("instagram-embed.html", eresp.text)
            debug.scan_counts("instagram embed", eresp.text)
            emb = parse(eresp.text, url, with_author=True)
            result = emb if result is None else merge(result, emb)
        except PulseError as e:
            err = err or e
    if result is None:
        raise err or PulseError("Instagram: no data")
    return result


def extract_api(url: str, *, proxy: Optional[str] = None, cookies: Optional[str] = None) -> PostMetrics:
    if not cookies:
        raise PulseError("Instagram JSON API needs --cookies (logged-in session)")
    code = _CODE_RE.search(url)
    if not code:
        raise PulseError("Could not find an Instagram shortcode in the URL")
    pk = shortcode_to_pk(code.group(1))
    headers = dict(API_HEADERS)
    headers["X-ASBD-ID"] = "129477"
    csrf = http.load_cookies(cookies, "https://www.instagram.com/").get("csrftoken")
    if csrf:
        headers["X-CSRFToken"] = csrf

    attempts = [("api-v1", f"https://www.instagram.com/api/v1/media/{pk}/info/")]
    errors = []
    for label, endpoint in attempts:
        try:
            resp = http.get(endpoint, proxy=proxy, cookies_file=cookies, headers=headers)
        except PulseError as e:
            errors.append(f"{label}: {e}")
            continue
        debug.dump(f"instagram-{label}.txt", resp.text)
        if "/accounts/login" in str(resp.url):
            errors.append(f"{label}: Instagram redirected to login, so it did not accept the cookies "
                          "(sessionid missing, expired, or exported while logged out)")
            continue
        head = resp.text[:120].replace("\n", " ")
        try:
            data = resp.json()
        except Exception:
            errors.append(f"{label}: non-JSON (HTTP {resp.status_code}, {resp.url}) starts: {head}")
            continue
        try:
            return parse_api(data, url)
        except PulseError as e:
            errors.append(f"{label}: {e}; reply: {head}")
    raise PulseError(" | ".join(errors))
