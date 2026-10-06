"""
lnprep cross-check command: Verify pedagogical alignment, timings, and LO coverage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from lnprep.console import console, print_error, print_formatted, print_success, print_warning
from lnprep.core.cross_checker import cross_check_module

app = typer.Typer(help="Verify time budget, assessment linkage, LO coverage, and file references")

CHECK_ALIASES = {"los": "lo", "decks": "deck", "readings": "reading"}
CHECK_NAMES = ("budget", "assessment", "lo", "deck", "reading")


def _check_rows(res):
    """Flatten session and module checks into (scope, check, result) rows."""
    for session_name, session in res.get("sessions", {}).items():
        if not isinstance(session, dict):
            continue
        if session.get("status") == "NOT_CHECKABLE" and session.get("reason"):
            yield session_name, "guide", session
        for key in ("budget", "deck", "reading"):
            check = session.get(key)
            if isinstance(check, dict):
                yield session_name, key, check
    for key, check in res.get("module_checks", {}).items():
        if isinstance(check, dict):
            yield "(module)", key, check


@app.callback(invoke_without_command=True)
def cross_check_command(
    ctx: typer.Context,
    module_path: Path = typer.Argument(
        ...,
        help="Path to module folder",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    check: Optional[str] = typer.Option(
        None,
        "--check",
        "-c",
        help="Run only one check: budget, assessment, lo, deck, reading",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output results as JSON",
    ),
) -> None:
    """Validate all session guides in a module for time budget and alignment."""
    only = (check or "").strip().lower() or None
    if only:
        only = CHECK_ALIASES.get(only, only)
    if only is not None and only not in CHECK_NAMES:
        # Previously an unrecognised value matched no branch and silently ran nothing.
        print_error(f"Unknown --check value {check!r}. Choose from: {', '.join(CHECK_NAMES)}.")
        raise typer.Exit(code=2)

    res = cross_check_module(str(module_path), only=only)

    if as_json:
        print_formatted(res, as_json=True)
        if res.get("status") == "FAIL":
            raise typer.Exit(code=1)
        return

    if res.get("status") == "NO_GUIDES":
        print_warning(f"No guides found in {module_path}: {res.get('reason')}")
        raise typer.Exit(code=1)

    console.print(f"[bold cyan]Cross-Check Results:[/bold cyan] {module_path.name}\n")

    rows = list(_check_rows(res))
    failed = [row for row in rows if row[2].get("status") == "FAIL"]

    overall_status = res.get("status", "UNKNOWN")
    if overall_status == "OK":
        print_success("Module passed all pedagogical cross-checks.")
    elif overall_status == "NOT_CHECKABLE":
        print_warning("Nothing could be checked — no budgets, linkages or files to validate.")
    else:
        print_error(f"Module cross-check FAILED — {len(failed)} check(s) need attention.")

    if rows:
        table = Table(title="Cross-Checks", show_header=True)
        table.add_column("Scope", style="bold")
        table.add_column("Check")
        table.add_column("Status")
        table.add_column("Details")

        for scope, name, chk in rows:
            st = str(chk.get("status", "INFO"))
            color = "green" if st == "OK" else "yellow" if st in ("NOT_CHECKABLE", "PARTIAL") else "red"
            detail = chk.get("problems") or chk.get("unreferenced") or chk.get("reason") or ""
            if isinstance(detail, list):
                detail = "; ".join(str(d) for d in detail)
            table.add_row(scope, name, f"[{color}]{st}[/{color}]", str(detail)[:70])
        console.print(table)

    if failed:
        raise typer.Exit(code=1)
