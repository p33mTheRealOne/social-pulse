from __future__ import annotations

import json
import re
from typing import Optional

from .. import debug, http
from ..models import PostMetrics, PulseError, to_int
from ..util import find_key

_SCRIPT_RE = re.compile(
    r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
    re.DOTALL,
)
_HANDLE_RE = re.compile(r"/@([^/?#]+)")
TARGETS = ("chrome", "safari", "edge")  # tried in order until TikTok serves real data


def parse(html: str, url: str) -> PostMetrics:
    m = _SCRIPT_RE.search(html)
    if not m:
        raise PulseError("TikTok rehydration JSON not found (blocked/captcha or layout changed)")
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise PulseError(f"TikTok JSON invalid: {e}") from e
    item = find_key(data, "itemStruct")
    if not isinstance(item, dict) or not (item.get("stats") or item.get("statsV2")):
        raise PulseError("TikTok video data missing (video private/removed or blocked)")

    stats = item.get("stats") or {}
    stats_v2 = item.get("statsV2") or {}  # exact counts as strings; stats may be rounded
    debug.log(f"tiktok stats={stats} statsV2={stats_v2}")

    def stat(key: str) -> Optional[int]:
        v = to_int(stats_v2.get(key))
        return v if v is not None else to_int(stats.get(key))

    author = item.get("author")
    if isinstance(author, dict):
        author = author.get("uniqueId")
    if not author or str(author).isdigit():  # numeric user id is useless to humans
        h = _HANDLE_RE.search(url)
        author = h.group(1) if h else None

    return PostMetrics(
        platform="tiktok",
        post_id=str(item.get("id", "")),
        url=url,
        author=str(author) if author else None,
        likes=stat("diggCount"),
        comments=stat("commentCount"),
        reposts=stat("repostCount"),
        shares=stat("shareCount"),
        saves=stat("collectCount"),
        views=stat("playCount"),
    )


def extract(url: str, *, proxy: Optional[str] = None, cookies: Optional[str] = None) -> PostMetrics:
    last: Optional[PulseError] = None
    for target in TARGETS:
        try:
            resp = http.get(
                url, proxy=proxy, cookies_file=cookies, impersonate=target,
                headers={"Accept-Language": "en-US,en;q=0.9"},
                warmup="https://www.tiktok.com/",
            )
        except PulseError as e:
            last = e
            continue
        try:
            return parse(resp.text, str(resp.url))
        except PulseError as e:
            debug.dump(f"tiktok-{target}.html", resp.text)
            last = e
    raise last or PulseError("TikTok request failed")


def extract_via_ytdlp(url: str, *, proxy: Optional[str] = None, cookies: Optional[str] = None) -> PostMetrics:
    """Fetch the page through yt-dlp's own HTTP session, then parse it with our parser."""
    from . import meta

    html = meta.fetch_text(url, proxy=proxy, cookies=cookies)
    try:
        return parse(html, url)
    except PulseError:
        debug.dump("tiktok-ytdlp-session.html", html)
        raise
