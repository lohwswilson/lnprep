"""
lnprep brief command: Assemble review brief for independent reviewer subagent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from lnprep.console import console, print_formatted, print_success
from lnprep.core.brief_builder import build_brief

app = typer.Typer(help="Assemble review brief for independent reviewer subagent")


@app.callback(invoke_without_command=True)
def brief_command(
    ctx: typer.Context,
    pptx_path: Path = typer.Argument(
        ...,
        help="Path to PPTX file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        "-o",
        help="Write brief to markdown file (default: stdout)",
    ),
    slides: Optional[str] = typer.Option(
        None,
        "--slides",
        "-s",
        help="Slide subset, e.g. '1-15' or '1,4,9'",
    ),
    skip_images: bool = typer.Option(
        False,
        "--skip-images",
        help="Skip image extraction from slides",
    ),
    visual_verify: bool = typer.Option(
        False,
        "--visual-verify",
        help="Include vision-model checks",
    ),
    flagged_only: bool = typer.Option(
        False,
        "--flagged-only",
        help="Compress brief: full note text only for slides L1 flagged",
    ),
    citation_ttl_days: int = typer.Option(
        180,
        "--citation-ttl-days",
        help="TTL for citation cache in days",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output brief statistics as JSON",
    ),
) -> None:
    """Assemble a comprehensive review brief for an independent reviewer subagent."""
    out_str = str(out) if out else None
    text, stats = build_brief(
        str(pptx_path),
        out_path=out_str,
        slides=slides,
        skip_images=skip_images,
        visual_verify=visual_verify,
        flagged_only=flagged_only,
        citation_ttl_days=citation_ttl_days,
    )

    if as_json:
        print_formatted({"stats": stats, "text": text if not out else None}, as_json=True)
        return

    if out:
        print_success(f"Review brief written → {stats.get('out')}")
        console.print(
            f"   {stats.get('chars', 0):,} chars | {stats.get('slides', 0)} slide(s) | "
            f"L1 flagged: {stats.get('l1_flagged', 0)} | Images: {stats.get('images', 0)}"
        )
        console.print("\n[dim]Spawn the reviewer with this brief as its complete context.[/dim]")
    else:
        console.print(text)
