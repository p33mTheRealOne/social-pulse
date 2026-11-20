from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import List, Optional

import typer
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import __version__, debug, router
from .models import IDENTITY_FIELDS, METRIC_FIELDS, PostMetrics, PulseError, parse_fields, select

app = typer.Typer(
    add_completion=False,
    help="Engagement metrics for public social posts. No browser, no API keys.",
)
out = Console()
err = Console(stderr=True)

COLUMNS = [
    ("platform", "Platform"), ("author", "Author"), ("likes", "Likes"),
    ("comments", "Comments"), ("reposts", "Reposts"), ("shares", "Shares"),
    ("saves", "Saves"), ("views", "Views"),
]


def _fmt(v) -> str:
    return "-" if v is None else (f"{v:,}" if isinstance(v, int) else str(v))


def _cell(r: PostMetrics, key: str) -> str:
    text = _fmt(getattr(r, key))
    if key == "views" and r.views is not None and r.views_source == "public":
        text += " (public)"
    return text


def columns_for(fields) -> list:
    return [(k, t) for k, t in COLUMNS if k == "platform" or fields is None or k in fields]


def render_table(results: List[PostMetrics], fields=None) -> Table:
    cols = columns_for(fields)
    table = Table(box=box.ROUNDED, title="social-pulse")
    for key, title in cols:
        table.add_column(title, justify="left" if key in ("platform", "author") else "right")
    for r in results:
        table.add_row(*[_cell(r, k) for k, _ in cols])
    return table


def read_urls(file: Path) -> List[str]:
    lines = file.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def write_report(results: List[PostMetrics], path: Path, fields=None) -> None:
    rows = [select(r, fields) for r in results]
    names = list(IDENTITY_FIELDS) + [k for k in ("author",) + METRIC_FIELDS if fields is None or k in fields]
    if "views" in names:
        names.insert(names.index("views") + 1, "views_source")
    if path.suffix.lower() == ".csv":
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=names, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    else:
        path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def _version(value: bool):
    if value:
        typer.echo(f"social-pulse {__version__}")
        raise typer.Exit()


@app.command()
def main(
    url: Optional[str] = typer.Argument(None, help="Post or video URL (TikTok, Instagram, Facebook, X, YouTube)."),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Text file with one URL per line."),
    fields: Optional[str] = typer.Option(
        None, "--fields", "-F",
        help="Only fetch these, comma-separated: author,likes,comments,reposts,shares,saves,views (default: all).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print raw JSON (pipe into jq)."),
    cookies: Optional[str] = typer.Option(None, "--cookies", help="Netscape cookies.txt from your own browser session."),
    proxy: Optional[str] = typer.Option(None, "--proxy", help="HTTP or SOCKS5 proxy, e.g. socks5://127.0.0.1:9050"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Save report to .csv or .json."),
    local_only: bool = typer.Option(False, "--local-only", help="Never call third-party services (api.fxtwitter.com)."),
    debug_mode: bool = typer.Option(False, "--debug", help="Show what each source returned; save raw pages to ./pulse-debug/"),
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True),
):
    debug.enabled = debug_mode
    try:
        want = parse_fields(fields)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    urls = ([url] if url else []) + (read_urls(file) if file else [])
    if not urls:
        err.print("[red]Provide a URL or --file links.txt[/red]")
        raise typer.Exit(2)

    results: List[PostMetrics] = []
    failures = 0
    for u in urls:
        try:
            results.append(router.fetch(
                u, proxy=proxy, cookies=cookies, local_only=local_only, fields=want,
                log=lambda m: err.print(f"[yellow]note:[/yellow] {escape(m)}"),
                warn=lambda m: err.print(f"[yellow]warning:[/yellow] {escape(m)}"),
            ))
        except PulseError as e:
            failures += 1
            err.print(f"[red]ERROR[/red] {escape(u)}: {escape(str(e))}")

    if as_json:
        data = [select(r, want) for r in results]
        typer.echo(json.dumps(data[0] if len(urls) == 1 and data else data, indent=2, ensure_ascii=False))
    elif results:
        out.print(render_table(results, want))
    if output and results:
        write_report(results, output, want)
        err.print(f"Saved {len(results)} result(s) to {output}")
    if failures:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
