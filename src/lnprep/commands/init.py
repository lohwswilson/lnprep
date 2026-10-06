"""
lnprep init command: Initialise LECTURE_NOTES_GUIDE.md for a module folder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from lnprep.console import console, print_formatted, print_success, print_warning
from lnprep.core.syllabus_sync import generate_guide


def init_command(
    ctx: typer.Context,
    module_path: Path = typer.Argument(
        ...,
        help="Path to module folder (e.g. MO9529.IOM)",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    class_size: Optional[int] = typer.Option(
        None,
        "--class-size",
        "-c",
        help="Class size / student count",
    ),
    style: Optional[str] = typer.Option(
        None,
        "--style",
        "-s",
        help="Pedagogical style bias (practical, analytical, strategic-case-based, theoretical)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing LECTURE_NOTES_GUIDE.md",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output result as JSON",
    ),
) -> None:
    """Initialise LECTURE_NOTES_GUIDE.md for a module folder."""
    success, msg, meta = generate_guide(
        str(module_path),
        class_size=class_size,
        style=style,
        force=force,
    )

    if as_json:
        print_formatted({"success": success, "message": msg, "meta": meta}, as_json=True)
        if not success:
            raise typer.Exit(code=1)
        return

    if not success:
        print_warning(msg)
        raise typer.Exit(code=1)

    print_success(f"Guide generated → {meta.get('guide_path')}")

    table = Table(title="Module Guide Initialized", show_header=True)
    table.add_column("Property", style="bold cyan")
    table.add_column("Value", style="green")

    table.add_row("Module Code", str(meta.get("module_code")))
    table.add_row("Module Name", str(meta.get("module_name")))
    table.add_row("Institution", str(meta.get("institution")))
    table.add_row("Total Sessions", str(meta.get("total_sessions")))
    table.add_row("Topics Extracted", str(meta.get("topics_extracted")))

    console.print(table)
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Review LECTURE_NOTES_GUIDE.md and verify learning outcomes")
    console.print("  2. Fill in assessment links and session dates")
