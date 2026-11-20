from __future__ import annotations

import re
from typing import Callable, List, Optional, Sequence
from urllib.parse import urlparse, urlsplit, urlunsplit

from . import debug, http
from .extractors import facebook, instagram, meta, tiktok, twitter, youtube
from .models import PostMetrics, PulseError, UnsupportedURL, merge

PLATFORM_DOMAINS = {
    "tiktok": ("tiktok.com",),
    "twitter": ("x.com", "twitter.com"),
    "instagram": ("instagram.com", "instagr.am"),
    "facebook": ("facebook.com", "fb.watch", "fb.com"),
    "youtube": ("youtube.com", "youtu.be"),
}
SHORTENERS = {"vm.tiktok.com", "vt.tiktok.com", "t.co", "fb.watch", "instagr.am"}
STRIP_QUERY = {"tiktok", "twitter", "instagram"}  # tracking params only; FB/YT need theirs

# Default: a source chain stops once these fields are filled.
EXPECTED = {
    "tiktok": ("likes", "comments", "shares", "saves", "views"),
    "twitter": ("likes", "comments", "reposts", "saves", "views"),
    "instagram": ("likes", "comments", "views"),
    "facebook": ("likes", "comments", "shares", "views"),
    "youtube": ("likes", "comments", "views"),
}
# Everything a platform can ever provide (used to avoid chasing impossible fields).
SUPPORTED = {
    "tiktok": {"likes", "comments", "reposts", "shares", "saves", "views"},
    "twitter": {"likes", "comments", "reposts", "saves", "views"},
    "instagram": {"likes", "comments", "reposts", "shares", "views"},
    "facebook": {"likes", "comments", "shares", "views"},
    "youtube": {"likes", "comments", "views"},
}
_FB_VIDEO = re.compile(r"/(reel|reels|videos?|watch)\b")
_IG_VIDEO = re.compile(r"/(reel|reels|tv)/")


def expected(platform: str, url: str):
    """Fields that should be filled for this kind of post; the source chain stops once they are."""
    if platform == "facebook" and not _FB_VIDEO.search(url):
        return ("likes", "comments", "shares")  # plain posts have no view counter
    if platform == "instagram" and not _IG_VIDEO.search(url):
        return ("likes", "comments")
    return EXPECTED[platform]


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def detect_platform(url: str) -> Optional[str]:
    host = _host(url)
    for platform, domains in PLATFORM_DOMAINS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return platform
    return None


def _needs_resolve(url: str) -> bool:
    path = urlparse(url).path
    platform = detect_platform(url)
    return (
        _host(url) in SHORTENERS
        or (platform == "tiktok" and path.startswith("/t/"))
        or (platform in ("instagram", "facebook") and "/share/" in path)
    )


def resolve(url: str, proxy: Optional[str] = None) -> str:
    """Follow short-link redirects (allowlisted hosts only) and return the final URL."""
    return str(http.get(url, proxy=proxy).url)


def normalize(url: str, platform: str) -> str:
    if platform in STRIP_QUERY or (
        platform == "facebook" and re.search(r"/(posts|reel|reels|videos)/", urlsplit(url).path)
    ):
        s = urlsplit(url)
        return urlunsplit((s.scheme, s.netloc, s.path, "", ""))
    return url


def pipeline(platform: str, url: str, has_cookies: bool = False, local_only: bool = False) -> List[str]:
    """Sources to try, in order. Results are merged: earlier sources win per field."""
    if platform == "tiktok":
        return ["tiktok", "tiktok-ydl", "yt-dlp"]
    if platform == "twitter":
        return ["twitter"] + ([] if local_only else ["fxtwitter"]) + ["yt-dlp"]
    if platform == "instagram":
        steps = ["yt-dlp", "instagram"] if _IG_VIDEO.search(url) else ["instagram", "yt-dlp"]
        return (["ig-api"] if has_cookies else []) + steps
    if platform == "facebook":
        return ["yt-dlp", "facebook"] if _FB_VIDEO.search(url) else ["facebook", "yt-dlp"]
    return ["yt-dlp"]  # youtube


def _run(name: str, platform: str, url: str, proxy, cookies) -> PostMetrics:
    if name == "tiktok":
        return tiktok.extract(url, proxy=proxy, cookies=cookies)
    if name == "tiktok-ydl":
        return tiktok.extract_via_ytdlp(url, proxy=proxy, cookies=cookies)
    if name == "twitter":
        return twitter.extract(url, proxy=proxy, cookies=cookies)
    if name == "fxtwitter":
        return twitter.extract_fx(url, proxy=proxy, cookies=cookies)
    if name == "instagram":
        return instagram.extract(url, proxy=proxy, cookies=cookies)
    if name == "ig-api":
        return instagram.extract_api(url, proxy=proxy, cookies=cookies)
    if name == "facebook":
        return facebook.extract(url, proxy=proxy, cookies=cookies)
    return meta.extract(url, platform, proxy=proxy, cookies=cookies)


def fetch(
    url: str,
    *,
    proxy: Optional[str] = None,
    cookies: Optional[str] = None,
    local_only: bool = False,
    fields: Optional[Sequence[str]] = None,
    log: Optional[Callable[[str], None]] = None,
    warn: Optional[Callable[[str], None]] = None,
) -> PostMetrics:
    """Fetch metrics. `fields` limits the work: sources stop as soon as the wanted fields are filled."""
    log = log or (lambda m: None)
    warn = warn or (lambda m: None)
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    if urlparse(url).scheme not in ("http", "https"):
        raise UnsupportedURL("Only http(s) URLs are supported")
    if _needs_resolve(url):
        try:
            url = resolve(url, proxy)
        except PulseError:
            pass  # detection below reports the problem
    platform = detect_platform(url)
    if platform is None:
        raise UnsupportedURL(f"Unsupported or unrecognized URL: {url}")
    url = normalize(url, platform)

    want = tuple(fields) if fields else None
    target = [f for f in (want or expected(platform, url)) if f in SUPPORTED[platform] or f == "author"]

    result: Optional[PostMetrics] = None
    errors: List[str] = []
    views_from: Optional[str] = None
    for name in pipeline(platform, url, has_cookies=bool(cookies), local_only=local_only):
        if name == "ig-api" and want is not None and not (set(want) & {"reposts", "shares", "views"}):
            continue  # the logged-in API is only worth calling for these fields
        try:
            part = _run(name, platform, url, proxy, cookies)
        except PulseError as e:
            msg = str(e).splitlines()[0][:900]
            errors.append(f"{name}: {msg}")
            log(f"{name} failed ({msg})")
            continue
        debug.log(f"{name} returned {part.model_dump(exclude_none=True)}")
        if views_from is None and part.views is not None:
            views_from = name
        result = part if result is None else merge(result, part)
        if all(getattr(result, k) is not None for k in target):
            break
    if result is None:
        raise PulseError(" | ".join(errors))
    if platform == "instagram" and result.views is not None and (want is None or "views" in want):
        source = "app" if views_from == "ig-api" else "public"
        result = result.model_copy(update={"views_source": source})
        if source == "public":
            warn("Instagram views come from a legacy public counter (marked views_source: public) and can be "
                 "lower than the play count shown in the app. Use --cookies to get the app's number.")
    if platform == "youtube" and (want is None or "comments" in want):
        result = youtube.refine(result, proxy=proxy, cookies=cookies)
    return result
