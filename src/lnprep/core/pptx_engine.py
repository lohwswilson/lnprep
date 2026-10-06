"""
PowerPoint extraction engine.
Extracts slide speaker notes, body text, tables, charts, images, SmartArt, and shapes.
"""

from __future__ import annotations

import io
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from lnprep.core.common import (
    extract_slide_body_text,
    get_slide_notes_text,
    get_slide_title,
)


def extract_table_content(shape: Any) -> Optional[Dict[str, Any]]:
    """Extract content from a table shape."""
    if not getattr(shape, "has_table", False):
        return None

    table = shape.table
    rows_data = []

    for row_idx, row in enumerate(table.rows):
        cells = [cell.text.strip() for cell in row.cells]
        rows_data.append({
            "row": row_idx + 1,
            "cells": cells,
        })

    return {
        "rows": len(table.rows),
        "columns": len(table.columns),
        "data": rows_data,
    }


def extract_smartart_text(slide: Any) -> List[str]:
    """Extract text from SmartArt/diagram data parts."""
    diagram_texts: List[str] = []
    try:
        for rel in slide.part.rels.values():
            if "diagram" in rel.reltype and "data" in getattr(rel, "target_ref", ""):
                part = rel.target_part
                xml_content = part.blob
                root = ET.fromstring(xml_content)
                for elem in root.iter():
                    if elem.tag.endswith("}t") and elem.text and elem.text.strip():
                        diagram_texts.append(elem.text.strip())
    except Exception:
        pass
    return diagram_texts


def extract_chart_info(shape: Any) -> Optional[Dict[str, Any]]:
    """Extract information from a chart shape."""
    if shape.shape_type != MSO_SHAPE_TYPE.CHART:
        return None

    try:
        chart = shape.chart
        info: Dict[str, Any] = {
            "chart_type": str(chart.chart_type),
            "has_title": bool(chart.has_title),
        }

        try:
            series_names = []
            for series in chart.series:
                series_names.append(series.name if series.name else f"Series {len(series_names) + 1}")
            info["series"] = series_names
        except Exception:
            info["series"] = []

        try:
            if chart.plots and chart.plots[0].categories:
                cats = [str(c) for c in chart.plots[0].categories]
                info["categories"] = cats[:10]
        except Exception:
            info["categories"] = []

        return info
    except Exception as e:
        return {"chart_type": f"(error: {e})", "has_title": False}


def extract_image_info(
    shape: Any,
    slide_num: int,
    output_dir: Optional[str] = None,
    counter: int = 1,
) -> Optional[Dict[str, Any]]:
    """Extract information about an embedded image."""
    if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
        return None

    try:
        image = shape.image
        ext = image.content_type.split("/")[-1]
        if ext == "jpeg":
            ext = "jpg"
        elif ext not in ("png", "jpg", "gif", "bmp"):
            ext = "png"

        from PIL import Image

        img = Image.open(io.BytesIO(image.blob))
        width, height = img.size

        filepath = None
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            filename = f"slide{slide_num:02d}_img{counter:02d}.{ext}"
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "wb") as f:
                f.write(image.blob)

        info = {
            "type": "image",
            "file": filepath,
            "dimensions": f"{width}x{height}",
            "size_bytes": len(image.blob),
            "content_type": image.content_type,
        }
        alt = shape_alt_text(shape)
        if alt:
            # Alt text is frequently the only machine-readable description of a
            # diagram, and was never read at all.
            info["alt_text"] = alt
        return info
    except Exception as e:
        return {"type": "image", "error": str(e)}


