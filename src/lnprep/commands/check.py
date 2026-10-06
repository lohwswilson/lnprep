"""
lnprep check command: Composite pre-flight gate running SBC audit and reference verification.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import typer
from pptx import Presentation
from rich.table import Table

from lnprep.console import console, print_error, print_formatted, print_success
from lnprep.core import citation_db as cc
from lnprep.core import ref_verifier as vr
from lnprep.core.audit_engine import run_audit
from lnprep.core.common import get_slide_notes_text


def check_command(
    ctx: typer.Context,
    pptx_path: Path = typer.Argument(
        ...,
        help="Path to PPTX file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    slide: Optional[int] = typer.Option(
        None,
        "--slide",
        "-s",
        help="Check a single slide (1-indexed)",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output check results as JSON",
    ),
) -> None:
    """Pre-flight check: runs both SBC audit and reference verification gate."""
    # 1. Audit
    audit_res = run_audit(str(pptx_path), slide_num=slide)
    audit_summary = audit_res.get("summary", {})
    # Deny-list, not allow-list. Counting only four named statuses silently dropped
    # GAPS, NO_NOTES and anything added later, so a deck that was entirely gaps passed.
    failing = {
        status: count
        for status, count in audit_summary.items()
        if count and status.upper() not in ("PASS", "SKIPPED")
    }
    audit_failures = sum(failing.values())

    # 2. Extract notes and run reference check
    prs = Presentation(str(pptx_path))
    notes_by_slide: Dict[int, str] = {}
    for i, s in enumerate(prs.slides):
        num = i + 1
        if slide is not None and num != slide:
            continue
        txt = get_slide_notes_text(s)
        if txt:
            notes_by_slide[num] = txt

    root = cc.find_module_root(str(pptx_path))
    ref_rep = vr.verify_notes(notes_by_slide, cache_root=root)
    blocking_refs = ref_rep.get("blocking", 0)

    overall_pass = (audit_failures == 0) and (blocking_refs == 0)

    if as_json:
        print_formatted(
            {
                "pass": overall_pass,
                "audit": {
                    "total_slides": audit_res.get("total_slides"),
                    "summary": audit_summary,
                    "failures": audit_failures,
                },
                "references": {
                    "counts": ref_rep.get("counts", {}),
                    "blocking": blocking_refs,
                },
            },
            as_json=True,
        )
        if not overall_pass:
            raise typer.Exit(code=1)
        return

    console.print(f"[bold cyan]Pre-flight Gate Check:[/bold cyan] {pptx_path.name}\n")

    gate_table = Table(title="Pre-flight Gate Status", show_header=True)
    gate_table.add_column("Check", style="bold")
    gate_table.add_column("Status", justify="center")
    gate_table.add_column("Details")

    audit_status = "[green]PASS[/green]" if audit_failures == 0 else f"[red]FAIL ({audit_failures} slides)[/red]"
    failing_detail = ", ".join(f"{k}: {v}" for k, v in sorted(failing.items())) or "no findings"
    gate_table.add_row(
        "SBC 5-Pass Audit",
        audit_status,
        f"Pass: {audit_summary.get('pass', 0)} · flagged: {audit_failures} ({failing_detail})",
    )

    ref_status = "[green]PASS[/green]" if blocking_refs == 0 else f"[red]FAIL ({blocking_refs} blocking)[/red]"
    ref_detail = ", ".join(f"{k}: {v}" for k, v in ref_rep.get("counts", {}).items()) or "no references found"
    gate_table.add_row(
        "Reference Verification Gate",
        ref_status,
        f"{ref_detail} ({blocking_refs} blocking issues)",
    )

    console.print(gate_table)

    if overall_pass:
        print_success("Pre-flight gate passed! Deck is ready for presentation or distribution.")
    else:
        print_error("Pre-flight gate failed. Resolve the highlighted issues above before releasing.")
        raise typer.Exit(code=1)
