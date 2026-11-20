from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel


class PulseError(Exception):
    """Any expected failure (network, parsing, unsupported URL)."""


class UnsupportedURL(PulseError):
    """The URL is not a recognized post URL for any supported platform."""


class PostMetrics(BaseModel):
    platform: str
    post_id: str
    url: str
    author: Optional[str] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    reposts: Optional[int] = None
    shares: Optional[int] = None
    saves: Optional[int] = None
    views: Optional[int] = None
    # Instagram only: 'app' = the play count the app shows (needs cookies), 'public' = the older public counter
    views_source: Optional[Literal["app", "public"]] = None


METRIC_FIELDS = ("likes", "comments", "reposts", "shares", "saves", "views")


def merge(base: PostMetrics, other: PostMetrics) -> PostMetrics:
    """Keep base values; fill only the fields base is missing."""
    data = base.model_dump()
    for key in METRIC_FIELDS + ("author",):
        if data.get(key) is None and getattr(other, key) is not None:
            data[key] = getattr(other, key)
    if not data.get("post_id") and other.post_id:
        data["post_id"] = other.post_id
    return PostMetrics(**data)


def to_int(value: Any) -> Optional[int]:
    """Coerce API numbers (int, '123', 123.0) to int; anything else -> None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


_SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9}


def parse_count(text: Any) -> Optional[int]:
    """'1,234' -> 1234, '12.5K' -> 12500, '3M' -> 3000000."""
    if text is None:
        return None
    s = str(text).strip().replace(",", "").replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kmb])?", s, re.I)
    if not m:
        return None
    mult = _SUFFIX[m.group(2).lower()] if m.group(2) else 1
    return int(round(float(m.group(1)) * mult))


ALL_FIELDS = ("author",) + METRIC_FIELDS
IDENTITY_FIELDS = ("platform", "post_id", "url")  # always returned
_ALIASES = {
    "bookmarks": "saves", "retweets": "reposts", "plays": "views", "replies": "comments",
    "reactions": "likes", "user": "author", "username": "author",
}


def parse_fields(value) -> "Optional[tuple]":
    """'likes,views' (or a list) -> ('likes', 'views'); None / '' / 'all' -> None (everything)."""
    if value is None:
        return None
    items = value.split(",") if isinstance(value, str) else list(value)
    out: list = []
    bad: list = []
    for raw in items:
        name = str(raw).strip().lower()
        if not name:
            continue
        if name == "all":
            return None
        name = _ALIASES.get(name, name)
        if name not in ALL_FIELDS:
            bad.append(name)
        elif name not in out:
            out.append(name)
    if bad:
        raise ValueError(f"Unknown field(s): {', '.join(bad)}. Allowed: {', '.join(ALL_FIELDS)}")
    return tuple(out) or None


def select(m: PostMetrics, fields=None) -> dict:
    """Identity fields plus only the requested fields (model order)."""
    data = m.model_dump()
    if not fields:
        return data
    wanted = set(fields)
    if "views" in wanted:
        wanted.add("views_source")
    return {k: v for k, v in data.items() if k in IDENTITY_FIELDS or k in wanted}
