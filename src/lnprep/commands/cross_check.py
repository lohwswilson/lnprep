"""
lnprep cross-check command: Verify pedagogical alignment, timings, and LO coverage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from lnprep.console import console, print_formatted, print_success, print_warning
from lnprep.core.cross_checker import cross_check_module

app = typer.Typer(help="Verify time budget, assessment linkage, LO coverage, and file references")


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
        help="Run only one check: budget, assessment, los, decks, readings",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output results as JSON",
    ),
) -> None:
    """Validate all session guides in a module for time budget and alignment."""
    res = cross_check_module(str(module_path), only=check)

    if as_json:
        print_formatted(res, as_json=True)
        return

    if res.get("status") == "NO_GUIDES":
        print_warning(f"No guides found in {module_path}: {res.get('reason')}")
        raise typer.Exit(code=1)

    console.print(f"[bold cyan]Cross-Check Results:[/bold cyan] {module_path.name}\n")

    overall_status = res.get("status", "UNKNOWN")
    if overall_status == "OK":
        print_success("Module passed all pedagogical cross-checks!")
    else:
        print_warning(f"Module cross-check status: {overall_status}")

    sessions = res.get("sessions", {})
    if sessions:
        table = Table(title="Session Cross-Checks", show_header=True)
        table.add_column("Session", style="bold")
        table.add_column("Status")
        table.add_column("Details")

        for sess_name, checks in sessions.items():
            if isinstance(checks, dict):
                st = checks.get("status", "INFO")
                color = "green" if st == "OK" else "yellow" if st == "NOT_CHECKABLE" else "red"
                table.add_row(sess_name, f"[{color}]{st}[/{color}]", str(checks.get("reason", ""))[:80])
            elif isinstance(checks, list):
                for chk in checks:
                    st = chk.get("status", "INFO")
                    color = "green" if st == "OK" else "yellow" if st == "NOT_CHECKABLE" else "red"
                    table.add_row(
                        f"{sess_name} ({chk.get('check', '')})",
                        f"[{color}]{st}[/{color}]",
                        str(chk.get("reason") or chk.get("unreferenced") or "")[:80],
                    )

        console.print(table)
