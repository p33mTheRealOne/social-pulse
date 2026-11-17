from __future__ import annotations

import math
import re
from typing import Optional

from .. import http
from ..models import PostMetrics, PulseError, to_int

_ID_RE = re.compile(r"/status(?:es)?/(\d+)")
_USER_RE = re.compile(r"(?:x|twitter)\.com/([^/?#]+)/status")
_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"
ENDPOINT = "https://cdn.syndication.twimg.com/tweet-result"
FX_ENDPOINT = "https://api.fxtwitter.com"


def tweet_id(url: str) -> str:
    m = _ID_RE.search(url)
    if not m:
        raise PulseError("Could not find a tweet ID in the URL")
    return m.group(1)


def make_token(tid: str) -> str:
    """Mimics the embed widget token: (id/1e15*pi) in base 36, zeros/dots removed."""
    x = int(tid) / 1e15 * math.pi
    whole, frac = int(x), x - int(x)
    digits = ""
    while whole:
        whole, r = divmod(whole, 36)
        digits = _B36[r] + digits
    digits = digits or "0"
    for _ in range(12):
        frac *= 36
        d = int(frac)
        digits += _B36[d]
        frac -= d
    return digits.replace("0", "") or "0"


def parse(data: dict, url: str) -> PostMetrics:
    """Public syndication payload: reliably has likes and replies only."""
    if not data or "id_str" not in data:
        raise PulseError("Tweet not available via syndication (deleted, private, or age-restricted)")
    views = data.get("views")
    views = views.get("count") if isinstance(views, dict) else views
    return PostMetrics(
        platform="twitter",
        post_id=str(data["id_str"]),
        url=url,
        author=(data.get("user") or {}).get("screen_name"),
        likes=to_int(data.get("favorite_count")),
        comments=to_int(data.get("conversation_count")),
        reposts=to_int(data.get("retweet_count")),
        saves=to_int(data.get("bookmark_count")),
        views=to_int(views),
    )


def parse_fx(data: dict, url: str) -> PostMetrics:
    tw = (data or {}).get("tweet")
    if not isinstance(tw, dict):
        raise PulseError("fxtwitter returned no tweet")
    return PostMetrics(
        platform="twitter",
        post_id=str(tw.get("id", "")),
        url=url,
        author=(tw.get("author") or {}).get("screen_name"),
        likes=to_int(tw.get("likes")),
        comments=to_int(tw.get("replies")),
        reposts=to_int(tw.get("retweets")),
        saves=to_int(tw.get("bookmarks")),
        views=to_int(tw.get("views")),
    )


def extract(url: str, *, proxy: Optional[str] = None, cookies: Optional[str] = None) -> PostMetrics:
    tid = tweet_id(url)
    resp = http.get(
        f"{ENDPOINT}?id={tid}&lang=en&token={make_token(tid)}",
        proxy=proxy,
        cookies_file=cookies,
    )
    try:
        data = resp.json()
    except Exception as e:
        raise PulseError("Syndication endpoint returned non-JSON") from e
    return parse(data, url)


def extract_fx(url: str, *, proxy: Optional[str] = None, cookies: Optional[str] = None) -> PostMetrics:
    """Third-party public API (api.fxtwitter.com): adds reposts, bookmarks and views."""
    tid = tweet_id(url)
    user = _USER_RE.search(url)
    resp = http.get(f"{FX_ENDPOINT}/{user.group(1) if user else 'i'}/status/{tid}", proxy=proxy)
    try:
        data = resp.json()
    except Exception as e:
        raise PulseError("fxtwitter returned non-JSON") from e
    return parse_fx(data, url)
