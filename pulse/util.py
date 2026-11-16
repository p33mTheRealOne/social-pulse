from __future__ import annotations

import html as htmllib
import re
from typing import Any, Iterator


def walk(obj: Any) -> Iterator[dict]:
    """Yield every dict inside a nested JSON structure (document order)."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def find_key(obj: Any, key: str) -> Any:
    for d in walk(obj):
        if d.get(key) is not None:
            return d[key]
    return None


def meta_content(page: str, prop: str) -> str:
    """Value of <meta property|name=prop content=...> (either attribute order)."""
    p = re.escape(prop)
    c = r'content=(?:"([^"]*)"|\'([^\']*)\')'
    for rx in (
        r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*%s' % (p, c),
        r'<meta[^>]+%s[^>]*(?:property|name)=["\']%s["\']' % (c, p),
    ):
        m = re.search(rx, page, re.I)
        if m:
            return htmllib.unescape(m.group(1) or m.group(2) or "")
    return ""
