"""
lnprep write command: Direct XML injection of lecture notes into PPTX slides.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import typer
from rich.table import Table

from lnprep.console import console, print_error, print_formatted, print_info, print_success
from lnprep.core import ref_verifier as vr
from lnprep.core.writer_engine import (
    backup_once,
    batch_update_notes,
    ensure_local_copy,
    load_notes_payload,
    sync_back,
)

app = typer.Typer(help="Write notes to PPTX slides via Direct XML injection with backup and gate")


@app.callback(invoke_without_command=True)
def write_command(
    ctx: typer.Context,
    pptx_path: Path = typer.Argument(
        ...,
        help="Path to PPTX file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    slide_num: Optional[int] = typer.Argument(
        None,
        help="Slide number (1-indexed) if writing a single slide",
    ),
    notes_text: Optional[str] = typer.Argument(
        None,
        help="Notes text string or file path containing notes",
    ),
    notes: Optional[str] = typer.Option(
        None,
        "--notes",
        "-n",
        help="Notes text string or file path containing notes (avoids leading dash issues)",
    ),
    batch_json: Optional[Path] = typer.Option(
        None,
        "--batch-json",
        "-b",
        help="Path to JSON file containing batched notes: {'slides': [{'slide': N, 'notes': '...'}]}",
    ),
    allow_unverified: bool = typer.Option(
        False,
        "--allow-unverified",
        help="Override reference gate and write even if unverified references exist",
    ),
    no_backup: bool = typer.Option(
        False,
        "--no-backup",
        help="Skip creating a .bak backup file",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output write result as JSON",
    ),
) -> None:
    """Safely inject notes directly into slide XML with verification gate and backup."""
    entries: List[Tuple[int, str]] = []

    target_notes = notes or notes_text

    if batch_json:
        payload = load_notes_payload(str(batch_json))
        slides_list = payload.get("slides", [])
        if not slides_list and isinstance(payload, list):
            slides_list = payload
        for s in slides_list:
            entries.append((int(s["slide"]), s["notes"]))
    elif slide_num is not None:
        if not target_notes:
            # Check if text was piped via stdin
            if not sys.stdin.isatty():
                target_notes = sys.stdin.read()
            else:
                print_error("Notes text is required when specifying a slide number.")
                raise typer.Exit(code=1)
        elif os.path.exists(target_notes):
            with open(target_notes, "r", encoding="utf-8") as f:
                target_notes = f.read()

        entries.append((slide_num, target_notes))
    else:
        print_error("Specify slide_num and notes, or provide --batch-json <file>")
        raise typer.Exit(code=1)

    if not entries:
        print_error("No notes entries found to write.")
        raise typer.Exit(code=1)

    notes_by_slide = {s: n for s, n in entries}

    # Reference verification gate
    gate_buf = io.StringIO()
    allowed = vr.gate(
        notes_by_slide,
        str(pptx_path),
        allow_unverified=allow_unverified,
        out=gate_buf,
    )
    gate_output = gate_buf.getvalue()

    if not allowed:
        if as_json:
            print_formatted(
                {"success": False, "gate_passed": False, "message": gate_output},
                as_json=True,
            )
        else:
            console.print(gate_output)
            print_error("Write-back cancelled by reference verification gate.")
        raise typer.Exit(code=1)

    # Backup & staging
    backup_file = None
    if not no_backup:
        backup_file = backup_once(str(pptx_path))
        if not as_json and backup_file:
            print_info(f"Backup verified → {backup_file}")

    ensure_local_copy(str(pptx_path))

    # Perform XML injection
    res = batch_update_notes(str(pptx_path), entries)

    # Sync back to original file
    sync_back(str(pptx_path))

    if as_json:
        res["success"] = True
        res["backup"] = backup_file
        print_formatted(res, as_json=True)
        return

    print_success(f"Successfully updated {res['updated']} slide(s) in {pptx_path.name}")

    v_table = Table(title="Write & Verify Status", show_header=True)
    v_table.add_column("Slide", style="cyan", width=6)
    v_table.add_column("⏱ Time Badge", justify="center")
    v_table.add_column("Speaker Notes", justify="center")
    v_table.add_column("Lecture Notes", justify="center")
    v_table.add_column("Visual Decon", justify="center")

    for v in res.get("verification", []):
        chk = v.get("checks", {})
        time_ok = "[green]✔[/green]" if chk.get("⏱") else "[red]✘[/red]"
        spk_ok = "[green]✔[/green]" if chk.get("--- SPEAKER NOTES ---") else "[red]✘[/red]"
        lec_ok = "[green]✔[/green]" if chk.get("--- LECTURE NOTES ---") else "[red]✘[/red]"
        vd_ok = "[green]✔[/green]" if chk.get("--- VISUAL DECONSTRUCTION ---") else "[dim]—[/dim]"
        v_table.add_row(str(v["slide"]), time_ok, spk_ok, lec_ok, vd_ok)

    console.print(v_table)
