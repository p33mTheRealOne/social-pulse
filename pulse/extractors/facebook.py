"""Native Facebook parser for public posts and reels."""
from __future__ import annotations

import re
from typing import Optional

from .. import debug, http
from ..models import PostMetrics, PulseError, parse_count
from ..util import meta_content

_NUM = r"(\d[\d.,]*\s?[KMBkmb]?)"
_ABBR = r'"([\d.,]+\s?[KMBkmb]?)"'
_JSON = {
    "likes": [
        r'"reaction_count"\s*:\s*\{\s*"count"\s*:\s*(\d+)',
        r'"i18n_reaction_count"\s*:\s*' + _ABBR,
        r'"likers"\s*:\s*\{\s*"count"\s*:\s*(\d+)',  # reels: total reactions
    ],
    "comments": [
        r'"total_comment_count"\s*:\s*(\d+)',
        r'"comment_count"\s*:\s*\{\s*"total_count"\s*:\s*(\d+)',
        r'"comments"\s*:\s*\{\s*"total_count"\s*:\s*(\d+)',
    ],
    "shares": [
        r'"share_count"\s*:\s*\{\s*"count"\s*:\s*(\d+)',
        r'"i18n_share_count"\s*:\s*' + _ABBR,
        r'"share_count_reduced"\s*:\s*' + _ABBR,  # reels: abbreviated, e.g. "9.4K"
    ],
    "views": [r'"play_count"\s*:\s*(\d+)', r'"video_view_count"\s*:\s*(\d+)'],
}
_OG_WORDS = {"view": "views", "reaction": "likes", "like": "likes", "comment": "comments", "share": "shares"}
_AUTHOR_RE = re.compile(r"facebook\.com/([^/?#]+)/(?:posts|videos|photos)/")
_ID_RE = re.compile(r"(?:/reel/|/videos?/|story_fbid=|/posts/|/permalink/)([\w.-]+)")


def parse(page: str, url: str) -> PostMetrics:
    found: dict = {}
    for key, patterns in _JSON.items():  # exact numbers from embedded JSON win
        for p in patterns:
            m = re.search(p, page)
            if m:
                found[key] = parse_count(m.group(1))
                break
    desc = meta_content(page, "og:description")
    if desc:  # "206,895 views, 66K reactions | caption" (rounded numbers)
        head = desc.split("|", 1)[0]
        for m in re.finditer(_NUM + r"\s+(views?|reactions?|likes?|comments?|shares?)", head, re.I):
            key = _OG_WORDS[m.group(2).lower().rstrip("s")]
            found.setdefault(key, parse_count(m.group(1)))
    if not any(found.get(k) is not None for k in _JSON):
        raise PulseError("No engagement data on the Facebook page (login wall or layout changed)")
    pid = _ID_RE.search(url)
    who = _AUTHOR_RE.search(url)
    return PostMetrics(
        platform="facebook",
        post_id=pid.group(1) if pid else "",
        url=url,
        author=who.group(1) if who else None,
        likes=found.get("likes"),
        comments=found.get("comments"),
        shares=found.get("shares"),
        views=found.get("views"),
    )


def extract(url: str, *, proxy: Optional[str] = None, cookies: Optional[str] = None) -> PostMetrics:
    resp = http.get(url, proxy=proxy, cookies_file=cookies, headers={"Accept-Language": "en-US,en;q=0.9"})
    pid = _ID_RE.search(str(resp.url))
    debug.dump(f"facebook-{pid.group(1)[:24] if pid else 'page'}.html", resp.text)
    debug.scan_counts("facebook page", resp.text)
    return parse(resp.text, str(resp.url))
