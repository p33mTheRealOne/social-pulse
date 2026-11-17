"""YouTube: yt-dlp gives rounded comment counts (48K); this fetches the exact number."""
from __future__ import annotations

import json
import re
from typing import Optional

from .. import debug, http
from ..models import PostMetrics, parse_count
from ..util import find_key, walk


def _initial_data(page: str) -> Optional[dict]:
    i = page.find("ytInitialData")
    j = page.find("{", i) if i >= 0 else -1
    if j < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(page[j:])
    except ValueError:
        return None
    return obj


def comment_token(initial: dict) -> Optional[str]:
    for d in walk(initial):
        if d.get("sectionIdentifier") == "comment-item-section":
            tok = find_key(d, "token")
            if tok:
                return tok
    return None


def parse_comment_count(resp: dict) -> Optional[int]:
    header = find_key(resp, "commentsHeaderRenderer")
    if not isinstance(header, dict):
        return None
    ct = header.get("countText") or {}
    if not isinstance(ct, dict):
        return None
    runs = ct.get("runs")
    text = runs[0].get("text") if runs else ct.get("simpleText")
    return parse_count(text)


def exact_comment_count(video_id: str, *, proxy: Optional[str] = None, cookies: Optional[str] = None) -> Optional[int]:
    page = http.get(
        f"https://www.youtube.com/watch?v={video_id}",
        proxy=proxy, cookies_file=cookies, headers={"Accept-Language": "en-US,en;q=0.9"},
    ).text
    token = comment_token(_initial_data(page) or {})
    if not token:
        return None
    key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', page)
    ver = re.search(r'"INNERTUBE_CONTEXT_CLIENT_VERSION":"([^"]+)"', page)
    url = "https://www.youtube.com/youtubei/v1/next" + (f"?key={key.group(1)}" if key else "")
    payload = {
        "context": {"client": {"clientName": "WEB", "hl": "en",
                               "clientVersion": ver.group(1) if ver else "2.20250101.00.00"}},
        "continuation": token,
    }
    resp = http.post_json(url, payload, proxy=proxy, cookies_file=cookies)
    return parse_comment_count(resp.json())


def refine(m: PostMetrics, *, proxy: Optional[str] = None, cookies: Optional[str] = None) -> PostMetrics:
    """Replace a rounded comment count (>= 1000) with the exact one when available."""
    if (m.comments is not None and m.comments < 1000) or not re.fullmatch(r"[\w-]{5,20}", m.post_id or ""):
        return m
    try:
        exact = exact_comment_count(m.post_id, proxy=proxy, cookies=cookies)
    except Exception as e:
        debug.log(f"youtube exact comment lookup failed: {e}")
        return m
    return m.model_copy(update={"comments": exact}) if exact else m
