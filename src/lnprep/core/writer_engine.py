"""
Direct XML slide notes injection engine.
Applies boldface, multi-level indentation, and italics directly into OpenXML.
Guards against PPTX corruption via local copy and automated backup.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pptx import Presentation

from lnprep.core.common import (
    get_slide_notes_text,
    load_format_spec,
    spec_bold_labels,
    spec_font_sizes,
    spec_labels_list,
)

ET.register_namespace('p', 'http://schemas.openxmlformats.org/presentationml/2006/main')
ET.register_namespace('a', 'http://schemas.openxmlformats.org/drawingml/2006/main')
ET.register_namespace('r', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships')

NS = {
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
}

SZ_TIMING = 1100
SZ_HEADER = 1000
SZ_BODY = 1000
SZ_SUB = 900


def _hash_path(path: str) -> str:
    return hashlib.md5(path.encode()).hexdigest()[:6]


def get_tmp_path(pptx_path: str) -> str:
    base = os.path.basename(pptx_path).replace(" ", "_")
    h = _hash_path(pptx_path)
    return f"/tmp/pptx_working_{base}_{h}.pptx"


def get_backup_marker(pptx_path: str) -> str:
    base = os.path.basename(pptx_path).replace(" ", "_")
    h = _hash_path(pptx_path)
    return f"/tmp/pptx_backup_done_{base}_{h}"


def get_unzip_dir(pptx_path: str) -> str:
    base = os.path.basename(pptx_path).replace(" ", "_")
    h = _hash_path(pptx_path)
    return f"/tmp/unzipped_slide_update_{base}_{h}"


def ensure_local_copy(pptx_path: str) -> str:
    """Copy from original location to /tmp working path."""
    tmp = get_tmp_path(pptx_path)
    if not os.path.exists(tmp):
        shutil.copy2(pptx_path, tmp)
    return tmp


def backup_once(pptx_path: str) -> str:
    """Create ONE backup per session, auto-invalidating on modification or >24h."""
    marker = get_backup_marker(pptx_path)
    needs_backup = True
    existing_backup = ""
    if os.path.exists(marker):
        try:
            with open(marker, "r", encoding="utf-8") as f:
                existing_backup = f.read().strip()
            if existing_backup and os.path.exists(existing_backup) and os.path.exists(pptx_path):
                src_mtime = os.path.getmtime(pptx_path)
                b_mtime = os.path.getmtime(existing_backup)
                if (src_mtime <= b_mtime + 2) and (
                    datetime.now() - datetime.fromtimestamp(b_mtime)
                ).total_seconds() < 86400:
                    needs_backup = False
        except Exception:
            needs_backup = True

    if needs_backup:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = pptx_path.replace(".pptx", f"_backup_{ts}.pptx")
        shutil.copy2(pptx_path, backup)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(backup)
        return backup
    return existing_backup


def sync_back(pptx_path: str) -> None:
    """Copy local working file back to target PPTX path."""
    tmp = get_tmp_path(pptx_path)
    shutil.copy2(tmp, pptx_path)


def create_p(space_before_pts: int = 100, level: Optional[int] = None) -> ET.Element:
    """Create a paragraph element with optional bullet level."""
    LEVEL_CONFIG = {
        0: {"marL": "171450", "indent": "-171450", "bullet": "•"},
        1: {"marL": "628650", "indent": "-171450", "bullet": "•"},
    }

    p = ET.Element('{http://schemas.openxmlformats.org/drawingml/2006/main}p')

    if level is not None and level in LEVEL_CONFIG:
        cfg = LEVEL_CONFIG[level]
        pPr = ET.SubElement(
            p,
            '{http://schemas.openxmlformats.org/drawingml/2006/main}pPr',
            indent=cfg["indent"],
            lvl=str(level),
            marL=cfg["marL"],
            marR="0",
            rtl="0",
            algn="l",
        )
        buChar = ET.SubElement(pPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}buChar')
        buChar.set('char', cfg["bullet"])
    else:
        pPr = ET.SubElement(
            p,
            '{http://schemas.openxmlformats.org/drawingml/2006/main}pPr',
            indent="0",
            lvl="0",
            marL="0",
            marR="0",
            rtl="0",
            algn="l",
        )
        ET.SubElement(pPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}buNone')

    spcBef = ET.SubElement(pPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}spcBef')
    ET.SubElement(spcBef, '{http://schemas.openxmlformats.org/drawingml/2006/main}spcPts', val=str(space_before_pts))
    spcAft = ET.SubElement(pPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}spcAft')
    ET.SubElement(spcAft, '{http://schemas.openxmlformats.org/drawingml/2006/main}spcPts', val="0")
    ET.SubElement(p, '{http://schemas.openxmlformats.org/drawingml/2006/main}endParaRPr')
    return p


def add_run(
    p: ET.Element,
    text: str,
    size_pts: int = SZ_BODY,
    bold: bool = False,
    italic: bool = False,
) -> None:
    end_para = p.find('{http://schemas.openxmlformats.org/drawingml/2006/main}endParaRPr')

    r = ET.Element('{http://schemas.openxmlformats.org/drawingml/2006/main}r')
    rPr = ET.SubElement(
        r,
        '{http://schemas.openxmlformats.org/drawingml/2006/main}rPr',
        lang="en-GB",
        sz=str(size_pts),
    )
    if bold:
        rPr.set('b', '1')
    if italic:
        rPr.set('i', '1')

    solidFill = ET.SubElement(rPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}solidFill')
    ET.SubElement(solidFill, '{http://schemas.openxmlformats.org/drawingml/2006/main}schemeClr', val="dk1")

    for tag in ('latin', 'ea', 'cs', 'sym'):
        ET.SubElement(rPr, f'{{http://schemas.openxmlformats.org/drawingml/2006/main}}{tag}', typeface="Arial")

    t = ET.SubElement(r, '{http://schemas.openxmlformats.org/drawingml/2006/main}t')
    t.text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', text)

    if end_para is not None:
        idx = list(p).index(end_para)
        p.insert(idx, r)
    else:
        p.append(r)


def add_text_with_markdown_and_quotes(
    p: ET.Element,
    text: str,
    size_pts: int = SZ_BODY,
    default_bold: bool = False,
    default_italic: bool = False,
) -> None:
    """Parse text with **bold** or quotes and append formatted runs to paragraph p."""
    trimmed = text.strip()
    if (
        (trimmed.startswith('"') and trimmed.endswith('"'))
        or (trimmed.startswith('"') and trimmed.count('"') == 1)
        or (trimmed.endswith('"') and trimmed.count('"') == 1)
        or (default_italic and '"' not in trimmed)
    ):
        add_run(p, text, size_pts=size_pts, bold=default_bold, italic=True)
        return

    if '**' in text:
        parts = text.split('**')
        for idx, part in enumerate(parts):
            if not part:
                continue
            is_b = (idx % 2 == 1) or default_bold
            q_parts = re.split(r'(".*?")', part)
            for qp in q_parts:
                if qp.startswith('"') and qp.endswith('"'):
                    add_run(p, qp, size_pts=size_pts, bold=is_b, italic=True)
                elif qp:
                    add_run(p, qp, size_pts=size_pts, bold=is_b, italic=default_italic)
    else:
        q_parts = re.split(r'(".*?")', text)
        for qp in q_parts:
            if qp.startswith('"') and qp.endswith('"'):
                add_run(p, qp, size_pts=size_pts, bold=default_bold, italic=True)
            elif qp:
                add_run(p, qp, size_pts=size_pts, bold=default_bold, italic=default_italic)


def get_notes_slide_path(unzip_dir: str, slide_num: int) -> Optional[str]:
    rels_path = os.path.join(unzip_dir, 'ppt', 'slides', '_rels', f'slide{slide_num}.xml.rels')
    if not os.path.exists(rels_path):
        return None

    tree = ET.parse(rels_path)
    root = tree.getroot()

    for rel in root.findall('.//rel:Relationship', NS):
        if 'notesSlide' in rel.attrib.get('Type', ''):
            target = rel.attrib.get('Target')
            if target:
                resolved = os.path.normpath(os.path.join(unzip_dir, 'ppt', 'slides', target))
                return resolved
    return None


def zip_dir(dir_path: str, zip_path: str) -> None:
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_ref:
        for root, _, files in os.walk(dir_path):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, dir_path)
                zip_ref.write(full_path, rel_path)


def _inject_notes_into_xml(notes_text: str, xml_path: str, spec: Dict[str, Any], slide_num: int = 1) -> None:
    """Parse notes_text into OpenXML paragraphs and write to xml_path."""
    labels_list = spec_labels_list(spec)
    bold_labels = spec_bold_labels(spec)
    sz = spec_font_sizes(spec)

    tree = ET.parse(xml_path)
    root = tree.getroot()

    body_sp = None
    for sp in root.findall('.//p:sp', NS):
        ph = sp.find('.//p:ph', NS)
        if ph is not None and ph.attrib.get('type') == 'body':
            body_sp = sp
            break

    if body_sp is None:
        raise ValueError(f"Body placeholder shape not found in slide {slide_num} notes XML")

    tx_body = body_sp.find('p:txBody', NS)
    if tx_body is None:
        raise ValueError(f"txBody not found in body shape of slide {slide_num} notes XML")

    for p_el in list(tx_body.findall('a:p', NS)):
        tx_body.remove(p_el)

    parts = notes_text.split("--- LECTURE NOTES ---")
    speaker_part = parts[0].replace("--- SPEAKER NOTES ---", "").strip()
    lecture_part = parts[1].strip() if len(parts) > 1 else ""

    if "--- VISUAL DECONSTRUCTION ---" in speaker_part:
        s_parts = speaker_part.split("--- VISUAL DECONSTRUCTION ---")
        speaker_part = s_parts[0].strip()
        visual_part = s_parts[1].strip()
    else:
        visual_part = ""

    paragraphs_to_add: List[ET.Element] = []

    p_hdr = create_p(space_before_pts=0)
    add_run(p_hdr, "--- SPEAKER NOTES ---", size_pts=sz["header"], bold=True)
    paragraphs_to_add.append(p_hdr)

    speaker_lines = speaker_part.split('\n')
    seen_star = False
    spaced_lines = []
    for _line in speaker_lines:
        _s = _line.strip()
        _is_top_star = _s.startswith('* ')
        _is_opening = (
            _s.startswith('* Opening line:')
            or _s.startswith('* NARRATIVE OPENING')
            or _s.startswith('* OPENING HOOK')
        )
        if _is_top_star and seen_star and not _is_opening:
            if spaced_lines and spaced_lines[-1].strip() != '':
                spaced_lines.append('')
        if _is_top_star:
            seen_star = True
        spaced_lines.append(_line)
    speaker_lines = spaced_lines

    last_was_empty = False
    in_quote = False
    for line in speaker_lines:
        line_str = line.strip()
        if not line_str:
            if not last_was_empty:
                paragraphs_to_add.append(create_p(space_before_pts=0))
                last_was_empty = True
            continue

        last_was_empty = False
        is_tg_sub = any(
            line_str.startswith(x)
            for x in ('Expected:', 'Guidance:', 'Assessment Link:', 'Key Insight:')
        ) or any(
            line_str.startswith(f"- {x}")
            for x in ('Expected:', 'Guidance:', 'Assessment Link:', 'Key Insight:')
        )
        is_sub_bullet = line_str.startswith('-')
        is_indented_zone_a = any(
            line_str.startswith(x)
            for x in ('COMMON STUDENT MISCONCEPTION', 'ACTIVITY', '* COMMON STUDENT MISCONCEPTION', '* ACTIVITY')
        ) or is_tg_sub
        para_level = 1 if (is_sub_bullet or is_indented_zone_a) else 0

        if line_str.startswith('⏱'):
            p = create_p(space_before_pts=100, level=None)
            add_run(p, line_str, size_pts=sz["timing"], bold=True)
        else:
            p = create_p(space_before_pts=30 if para_level == 1 else 100, level=para_level)

        if line_str.startswith('⏱'):
            pass
        elif line_str.startswith('*'):
            escaped_bold = '|'.join(re.escape(l) for l in bold_labels)
            pat = (
                rf'^(\*\s*(?:BRIDGE|KEY POINT|NARRATIVE OPENING[^\:]*|OPENING HOOK[^\:]*|Opening line|'
                rf'SOCRATIC PROMPT[^\:]*|COLD CALL[^\:]*|COMMON STUDENT MISCONCEPTION[^\:]*|'
                rf'ACTIVITY[^\:]*|TEACHER GUIDANCE[^\:]*|TRANSITION|VIDEO CUE[^\:]*|'
                rf'SCRIPTED EXPLANATION[^\:]*|🎥[^\:]*|{escaped_bold}[^\:]*):?\s*)(.*)$'
            )
            m = re.match(pat, line_str, re.IGNORECASE)
            if m:
                lbl, rest = m.group(1), m.group(2)
                bold_lbl = not lbl.startswith('* Opening line')
                add_run(p, lbl, size_pts=sz["header"], bold=bold_lbl)
                if rest:
                    add_text_with_markdown_and_quotes(p, rest, size_pts=sz["body"])
            else:
                add_text_with_markdown_and_quotes(p, line_str, size_pts=sz["body"])
        elif line_str.startswith('-') or is_tg_sub:
            m_sub = re.match(r'^(-?\s*(?:Expected|Guidance|Assessment Link|Key Insight):?\s*)(.*)$', line_str, re.IGNORECASE)
            if m_sub:
                lbl, rest = m_sub.group(1), m_sub.group(2)
                clean_lbl = re.sub(r'^-\s*', '', lbl).strip() + ' '
                add_run(p, clean_lbl, size_pts=sz["sub"], bold=True)
                if rest:
                    add_text_with_markdown_and_quotes(p, rest, size_pts=sz["sub"])
            else:
                clean_line = re.sub(r'^-\s*', '', line_str).strip()
                add_text_with_markdown_and_quotes(p, clean_line, size_pts=sz["sub"])
        else:
            escaped_bold = '|'.join(re.escape(l) for l in bold_labels)
            pat_unb = (
                rf'^((?:BRIDGE|KEY POINT|NARRATIVE OPENING[^\:]*|OPENING HOOK[^\:]*|Opening line|'
                rf'SOCRATIC PROMPT[^\:]*|COLD CALL[^\:]*|COMMON STUDENT MISCONCEPTION[^\:]*|'
                rf'ACTIVITY[^\:]*|TEACHER GUIDANCE[^\:]*|TRANSITION|VIDEO CUE[^\:]*|'
                rf'SCRIPTED EXPLANATION[^\:]*|🎥[^\:]*|{escaped_bold}[^\:]*):?\s*)(.*)$'
            )
            m_unb = re.match(pat_unb, line_str, re.IGNORECASE)
            if m_unb:
                lbl, rest = m_unb.group(1), m_unb.group(2)
                bold_lbl = not lbl.startswith('Opening line')
                add_run(p, lbl, size_pts=sz["header"], bold=bold_lbl)
                if rest:
                    add_text_with_markdown_and_quotes(p, rest, size_pts=sz["body"])
                    if rest.count('"') % 2 == 1:
                        in_quote = not in_quote
            else:
                is_bold_label = any(line_str.startswith(lbl) for lbl in bold_labels)
                if is_bold_label:
                    add_run(p, line_str, size_pts=sz["header"], bold=True)
                else:
                    add_text_with_markdown_and_quotes(p, line_str, size_pts=sz["body"], default_italic=in_quote)
                    if line_str.count('"') % 2 == 1:
                        in_quote = not in_quote
        paragraphs_to_add.append(p)

    if visual_part:
        paragraphs_to_add.append(create_p(space_before_pts=0))
        p_vd_hdr = create_p(space_before_pts=100)
        add_run(p_vd_hdr, "--- VISUAL DECONSTRUCTION ---", size_pts=sz["header"], bold=True)
        paragraphs_to_add.append(p_vd_hdr)

        visual_lines = visual_part.split('\n')
        last_was_empty = False
        in_quote = False
        for line in visual_lines:
            line_str = line.strip()
            if not line_str:
                if not last_was_empty:
                    paragraphs_to_add.append(create_p(space_before_pts=0))
                    last_was_empty = True
                continue

            last_was_empty = False
            is_step_bullet = line_str.startswith('-') or bool(re.match(r'^(?:-\s*)?Step\s*\d', line_str, re.IGNORECASE))
            para_level = 1 if is_step_bullet else 0

            p = create_p(space_before_pts=30 if para_level == 1 else 100, level=para_level)

            escaped_bold = '|'.join(re.escape(l) for l in bold_labels)
            pat_vd = (
                rf'^((?:🎯\s*VISUAL OBJECTIVE|👁️\s*GAZE DIRECTION[^\:]*|🔄\s*STEP-BY-STEP WALK-THROUGH|'
                rf'💡\s*VISUAL PUNCHLINE|VISUAL OBJECTIVE|GAZE DIRECTION[^\:]*|STEP-BY-STEP WALK-THROUGH|'
                rf'VISUAL PUNCHLINE|{escaped_bold}[^\:]*):?\s*)(.*)$'
            )
            m_vd = re.match(pat_vd, line_str, re.IGNORECASE)
            if m_vd:
                lbl, rest = m_vd.group(1), m_vd.group(2)
                add_run(p, lbl, size_pts=sz["header"], bold=True)
                if rest:
                    add_text_with_markdown_and_quotes(p, rest, size_pts=sz["body"])
            elif is_step_bullet:
                clean_line = re.sub(r'^-\s*', '', line_str).strip()
                m_step = re.match(r'^(Step\s*\d+[^:]*:\s*)(.*)$', clean_line, re.IGNORECASE)
                if m_step:
                    add_run(p, m_step.group(1), size_pts=sz["sub"], bold=True)
                    if m_step.group(2):
                        add_text_with_markdown_and_quotes(p, m_step.group(2), size_pts=sz["sub"])
                else:
                    add_text_with_markdown_and_quotes(p, clean_line, size_pts=sz["sub"])
            else:
                add_text_with_markdown_and_quotes(p, line_str, size_pts=sz["body"], default_italic=in_quote)
            paragraphs_to_add.append(p)

    if lecture_part:
        paragraphs_to_add.append(create_p(space_before_pts=0))
        p_ln_hdr = create_p(space_before_pts=100)
        add_run(p_ln_hdr, "--- LECTURE NOTES ---", size_pts=sz["header"], bold=True)
        paragraphs_to_add.append(p_ln_hdr)

        lecture_lines = lecture_part.split('\n')
        in_coverage = False
        curr_sbc_field = None
        for line in lecture_lines:
            line_str = line.strip()
            if line_str == '**':
                continue
            if line_str in ('Recommended Videos: **', '**Recommended Videos:**'):
                line_str = 'Recommended Videos:'

            if not line_str:
                paragraphs_to_add.append(create_p(space_before_pts=0))
                continue

            if 'SLIDE BODY COVERAGE' in line_str.upper():
                in_coverage = True
                curr_sbc_field = None
                p = create_p(space_before_pts=100, level=None)
                add_run(p, line_str.upper(), size_pts=sz["header"], bold=True)
                paragraphs_to_add.append(p)
                continue

            if not in_coverage:
                p = create_p(space_before_pts=60, level=None)
                if re.match(r'^[\u2022]\s*[A-Z][A-Z0-9 /&\'\-()]*:?\s*$', line_str):
                    add_run(p, line_str, size_pts=sz["header"], bold=True)
                    paragraphs_to_add.append(p)
                    continue
                m = re.match(r'^(Framing|Visual|Case|Insight|Activity Flow|Teacher Guidance|\uf0e0[^\:]+):?\s*(.*)$', line_str)
                if m:
                    lbl, rest = m.group(1), m.group(2)
                    if not lbl.endswith(':'):
                        lbl += ':'
                    add_run(p, lbl + (' ' if not rest.startswith(' ') else ''), size_pts=sz["sub"], bold=True)
                    if rest:
                        add_text_with_markdown_and_quotes(p, rest, size_pts=sz["sub"])
                else:
                    add_text_with_markdown_and_quotes(p, line_str, size_pts=sz["sub"])
                paragraphs_to_add.append(p)
            else:
                escaped_labels = [re.escape(l) for l in labels_list]
                split_pat = r'(\s*(?:' + '|'.join(escaped_labels) + r'))'
                chunks = re.split(split_pat, line_str)

                recombined = []
                curr = ''
                for c in chunks:
                    if any(c.strip().startswith(l) for l in labels_list):
                        if curr.strip():
                            recombined.append(curr.strip())
                        curr = c
                    else:
                        curr += c
                if curr.strip():
                    recombined.append(curr.strip())

                for chunk in recombined:
                    matching_lbl = None
                    for l in labels_list:
                        if chunk.startswith(l):
                            matching_lbl = l
                            break

                    if matching_lbl:
                        lbl = matching_lbl
                        curr_sbc_field = lbl.strip().strip(':')
                        rest = chunk[len(lbl):]
                        level = 1 if lbl not in ['Recommended Videos:', 'Academic and Industry References:'] else 0
                        p = create_p(space_before_pts=30, level=level)
                        add_run(p, lbl + (' ' if not rest.startswith(' ') else ''), size_pts=sz["sub"], bold=True)
                        if rest:
                            add_text_with_markdown_and_quotes(p, rest, size_pts=sz["sub"])
                    else:
                        if (
                            chunk.startswith('Why?') or chunk.startswith('Why avoid') or
                            chunk.startswith('Why do') or chunk.startswith('To understand why') or
                            chunk.startswith('Source:') or chunk.startswith('Sources:') or
                            chunk.startswith('Incoterms (') or
                            chunk.startswith('Key citations') or chunk.startswith('Teaching note:')
                        ):
                            p = create_p(space_before_pts=30, level=1)
                            add_text_with_markdown_and_quotes(p, chunk, size_pts=sz["sub"])
                        elif curr_sbc_field in [
                            'Plain English', 'Deep Research', 'Concrete Example',
                            'Bigger Picture', 'Assessment Link', "Manager's So What"
                        ] and not (
                            chunk.startswith('*') or chunk.startswith('•') or
                            chunk.startswith('- Classical Foundation:') or
                            chunk.startswith('- Contemporary Frontier')
                        ):
                            p = create_p(space_before_pts=30, level=1)
                            add_text_with_markdown_and_quotes(p, chunk, size_pts=sz["sub"])
                        else:
                            curr_sbc_field = None
                            p = create_p(space_before_pts=60, level=0)
                            m_top = re.match(r'^([^:\n]+:)(.*)$', chunk)
                            if m_top and not chunk.startswith('http') and not chunk.startswith('URL:'):
                                top_hdr, top_rest = m_top.group(1), m_top.group(2)
                                add_run(p, top_hdr, size_pts=sz["sub"], bold=True)
                                if top_rest:
                                    add_text_with_markdown_and_quotes(p, top_rest, size_pts=sz["sub"])
                            else:
                                add_text_with_markdown_and_quotes(p, chunk, size_pts=sz["sub"])
                    paragraphs_to_add.append(p)

    for p_node in paragraphs_to_add:
        tx_body.append(p_node)

    tree.write(xml_path, xml_declaration=True, encoding='utf-8')


def batch_update_notes(
    pptx_path: str,
    entries: Sequence[Tuple[int, str]],
    spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update notes on multiple slides in a single unzip-modify-repack pass."""
    if not entries:
        return {"updated": 0, "slides": []}

    tmp_path = get_tmp_path(pptx_path)
    if not os.path.exists(tmp_path):
        ensure_local_copy(pptx_path)

    unzip_dir = get_unzip_dir(pptx_path)
    spec = spec or load_format_spec(pptx_path)[0]

    prs = Presentation(tmp_path)
    num_slides = len(prs.slides)
    needs_save = False

    for slide_num, _ in entries:
        if slide_num < 1 or slide_num > num_slides:
            raise ValueError(f"Slide {slide_num} is out of range (1..{num_slides})")
        slide = prs.slides[slide_num - 1]
        if not slide.has_notes_slide:
            _ = slide.notes_slide
            needs_save = True

    if needs_save:
        prs.save(tmp_path)

    if os.path.exists(unzip_dir):
        shutil.rmtree(unzip_dir)
    os.makedirs(unzip_dir)

    tmp_zipped = tmp_path + ".zip"
    written_slides: List[Dict[str, Any]] = []
    try:
        with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
            zip_ref.extractall(unzip_dir)

        for slide_num, notes_text in entries:
            xml_path = get_notes_slide_path(unzip_dir, slide_num)
            if xml_path is None or not os.path.exists(xml_path):
                raise FileNotFoundError(f"Could not locate notes slide XML for slide {slide_num}")
            _inject_notes_into_xml(notes_text, xml_path, spec, slide_num=slide_num)
            written_slides.append({"slide": slide_num, "chars": len(notes_text)})

        if os.path.exists(tmp_zipped):
            os.remove(tmp_zipped)
        zip_dir(unzip_dir, tmp_zipped)
        shutil.copy2(tmp_zipped, tmp_path)
    finally:
        if os.path.exists(tmp_zipped):
            try:
                os.remove(tmp_zipped)
            except OSError:
                pass
        if os.path.exists(unzip_dir):
            shutil.rmtree(unzip_dir, ignore_errors=True)

    prs = Presentation(tmp_path)
    verification_checks: List[Dict[str, Any]] = []
    for slide_num, raw_notes in entries:
        s = prs.slides[slide_num - 1]
        written = get_slide_notes_text(s)
        checks = ["⏱", "--- LECTURE NOTES ---", "--- SPEAKER NOTES ---"]
        if "--- VISUAL DECONSTRUCTION ---" in raw_notes:
            checks.append("--- VISUAL DECONSTRUCTION ---")
        item_checks = {c: (c in written) for c in checks}
        verification_checks.append({"slide": slide_num, "checks": item_checks})

    return {
        "updated": len(written_slides),
        "slides": written_slides,
        "verification": verification_checks,
    }


def update_slide(
    pptx_path: str,
    slide_num: int,
    notes_text: str,
    spec: Optional[Dict[str, Any]] = None,
    sync: bool = True,
) -> Dict[str, Any]:
    """Update single slide notes using Direct XML Notes Injection."""
    res = batch_update_notes(pptx_path, [(slide_num, notes_text)], spec=spec)
    if sync:
        sync_back(pptx_path)
    return res


def load_notes_payload(path_or_str: str) -> Dict[str, Any]:
    """Load notes payload from file path or JSON string."""
    text = path_or_str
    if os.path.exists(path_or_str):
        with open(path_or_str, "r", encoding="utf-8") as f:
            text = f.read()

    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    attempts = [stripped, text]
    lo, hi = stripped.find("{"), stripped.rfind("}")
    if lo != -1 and hi > lo:
        attempts.append(stripped[lo:hi + 1])

    last_err = None
    for candidate in attempts:
        try:
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError as e:
            last_err = e

    raise ValueError(f"Payload is not valid JSON: {last_err}")
