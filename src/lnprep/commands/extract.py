"""
lnprep extract command: Extract notes, visual metadata, and images from PPTX slides.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from lnprep.console import console, print_formatted, print_success
from lnprep.core.pptx_engine import extract_notes, extract_slide_images

app = typer.Typer(help="Extract notes and visual metadata from PPTX slides")


@app.callback(invoke_without_command=True)
def extract_command(
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
        help="Extract single slide (1-indexed)",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Directory to save extracted notes/images",
    ),
    extract_images_flag: bool = typer.Option(
        False,
        "--images",
        "-i",
        help="Extract slide images to disk",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output raw data as JSON",
    ),
) -> None:
    """Extract notes and visual metadata from PPTX slides."""
    out_dir_str = str(output_dir) if output_dir else None

    if extract_images_flag:
        img_res = extract_slide_images(str(pptx_path), output_dir=out_dir_str)
        if as_json:
            print_formatted(img_res, as_json=True)
            return

        print_success(
            f"Extracted {img_res['images_extracted']} image(s) from "
            f"{img_res['slides_with_visuals']} slide(s) → {img_res['output_dir']}"
        )
        return

    slides_data = extract_notes(str(pptx_path), output_dir=out_dir_str, slide_filter=slide)
    data = {"total_slides": len(slides_data), "slides": slides_data}

    if as_json:
        print_formatted(data, as_json=True)
        return

    print_success(f"Extracted presentation data: {data['total_slides']} slide(s)")

    table = Table(title="Slide Extraction Summary", show_header=True)
    table.add_column("Slide", style="cyan", width=6)
    table.add_column("Title", style="bold", max_width=40)
    table.add_column("Notes (Chars)", style="green", justify="right")
    table.add_column("Tables", justify="right")
    table.add_column("Charts", justify="right")
    table.add_column("Images", justify="right")
    table.add_column("SmartArt", justify="right")

    for s in data["slides"]:
        notes_len = len(s.get("speaker_notes", ""))
        v = s.get("visuals", {})
        table.add_row(
            str(s["slide"]),
            (s.get("title") or "—")[:40],
            str(notes_len),
            str(len(v.get("tables", []))),
            str(len(v.get("charts", []))),
            str(len(v.get("images", []))),
            str(len(v.get("smartart", []))),
        )

    console.print(table)
