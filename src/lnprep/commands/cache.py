"""
lnprep cache command: Manage the per-module academic citation cache.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from lnprep.console import console, print_error, print_formatted, print_info, print_success, print_warning
from lnprep.core import citation_db as cc

app = typer.Typer(help="Manage per-module academic citation cache (180-day TTL)")


@app.command("lookup")
def cache_lookup(
    module_path: Path = typer.Argument(
        ...,
        help="Path to module folder or PPTX within module",
        exists=True,
    ),
    author: str = typer.Argument(..., help="Author name, e.g. 'Ackoff' or 'Christopher'"),
    year: str = typer.Argument(..., help="Publication year, e.g. '1989'"),
    ttl_days: int = typer.Option(180, "--ttl-days", help="TTL in days"),
    as_json: bool = typer.Option(False, "--json", help="Output result as JSON"),
) -> None:
    """Look up a citation in the module's cache."""
    root = cc.find_module_root(str(module_path))
    data = cc.load(root)
    status, entry, days_left = cc.lookup(data, author, year, ttl_days=ttl_days)

    if as_json:
        print_formatted(
            {"status": status, "entry": entry, "days_left": days_left, "module_root": root},
            as_json=True,
        )
        if status == "MISS":
            raise typer.Exit(code=1)
        return

    if status == "HIT_FRESH":
        print_success(f"HIT (FRESH) — {days_left:.1f} days remaining")
        console.print(entry)
    elif status == "HIT_STALE":
        print_warning(f"HIT (STALE) — expired {abs(days_left):.1f} days ago")
        console.print(entry)
    else:
        print_info(f"MISS — not cached for module: {root}")
        raise typer.Exit(code=1)


@app.command("record")
def cache_record(
    module_path: Path = typer.Argument(..., help="Path to module folder or PPTX", exists=True),
    author: str = typer.Argument(..., help="Author name"),
    year: str = typer.Argument(..., help="Year"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="Paper or book title"),
    doi: Optional[str] = typer.Option(None, "--doi", "-d", help="Digital Object Identifier"),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Verified URL"),
    isbn: Optional[str] = typer.Option(None, "--isbn", help="ISBN"),
    ttl_days: int = typer.Option(180, "--ttl-days", help="TTL in days"),
    as_json: bool = typer.Option(False, "--json", help="Output JSON result"),
) -> None:
    """Record a verified citation to the module's cache."""
    root = cc.find_module_root(str(module_path))
    res = cc.record_entry(
        root,
        author,
        year,
        title=title,
        doi=doi,
        url=url,
        isbn=isbn,
        ttl_days=ttl_days,
        quiet=as_json,
    )
    if res != 0:
        if as_json:
            print_formatted({"success": False, "error": "Failed to record citation"}, as_json=True)
        else:
            print_error("Failed to record citation. Evidence (title, doi, url, or isbn) is required.")
        raise typer.Exit(code=res)

    if as_json:
        print_formatted({"success": True, "author": author, "year": year, "module_root": root}, as_json=True)
    else:
        print_success(f"Recorded citation {author} ({year}) to module cache.")


@app.command("report")
def cache_report(
    module_path: Path = typer.Argument(..., help="Path to module folder or PPTX", exists=True),
    ttl_days: int = typer.Option(180, "--ttl-days", help="TTL in days"),
    as_json: bool = typer.Option(False, "--json", help="Output report as JSON"),
) -> None:
    """Generate status report for the module's citation cache."""
    root = cc.find_module_root(str(module_path))
    rep = cc.get_report_data(root, ttl_days=ttl_days)

    if as_json:
        print_formatted(rep, as_json=True)
        return

    console.print(f"[bold cyan]Citation Cache Report:[/bold cyan] {rep.get('cache_file')}")
    console.print(f"Total: {rep.get('total')} | Fresh: [green]{rep.get('fresh')}[/green] | Stale: [yellow]{rep.get('stale')}[/yellow]\n")

    entries = rep.get("entries", [])
    if entries:
        table = Table(title="Cached Citations", show_header=True)
        table.add_column("Citation", style="bold", width=22)
        table.add_column("Status", width=12)
        table.add_column("Days Left", justify="right", width=10)
        table.add_column("Hits", justify="right", width=6)
        table.add_column("Title / Evidence")

        for e in entries:
            st = e.get("status")
            color = "green" if st == "FRESH" else "yellow"
            left = f"{e.get('days_left', 0):.0f}" if st == "FRESH" else f"-{abs(e.get('days_left', 0)):.0f}"
            ev = e.get("doi") or e.get("url") or e.get("title") or "—"
            table.add_row(
                f"{e.get('author')} ({e.get('year')})",
                f"[{color}]{st}[/{color}]",
                left,
                str(e.get("hits", 0)),
                str(ev)[:45],
            )
        console.print(table)
    else:
        print_info("No citations currently cached in this module.")


@app.command("prune")
def cache_prune(
    module_path: Path = typer.Argument(..., help="Path to module folder or PPTX", exists=True),
    ttl_days: int = typer.Option(180, "--ttl-days", help="TTL in days"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report expired entries without deleting"),
    as_json: bool = typer.Option(False, "--json", help="Output JSON"),
) -> None:
    """Prune stale citations beyond their TTL from the cache."""
    root = cc.find_module_root(str(module_path))
    if dry_run:
        rep = cc.get_report_data(root, ttl_days=ttl_days)
        stale_entries = [e for e in rep.get("entries", []) if e.get("status") == "STALE"]
        if as_json:
            print_formatted({"dry_run": True, "stale_count": len(stale_entries), "stale": stale_entries}, as_json=True)
        else:
            print_info(f"Dry run: {len(stale_entries)} stale citation(s) would be pruned.")
        return

    kept, dropped, keys = cc.prune(root, ttl_days=ttl_days)
    if as_json:
        print_formatted({"kept": kept, "dropped": dropped, "pruned_keys": keys}, as_json=True)
        return

    print_success(f"Pruned cache: kept {kept}, dropped {dropped} expired citation(s).")


@app.command("hit")
def cache_hit(
    module_path: Path = typer.Argument(..., help="Path to module folder or PPTX", exists=True),
    author: str = typer.Argument(..., help="Author name"),
    year: str = typer.Argument(..., help="Year"),
    as_json: bool = typer.Option(False, "--json", help="Output JSON"),
) -> None:
    """Log an audit hit for a cached citation to track usage."""
    root = cc.find_module_root(str(module_path))
    code = cc.log_hit(root, author, year)
    if code == 0:
        if as_json:
            print_formatted({"success": True, "author": author, "year": year}, as_json=True)
        else:
            print_success(f"Logged cache hit for {author} ({year})")
    else:
        if as_json:
            print_formatted({"success": False, "author": author, "year": year}, as_json=True)
        else:
            print_error(f"Citation {author} ({year}) not found in cache.")
        raise typer.Exit(code=code)
