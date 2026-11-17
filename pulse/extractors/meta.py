"""yt-dlp wrapper: YouTube, Instagram reels, Facebook, and fallback for everything else."""
from __future__ import annotations

import re
from typing import Optional

from .. import debug
from ..models import PostMetrics, PulseError, to_int


class _Quiet:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def _handle_from_url(url: Optional[str]) -> Optional[str]:
    m = re.search(r"instagram\.com/([^/?#]+)", url or "")
    return m.group(1) if m else None


def pick_author(info: dict, platform: str) -> Optional[str]:
    if platform == "instagram":  # uploader_id is a numeric pk; the handle hides in channel/uploader_url
        cands = [info.get("channel"), _handle_from_url(info.get("uploader_url")),
                 info.get("uploader_id"), info.get("uploader")]
    elif platform == "youtube":
        cands = [info.get("uploader_id"), info.get("uploader"), info.get("channel")]
    else:  # TikTok's uploader_id is numeric; uploader is the handle
        cands = [info.get("uploader"), info.get("channel"), info.get("uploader_id")]
    for c in cands:
        if c and not str(c).isdigit():
            return str(c)
    return None


def to_metrics(info: dict, platform: str, url: str) -> PostMetrics:
    repost = to_int(info.get("repost_count"))
    return PostMetrics(
        platform=platform,
        post_id=str(info.get("id", "")),
        url=url,
        author=pick_author(info, platform),
        likes=to_int(info.get("like_count")),
        comments=to_int(info.get("comment_count")),
        reposts=repost if platform == "twitter" else None,
        shares=None if platform == "twitter" else repost,
        saves=to_int(info.get("save_count")),
        views=to_int(info.get("view_count")),
    )


def _opts(proxy: Optional[str], cookies: Optional[str]) -> dict:
    opts: dict = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "noplaylist": True, "logger": _Quiet(),
    }
    if cookies:
        opts["cookiefile"] = cookies
    if proxy:
        opts["proxy"] = proxy
    return opts


def extract(
    url: str,
    platform: str = "unknown",
    *,
    proxy: Optional[str] = None,
    cookies: Optional[str] = None,
) -> PostMetrics:
    import yt_dlp  # lazy: slow import

    try:
        with yt_dlp.YoutubeDL(_opts(proxy, cookies)) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise PulseError(f"yt-dlp: {e}") from e
    if not info:
        raise PulseError("yt-dlp returned no metadata")
    words = ("count", "view", "like", "repost", "share", "save", "uploader", "channel")
    debug.log("yt-dlp fields: " + str({k: v for k, v in info.items()
                                        if any(w in k for w in words) and not isinstance(v, (dict, list))}))
    return to_metrics(info, platform, url)


def fetch_text(url: str, *, proxy: Optional[str] = None, cookies: Optional[str] = None) -> str:
    """GET a page through yt-dlp's own HTTP stack."""
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(_opts(proxy, cookies)) as ydl:
            return ydl.urlopen(url).read().decode("utf-8", "replace")
    except Exception as e:
        raise PulseError(f"yt-dlp page fetch: {e}") from e
