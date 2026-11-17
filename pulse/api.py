"""HTTP API around the same engine as the CLI.

Run:  pulse-api            (or: uvicorn pulse.api:app)
Docs: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import __version__, router
from .models import ALL_FIELDS, PulseError, UnsupportedURL, parse_fields, select

app = FastAPI(
    title="social-pulse API",
    version=__version__,
    description="Engagement metrics (likes, comments, reposts, shares, saves, views) for public posts.",
)

_lock = threading.Lock()
_hits: Dict[str, Deque[float]] = {}
_cache: Dict[tuple, Tuple[float, dict]] = {}
MAX_BATCH = 10


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _keys() -> List[str]:
    return [k.strip() for k in os.getenv("PULSE_API_KEYS", "").split(",") if k.strip()]


def _charge(who: str, n: int = 1) -> None:
    """Sliding one-minute window per API key (or client IP when anonymous)."""
    limit = _env_int("PULSE_RATE_LIMIT", 30)
    now = time.monotonic()
    with _lock:
        q = _hits.setdefault(who, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) + n > limit:
            retry = int(60 - (now - q[0])) + 1 if q else 60
            raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": str(retry)})
        q.extend([now] * n)


def guard(request: Request, x_api_key: Optional[str] = Header(default=None)) -> str:
    keys = _keys()
    if keys:
        ok = bool(x_api_key) and any(
            secrets.compare_digest(x_api_key.encode(), k.encode()) for k in keys
        )
        if not ok:
            raise HTTPException(401, "Invalid or missing X-API-Key header")
        who = "key:" + x_api_key
    elif os.getenv("PULSE_ALLOW_ANONYMOUS") == "1":
        who = "ip:" + (request.client.host if request.client else "unknown")
    else:
        raise HTTPException(503, "Server has no API keys configured (set PULSE_API_KEYS)")
    _charge(who)
    return who


def _local(flag: bool) -> bool:
    return flag or os.getenv("PULSE_LOCAL_ONLY") == "1"


def _fetch(url: str, want: Optional[tuple], local_only: bool) -> dict:
    ttl = _env_int("PULSE_CACHE_TTL", 60)
    key = (url.strip(), want, local_only)
    now = time.monotonic()
    if ttl > 0:
        with _lock:
            hit = _cache.get(key)
            if hit and hit[0] > now:
                return {**hit[1], "cached": True}
    warnings: List[str] = []
    try:
        m = router.fetch(
            url,
            proxy=os.getenv("PULSE_PROXY") or None,
            cookies=os.getenv("PULSE_COOKIES_FILE") or None,  # server-side only; never taken from requests
            local_only=local_only,
            fields=want,
            warn=warnings.append,
        )
    except UnsupportedURL as e:
        raise HTTPException(400, str(e)[:300])
    except PulseError as e:
        raise HTTPException(502, f"Could not fetch metrics: {str(e)[:300]}")
    payload = {
        **select(m, want),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "warnings": warnings,
    }
    if ttl > 0:
        with _lock:
            if len(_cache) > 1000:
                for k in [k for k, v in _cache.items() if v[0] <= now]:
                    _cache.pop(k, None)
                if len(_cache) > 1000:
                    _cache.clear()
            _cache[key] = (now + ttl, payload)
    return {**payload, "cached": False}


def _want(fields) -> Optional[tuple]:
    try:
        return parse_fields(fields)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/v1/fields", tags=["meta"])
def list_fields() -> dict:
    return {"fields": list(ALL_FIELDS), "always_included": ["platform", "post_id", "url"]}


@app.get("/v1/metrics", tags=["metrics"])
def get_metrics(
    url: str = Query(..., max_length=2048, description="Public post or video URL"),
    fields: Optional[str] = Query(None, description="Comma-separated, e.g. likes,views (default: all)"),
    local_only: bool = Query(False, description="Do not use third-party services (affects X)"),
    who: str = Depends(guard),
) -> dict:
    return _fetch(url, _want(fields), _local(local_only))


class BatchBody(BaseModel):
    urls: List[str] = Field(..., min_length=1, max_length=MAX_BATCH)
    fields: Optional[List[str]] = None
    local_only: bool = False


@app.post("/v1/metrics/batch", tags=["metrics"])
def post_batch(body: BatchBody, who: str = Depends(guard)) -> dict:
    want = _want(body.fields)
    _charge(who, len(body.urls) - 1)  # guard already charged one request
    results = []
    for u in body.urls:
        try:
            results.append({"ok": True, "data": _fetch(u[:2048], want, _local(body.local_only))})
        except HTTPException as e:
            results.append({"ok": False, "url": u[:2048], "status": e.status_code, "error": e.detail})
    return {"results": results}


def main() -> None:
    import uvicorn

    uvicorn.run("pulse.api:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
