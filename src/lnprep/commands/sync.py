"""
lnprep sync command: Auto-extract MLOs and assessment tasks from syllabus / TLP documents.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from lnprep.console import console, print_formatted, print_warning
from lnprep.core.syllabus_sync import parse_syllabus


def sync_command(
    ctx: typer.Context,
    module_path: Path = typer.Argument(
        ...,
        help="Path to module folder",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output parsed syllabus data as JSON",
    ),
) -> None:
    """Scan module folder for TLP/handbook and extract MLOs and assessments."""
    data = parse_syllabus(str(module_path))

    if as_json:
        print_formatted(data, as_json=True)
        return

    console.print(f"[bold cyan]Syllabus Sync:[/bold cyan] {data.get('module_code')} — {data.get('module_title')}")
    files = data.get("syllabus_files", [])
    if files:
        console.print(f"[green]Discovered syllabus files:[/green] {', '.join(files)}")
    else:
        print_warning("No docx/pdf syllabus or TLP files found.")

    mlos = data.get("module_learning_outcomes", [])
    if mlos:
        table = Table(title="Module Learning Outcomes (MLOs)", show_header=True)
        table.add_column("#", style="cyan", width=4)
        table.add_column("Outcome", style="green")
        for i, mlo in enumerate(mlos, 1):
            table.add_row(str(i), mlo)
        console.print(table)

    assessments = data.get("assessments", [])
    if assessments:
        table_a = Table(title="Extracted Assessment Structures", show_header=True)
        table_a.add_column("Type", style="bold")
        table_a.add_column("Word Counts")
        table_a.add_column("Tasks")
        for a in assessments:
            table_a.add_row(
                str(a.get("type")),
                ", ".join(a.get("word_counts", [])) or "—",
                "; ".join(a.get("tasks", [])) or "—",
            )
        console.print(table_a)
