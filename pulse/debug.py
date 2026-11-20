"""Optional diagnostics, enabled with --debug."""
from __future__ import annotations

import re
import sys
from pathlib import Path

enabled = False
DIR = Path("pulse-debug")

_WORDS = r"(?:count|view|play|share|repost|save|reaction|like)"
_NUM_RE = re.compile(r'\\*"([A-Za-z0-9_]*%s[A-Za-z0-9_]*)\\*"\s*:\s*(\d+)' % _WORDS, re.I)
_STR_RE = re.compile(r'\\*"([A-Za-z0-9_]*%s[A-Za-z0-9_]*)\\*"\s*:\s*\\*"(\d[\d.,]*\s?[KMBkmb]?)\\*"' % _WORDS, re.I)
_NEST_RE = re.compile(
    r'\\*"([A-Za-z0-9_]*(?:%s|comment)[A-Za-z0-9_]*)\\*"\s*:\s*\{\s*\\*"(?:count|total_count)\\*"\s*:\s*(\d+)' % _WORDS, re.I)


def log(msg: str) -> None:
    if enabled:
        print(f"[debug] {msg}", file=sys.stderr)


def dump(name: str, content: str) -> None:
    """Save a raw page/response so failures can be inspected."""
    if not enabled:
        return
    DIR.mkdir(exist_ok=True)
    path = DIR / name
    path.write_text(content, encoding="utf-8", errors="replace")
    log(f"saved raw response to {path}")


def _collect(rx, text: str, suffix: str = "") -> dict:
    seen: dict = {}
    for key, val in rx.findall(text):
        if key.lower().startswith("oz_"):  # player tuning noise
            continue
        vals = seen.setdefault(key + suffix, [])
        if val not in vals and len(vals) < 6:
            vals.append(val)
    return seen


def scan_counts(label: str, text: str, limit: int = 40) -> None:
    """Log every field whose name looks like an engagement counter (numbers, abbreviated strings, nested counts)."""
    if not enabled:
        return
    groups = (
        ("numeric", _collect(_NUM_RE, text)),
        ("string", _collect(_STR_RE, text)),
        ("nested .count", _collect(_NEST_RE, text, ".count")),
    )
    for name, seen in groups:
        items = list(seen.items())[:limit]
        log(f"{label} {name} fields: " + ("; ".join(f"{k}={','.join(v)}" for k, v in items) or "(none)"))