def extract_slide_visuals(
    slide: Any,
    slide_num: int = 1,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract all visual elements from a slide: tables, charts, images, SmartArt, groups."""
    visuals: Dict[str, List[Any]] = {
        "tables": [],
        "charts": [],
        "images": [],
        "smartart": [],
        "groups": [],
        "other_shapes": [],
    }

    img_counter = 0

    def process_shape(shape: Any, depth: int = 0) -> Optional[Dict[str, Any]]:
        nonlocal img_counter

        if getattr(shape, "has_table", False):
            table_data = extract_table_content(shape)
            if table_data:
                visuals["tables"].append(table_data)

        if shape.shape_type == MSO_SHAPE_TYPE.CHART:
            chart_info = extract_chart_info(shape)
            if chart_info:
                visuals["charts"].append(chart_info)

        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            img_counter += 1
            img_info = extract_image_info(shape, slide_num, output_dir, img_counter)
            if img_info:
                visuals["images"].append(img_info)

        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            group_info: Dict[str, Any] = {
                "name": shape.name,
                "children_count": len(shape.shapes),
                "children": [],
            }
            for child in shape.shapes:
                child_info = process_shape(child, depth + 1)
                if child_info:
                    group_info["children"].append(child_info)
            visuals["groups"].append(group_info)

        try:
            if shape.is_placeholder:
                return {
                    "type": "placeholder",
                    "name": shape.name,
                    "idx": shape.placeholder_format.idx,
                }
        except (ValueError, AttributeError):
            pass

        return None

    for shape in slide.shapes:
        process_shape(shape)

    smartart_texts = extract_smartart_text(slide)
    if smartart_texts:
        visuals["smartart"] = smartart_texts

    return visuals


def shape_alt_text(shape: Any) -> str:
    """The shape's alt text (descr), which is often the only description of a picture."""
    element = getattr(shape, "_element", None)
    if element is None:
        return ""
    try:
        for node in element.iter():
            if node.tag.endswith("}cNvPr"):
                return (node.get("descr") or "").strip()
    except (AttributeError, TypeError):
        pass
    return ""


def extract_slide_context(slide: Any, slide_num: int) -> Dict[str, Any]:
    """Extract all context needed for prompt generation from a slide."""
    title = get_slide_title(slide)
    body_text = extract_slide_body_text(slide)
    existing_notes = get_slide_notes_text(slide)

    visuals: List[Dict[str, Any]] = []
    # Walk into groups. This used to iterate slide.shapes only, so a table or chart
    # nested in a group was invisible to prompt generation — even though the audit
    # engine's own walker sees it — and a group contributed nothing but its name.
    for shape in _walk_shapes(slide.shapes):
        try:
            if getattr(shape, "has_table", False):
                t = extract_table_content(shape)
                if t:
                    visuals.append({
                        "type": "table", "rows": t["rows"],
                        "columns": t["columns"], "data": t["data"],
                    })
            elif shape.shape_type == MSO_SHAPE_TYPE.CHART:
                c = extract_chart_info(shape)
                if c:
                    visuals.append({"type": "chart", **c})
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                entry: Dict[str, Any] = {"type": "image"}
                alt = shape_alt_text(shape)
                if alt:
                    entry["alt_text"] = alt
                visuals.append(entry)
        except Exception:
            continue

    return {
        "slide": slide_num,
        "title": title,
        "body_text": body_text,
        "existing_notes": existing_notes,
        "has_existing_notes": bool(existing_notes),
        "visuals": visuals,
    }


def extract_notes(
    pptx_path: str,
    output_dir: Optional[str] = None,
    slide_filter: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Extract all slides and content from a PPTX file."""
    if not os.path.exists(pptx_path):
        raise FileNotFoundError(f"Presentation not found: {pptx_path}")

    prs = Presentation(pptx_path)
    slides_data: List[Dict[str, Any]] = []

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    for i, slide in enumerate(prs.slides):
        slide_num = i + 1

        if slide_filter and slide_num != slide_filter:
            continue

        title = slide.shapes.title.text.strip() if getattr(slide.shapes, "title", None) else ""
        body_text = extract_slide_body_text(slide)
        notes = get_slide_notes_text(slide)
        visuals = extract_slide_visuals(slide, slide_num, output_dir)

        slides_data.append({
            "slide": slide_num,
            "title": title,
            "body_text": body_text,
            "notes": notes,
            "has_notes": bool(notes),
            "notes_length": len(notes),
            "visuals": visuals,
        })

    return slides_data


def _walk_shapes(shapes: Any) -> Any:
    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            try:
                yield from _walk_shapes(shape.shapes)
            except (AttributeError, ValueError):
                continue


def _slide_has_smartart(slide: Any) -> bool:
    try:
        for rel in slide.part.rels.values():
            if "diagram" in rel.reltype:
                return True
    except Exception:
        pass
    return False


def extract_slide_images(
    pptx_path: str,
    slide_num: Optional[Any] = None,
    output_dir: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Extract visuals from a PPTX deck to PNG files."""
    if output_dir is None:
        base = os.path.basename(pptx_path).replace(".pptx", "").replace(" ", "_")
        output_dir = f"/tmp/{base}_images"
    os.makedirs(output_dir, exist_ok=True)

    prs = Presentation(pptx_path)
    total = len(prs.slides)

    if slide_num is not None:
        if isinstance(slide_num, (list, tuple, set)):
            indices = [n - 1 for n in sorted(slide_num) if 1 <= n <= total]
        else:
            if not 1 <= slide_num <= total:
                raise ValueError(f"slide {slide_num} out of range (deck has {total} slides)")
            indices = [slide_num - 1]
    else:
        indices = list(range(total))

    from PIL import Image

    manifest: Dict[str, Any] = {
        "deck": os.path.basename(pptx_path),
        "deck_path": os.path.abspath(pptx_path),
        "output_dir": output_dir,
        "total_slides": total,
        "slides": [],
    }

    for idx in indices:
        slide = prs.slides[idx]
        num = idx + 1
        try:
            title = slide.shapes.title.text.strip() if getattr(slide.shapes, "title", None) else ""
        except Exception:
            title = ""

        visuals = []
        img_k = 0

        for shape in _walk_shapes(slide.shapes):
            st = shape.shape_type

            if st == MSO_SHAPE_TYPE.PICTURE:
                try:
                    image = shape.image
                    ext = (image.content_type or "image/png").split("/")[-1].lower()
                    ext = {"jpeg": "jpg"}.get(ext, ext)
                    if ext not in ("png", "jpg", "gif", "bmp"):
                        ext = "png"
                    img_k += 1
                    filename = f"slide{num:02d}_img{img_k:02d}.{ext}"
                    filepath = os.path.join(output_dir, filename)
                    with open(filepath, "wb") as f:
                        f.write(image.blob)
                    try:
                        dim = Image.open(io.BytesIO(image.blob)).size
                        size = f"{dim[0]}x{dim[1]}"
                    except Exception:
                        size = "?"
                    entry = {
                        "type": "image",
                        "file": filename,
                        "path": filepath,
                        "size": size,
                        "bytes": len(image.blob),
                    }
                    alt = shape_alt_text(shape)
                    if alt:
                        # Carried into the review brief too: alt text is often the
                        # only machine-readable description of a diagram.
                        entry["alt_text"] = alt
                    visuals.append(entry)
                except Exception as exc:
                    visuals.append({
                        "type": "image",
                        "file": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    })

            elif st == MSO_SHAPE_TYPE.CHART:
                try:
                    chart = shape.chart
                    visuals.append({
                        "type": "chart",
                        "file": None,
                        "chart_type": str(chart.chart_type),
                        "has_title": bool(chart.has_title),
                    })
                except Exception as exc:
                    visuals.append({
                        "type": "chart",
                        "file": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    })

        if _slide_has_smartart(slide):
            visuals.append({
                "type": "smartart",
                "file": None,
                "note": "SmartArt present; not renderable to PNG from python-pptx",
            })

        manifest["slides"].append({
            "slide": num,
            "title": title,
            "image_count": sum(1 for v in visuals if v["type"] == "image"),
            "visuals": visuals,
        })

    manifest["slides_with_visuals"] = sum(1 for s in manifest["slides"] if s["visuals"])
    manifest["images_extracted"] = sum(s["image_count"] for s in manifest["slides"])
    return manifest
