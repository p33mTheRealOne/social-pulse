from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin, urlparse

from curl_cffi import requests as cffi

from . import debug
from .models import PulseError

IMPERSONATE = "chrome"  # alias: newest Chrome this curl_cffi version supports

# Requests (and every redirect hop) may only go to these hosts. This keeps the tool, and
# especially the HTTP API, from being turned into a fetcher for arbitrary or internal URLs.
ALLOWED_SUFFIXES = (
    "tiktok.com", "x.com", "twitter.com", "twimg.com", "t.co", "fxtwitter.com",
    "instagram.com", "instagr.am", "facebook.com", "fb.com", "fb.watch",
    "youtube.com", "youtu.be",
)
REDIRECT_CODES = (301, 302, 303, 307, 308)


def _allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_SUFFIXES)


def load_cookies(path: str, url: Optional[str] = None) -> dict[str, str]:
    """Parse a Netscape cookies.txt (including #HttpOnly_ lines) and keep cookies matching url's host."""
    host = (urlparse(url).hostname or "").lower() if url else ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError as e:
        raise PulseError(f"Cannot read cookies file: {e}") from e
    out: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            parts = line.split(None, 6)
        if len(parts) < 7:
            continue
        domain, name, value = parts[0].lstrip(".").lower(), parts[5], parts[6]
        if host and not (host == domain or host.endswith("." + domain)):
            continue
        out[name] = value
    return out


def _cookies_for(path: Optional[str], url: str) -> Optional[dict[str, str]]:
    if not path:
        return None
    jar = load_cookies(path, url)
    debug.log(f"cookies sent to {urlparse(url).hostname}: {sorted(jar)}")  # names only, never values
    return jar


def _proxies(proxy: Optional[str]):
    return {"http": proxy, "https": proxy} if proxy else None


def _follow(session, url: str, *, proxy, cookies_file, headers, timeout, max_hops: int = 6):
    """GET following redirects by hand so every hop can be checked against the allowlist."""
    for _ in range(max_hops + 1):
        if not _allowed(url):
            raise PulseError(f"Blocked request to a host that is not allowlisted: {urlparse(url).hostname}")
        resp = session.get(
            url,
            proxies=_proxies(proxy),
            cookies=_cookies_for(cookies_file, url),  # recomputed per hop: never sent to other hosts
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        )
        loc = resp.headers.get("location")
        if resp.status_code in REDIRECT_CODES and loc:
            url = urljoin(url, loc)
            continue
        return resp
    raise PulseError("Too many redirects")


def get(
    url: str,
    *,
    proxy: Optional[str] = None,
    cookies_file: Optional[str] = None,
    headers: Optional[dict] = None,
    timeout: int = 20,
    impersonate: Optional[str] = None,
    warmup: Optional[str] = None,
):
    """GET with a browser TLS fingerprint. Optional warmup URL is fetched first to collect cookies."""
    try:
        with cffi.Session(impersonate=impersonate or IMPERSONATE) as s:
            if warmup and _allowed(warmup):
                try:
                    s.get(warmup, proxies=_proxies(proxy), timeout=timeout)
                except Exception:
                    pass
            resp = _follow(s, url, proxy=proxy, cookies_file=cookies_file, headers=headers, timeout=timeout)
    except PulseError:
        raise
    except Exception as e:  # curl_cffi raises many error types
        raise PulseError(f"Request failed: {e}") from e
    if resp.status_code >= 400:
        raise PulseError(f"HTTP {resp.status_code} for {url}")
    return resp


def post_json(
    url: str,
    payload: dict,
    *,
    proxy: Optional[str] = None,
    cookies_file: Optional[str] = None,
    headers: Optional[dict] = None,
    timeout: int = 20,
):
    if not _allowed(url):
        raise PulseError("Blocked request to a host that is not allowlisted")
    try:
        resp = cffi.post(
            url,
            json=payload,
            impersonate=IMPERSONATE,
            proxies=_proxies(proxy),
            cookies=_cookies_for(cookies_file, url),
            headers=headers,
            timeout=timeout,
        )
    except PulseError:
        raise
    except Exception as e:
        raise PulseError(f"Request failed: {e}") from e
    if resp.status_code >= 400:
        raise PulseError(f"HTTP {resp.status_code} for {url}")
    return resp
