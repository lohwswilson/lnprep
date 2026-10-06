"""
lnprep audit command: Run 5-pass SBC quality, coverage, and depth audit on PPTX slides.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from lnprep.config import DEFAULT_ALIGNMENT_THRESHOLD, DEFAULT_MIN_OVERLAP
from lnprep.console import console, print_formatted, print_info, print_success
from lnprep.core.audit_engine import AUDIT_STATUSES, run_audit


def audit_command(
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
        help="Audit a single slide (1-indexed)",
    ),
    threshold: float = typer.Option(
        DEFAULT_ALIGNMENT_THRESHOLD,
        "--threshold",
        "-t",
        help="Jaccard similarity threshold for alignment pass",
    ),
    min_overlap: int = typer.Option(
        DEFAULT_MIN_OVERLAP,
        "--min-overlap",
        help="Minimum overlapping content terms required",
    ),
    depth_summary: bool = typer.Option(
        False,
        "--depth-summary",
        help="Print depth roll-up breakdown",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output audit results as JSON",
    ),
) -> None:
    """Run 5-pass SBC audit: coverage, alignment, quality, depth, and cadence."""
    audit_res = run_audit(
        str(pptx_path),
        slide_num=slide,
        jaccard_threshold=threshold,
        min_overlap=min_overlap,
        depth_summary=depth_summary,
    )

    if as_json:
        print_formatted(audit_res, as_json=True)
        return

    summary = audit_res.get("summary", {})
    results = audit_res.get("results", [])

    console.print(f"[bold cyan]SBC Audit:[/bold cyan] {audit_res.get('file')}")
    console.print(f"Total slides audited: [bold]{len(results)}[/bold]\n")

    fs = audit_res.get("format_spec", {})
    if fs.get("bound"):
        console.print(f"[green]Format spec:[/green] BOUND — {', '.join(fs['bound'])}")
    elif fs.get("draft"):
        console.print(f"[yellow]Format spec:[/yellow] DRAFT present, NOT bound — {', '.join(fs['draft'])}")
    else:
        console.print("[dim]Format spec: built-in default canon[/dim]")

    cad = audit_res.get("cadence")
    if cad:
        console.print(f"Engagement cadence: [bold]{cad['status']}[/bold] (Longest gap: {cad['longest_gap_minutes']}m)")

    console.print()

    # Summary table
    sum_table = Table(title="Audit Results by Status", show_header=True)
    sum_table.add_column("Status", style="bold")
    sum_table.add_column("Count", justify="right")
    sum_table.add_column("Description")

    status_desc = {
        "PASS": ("green", "Full coverage, aligned, quality and depth bars met"),
        "GAPS": ("yellow", "Slide body items missing in SBC section"),
        "MISALIGNED": ("red", "Vocabulary differs significantly from slide"),
        "WEAK_QUALITY": ("red", "Fails 6-marker quality floor"),
        "SHALLOW_DEPTH": ("red", "SBC fields present but below the paragraph/depth bar"),
        "WEAK_ZONE_A": ("red", "Zone A KEY POINT present but below the depth bar"),
        "UNSOURCED_EXAMPLES": ("red", "Concrete Example carries no source"),
        "UNPARSED_SBC": ("red", "SBC section exists but cannot be parsed"),
        "NO_SBC": ("red", "Missing Slide Body Coverage block"),
        "NO_NOTES": ("red", "Slide has no notes at all"),
        "SKIPPED": ("dim", "Chrome/title slide without substantive body"),
    }

    for st in AUDIT_STATUSES:
        style, desc = status_desc.get(st, ("white", ""))
        cnt = summary.get(st.lower(), 0)
        sum_table.add_row(f"[{style}]{st}[/{style}]", str(cnt), desc)

    console.print(sum_table)

    # Detailed issues table
    issues = [r for r in results if r["status"] != "PASS" and r["status"] != "SKIPPED"]
    if issues:
        console.print(f"\n[bold yellow]Flagged Slides ({len(issues)}):[/bold yellow]")
        detail_table = Table(show_header=True)
        detail_table.add_column("Slide", style="cyan", width=6)
        detail_table.add_column("Status", style="bold", width=14)
        detail_table.add_column("Title", max_width=35)
        detail_table.add_column("Finding / Recommendation")

        for r in issues:
            c = r.get("coverage") or {}
            q = r.get("quality") or {}
            detail = ""
            if c.get("missing", 0) > 0:
                detail += f"Missing {c['missing']} items ({', '.join(c.get('missing_items', [])[:2])}). "
            if q.get("reason"):
                detail += f"Quality: {q['reason']}"
            if not detail:
                detail = r["status"]

            st_color = "yellow" if r["status"] == "GAPS" else "red"
            detail_table.add_row(
                str(r["slide"]),
                f"[{st_color}]{r['status']}[/{st_color}]",
                (r.get("title") or "—")[:35],
                detail[:120],
            )
        console.print(detail_table)
    else:
        print_success("All audited slides passed SBC structural checks!")

    if depth_summary:
        rows = [r for r in results if (r.get("depth") or {}).get("fields_checked")]
        if not rows:
            print_info("Depth roll-up: no SBC fields were parsed, so there is nothing to summarise.")
            return
        console.print()
        depth_table = Table(title="SBC Depth Roll-up", show_header=True)
        depth_table.add_column("Slide", style="cyan", width=6)
        depth_table.add_column("Status")
        depth_table.add_column("Below / checked", justify="right")
        depth_table.add_column("Avg paras", justify="right")
        depth_table.add_column("Below")
        depth_table.add_column("Over")
        depth_table.add_column("Not prose")
        for r in rows:
            d = r["depth"]
            depth_table.add_row(
                str(r["slide"]),
                str(d.get("status", "—")),
                f"{d.get('fields_below', 0)} / {d.get('fields_checked', 0)}",
                str(d.get("average_paragraphs", "—")),
                ", ".join(d.get("below") or []) or "—",
                ", ".join(d.get("over") or []) or "—",
                ", ".join(d.get("not_prose") or []) or "—",
            )
        console.print(depth_table)
