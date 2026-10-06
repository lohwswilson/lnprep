"""
Slide Body Coverage (SBC) audit engine.
Performs 5-pass auditing:
1. Coverage (body items represented in lecture notes)
2. Semantic alignment (Jaccard similarity + overlap count)
3. Quality (SBC 6-element structure)
4. Multi-paragraph depth (Zone A key point and SBC field paragraph count)
5. Formatting & engagement cadence (online delivery monologue limits)
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from lnprep.config import DEFAULT_ALIGNMENT_THRESHOLD, DEFAULT_MIN_OVERLAP
from lnprep.core.common import (
    DEFAULT_FORMAT_SPEC,
    PARAGRAPH_RULES,
    ZONE_LECTURE,
    ZONE_SPEAKER,
    ZONE_VISUAL,
    get_slide_notes_text,
    get_slide_title,
    has_visual_content,
    load_format_spec,
    normalise_newlines,
    zone_index,
)
from lnprep.core.ref_verifier import check_example_sourcing

STOPWORDS = {
    'a', 'an', 'the', 'and', 'or', 'but', 'if', 'then', 'this', 'that',
    'these', 'those', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should',
    'could', 'can', 'may', 'might', 'must', 'shall', 'to', 'of', 'in',
    'on', 'at', 'by', 'for', 'with', 'about', 'as', 'from', 'into', 'over',
    'after', 'before', 'between', 'under', 'above', 'up', 'down', 'out',
    'off', 'through', 'during', 'supplier', 'suppliers', 'supply', 'chain',
    'chains', 'slide', 'note', 'notes', 'lecture', 'speaker', 'section',
    'point', 'body', 'coverage', 'item', 'items', 'page', 'figure',
    'example', 'examples', 'case', 'study', 'analysis', 'framework',
    'concept', 'insight', 'transition', 'activity', 'discussion',
    'students', 'class', 'classroom', 'ask', 'expected', 'guidance',
    'use', 'using', 'used', 'based', 'within', 'including', 'also',
    'more', 'most', 'some', 'such', 'than', 'each', 'all',
    'any', 'both', 'either', 'neither', 'every', 'one', 'two', 'three',
    'first', 'second', 'third', 'new', 'old', 'high', 'low', 'long',
    'short', 'large', 'small', 'great', 'less', 'much', 'many', 'few',
    'single', 'total', 'overall', 'main', 'key', 'core',
    'while', 'where', 'when', 'what', 'why', 'how', 'who', 'which',
    'their', 'there', 'these', 'they', 'them', 'its', 'his', 'her',
    'our', 'your', 'my', 'we', 'us', 'he', 'she', 'it',
    'true', 'false', 'yes', 'no', 'ok', 'okay', 'etc', 'eg', 'ie',
    'vs', 'via', 'per', 'among', 'since', 'though', 'although',
    'plus', 'minus', 'just', 'only', 'still', 'very', 'really',
    'now', 'then', 'here', 'today', 'never', 'always', 'often',
    '2024', '2025', '2026', '2023', '2022', '2021', '2020',
    'business', 'firm', 'companies', 'company', 'industry', 'market',
    'markets', 'global', 'process', 'processes', 'system', 'systems',
    'strategy', 'strategic', 'management', 'operations', 'operational',
    'order', 'orders', 'cost', 'costs', 'price', 'prices', 'value',
    'risk', 'risks', 'quality', 'time', 'times', 'need', 'needs',
}

SBC_QUALITY_MARKERS = [
    ("definition", r'(?i)(?:is|means|refers to|defined as|describes)'),
    ("research_context", r'(?i)(?:\b(?:19|20)\d{2}\b|et al\.?|journal|paper|study|research)'),
    ("concrete_example", r'(?i)(?:for example|think of|imagine|consider|such as|e\.g\.|like the)'),
    ("bigger_picture", r'(?i)(?:strategically|why.*matter|consequence|implication|if.*wrong|critical)'),
    ("assessment_link", r'(?i)(?:assignment|exam|report|question|apply|calculate|analyse)'),
    ("so_what", r'(?i)(?:so what|manager.*should|leader.*do|actionable|takeaway|bottom line)'),
]

CHROME_PATTERNS = (
    r'@',
    r'^https?://|^www\.',
    r'^(name|e-?mail|tel|telephone|phone|contact)\s*:',
    r'^module\s+(number|title|code|information|leader|tutor|descriptor)\b',
    r'^(in-?class\s+)?(quiz|poll|vote|survey)\b',
    r'^\d+\s*(min|mins|minutes|hr|hrs|hours?)$',
)

_CHROME_RE = re.compile("|".join(CHROME_PATTERNS), re.IGNORECASE)
_BULLET_LINE = re.compile(r"(?m)^\s*(?:[-•·▪◦]|\*(?!\*)|\d{1,2}[.)])\s+\S")
TIMING_RE = re.compile(r'⏱\s*([\d.]+)\s*min', re.I)

ENGAGEMENT_MARKERS = (
    ("activity", re.compile(r'ACTIVITY\s*[\(:]', re.I)),
    ("socratic", re.compile(r'SOCRATIC PROMPT|COLD CALL', re.I)),
    ("quiz_poll_chat", re.compile(r'\bquiz\b|\bpoll\b|\bchat\b|type your|type the|waterfall|menti|slido', re.I)),
    ("teacher_guidance", re.compile(r'TEACHER GUIDANCE', re.I)),
)

CHAT_POLL_RE = re.compile(r'\bpoll\b|\bchat\b|type your|type the|chat waterfall|menti|slido|three words|3 words', re.I)
BREAKOUT_RE = re.compile(r'breakout|break-out|in groups of|group[s]? of \d|small groups|breakout rooms', re.I)
DELIVERABLE_RE = re.compile(
    r'report back|report-back|deliverable|nominate|reporter|share back|share-back|'
    r'one-line|one liner|present back|feed back|feedback back', re.I)


def is_chrome(text: str) -> bool:
    """True when a body item is administrative or UI chrome."""
    return bool(_CHROME_RE.search(text.strip()))


def split_speaker_and_lecture(text: str, speaker_first: bool = True) -> Tuple[str, str]:
    """Split notes text into (speaker_text, lecture_text).

    Markers are matched case-insensitively, on the first occurrence only, and the
    text is newline-normalised first. A case-sensitive `in`/`split` meant a deck
    using lowercase markers put the whole text in the speaker half and produced
    NO_SBC for every slide, with nothing said about why.
    """
    text = normalise_newlines(text)
    sp_at = zone_index(text, ZONE_SPEAKER)
    le_at = zone_index(text, ZONE_LECTURE)

    if le_at >= 0 and sp_at >= 0 and not speaker_first:
        speaker_part = text[sp_at + len(ZONE_SPEAKER):]
        lecture_part = text[:sp_at]
    elif le_at >= 0:
        speaker_part = text[:le_at]
        lecture_part = text[le_at + len(ZONE_LECTURE):]
    else:
        speaker_part, lecture_part = text, ""

    vd_at = zone_index(speaker_part, ZONE_VISUAL)
    if vd_at >= 0:
        speaker_part = speaker_part[:vd_at]

    return speaker_part, lecture_part


def extract_sbc_block(lecture_text: str) -> str:
    """Extract Slide Body Coverage block from lecture notes."""
    lower = lecture_text.lower()
    if "slide body coverage" not in lower:
        return ""
    return lecture_text[lower.find("slide body coverage"):]


def get_body_items(slide: Any) -> Tuple[List[str], List[str]]:
    """Extract body text items from a slide, recursing into GROUP shapes."""
    items: List[str] = []
    chrome: List[str] = []

    def _add(t: str, min_len: int) -> None:
        if not t or len(t) < min_len or t.lower() == "generated by ai":
            return
        (chrome if is_chrome(t) else items).append(t)

    def _walk(shapes: Any) -> None:
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                try:
                    _walk(shape.shapes)
                except (AttributeError, ValueError):
                    pass
                continue
            if getattr(shape, "has_text_frame", False):
                for para in shape.text_frame.paragraphs:
                    _add(para.text.strip(), 4)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    for cell in row.cells:
                        _add(cell.text.strip(), 3)

    _walk(slide.shapes)
    return items, chrome


def get_distinctive_terms(text: str, min_len: int = 5, stopwords: Optional[Set[str]] = None) -> Set[str]:
    """Extract distinctive alpha terms, filtering stopwords."""
    sw = STOPWORDS if stopwords is None else stopwords
    words = re.findall(r'\b[a-zA-Z]{%d,}\b' % min_len, text)
    return {w.lower() for w in words if w.lower() not in sw}


def resolve_cfg(pptx_path: Optional[str] = None, spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build audit configuration from NOTES_FORMAT.md."""
    if spec is None:
        if pptx_path:
            spec, _ = load_format_spec(pptx_path)
        else:
            spec = DEFAULT_FORMAT_SPEC
    quality = spec.get("sbc_quality", {})
    vocab = spec.get("vocabulary", {}) or {}
    return {
        "spec": spec,
        "markers": quality.get("markers") or SBC_QUALITY_MARKERS,
        "pass_threshold": quality.get("pass_threshold", 4),
        "stopwords": STOPWORDS | set(vocab.get("stopwords_extra") or []),
        "require_all_fields": bool((spec.get("audit") or {}).get("require_all_fields", False)),
        "field_labels": [f["label"] for f in spec.get("sbc_fields", [])],
        "speaker_first": bool((spec.get("zones") or {}).get("speaker_first", True)),
        "verify_formatting": bool((spec.get("audit") or {}).get("verify_formatting", False)),
        "fonts": spec.get("fonts") or {},
        "bold_labels": spec.get("zone_a_labels") or [],
        "delivery_mode": spec.get("delivery_mode"),
        "min_paragraphs": (spec.get("audit") or {}).get("min_paragraphs", 2),
        "paragraph_rules": (spec.get("audit") or {}).get("paragraphs") or None,
        "engagement": spec.get("engagement") or {},
    }


def jaccard(set_a: Set[Any], set_b: Set[Any]) -> float:
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def audit_coverage(body_items: List[str], lecture_text: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Check which body items are addressed in lecture notes."""
    sw = (cfg or {}).get("stopwords")
    lecture_terms = get_distinctive_terms(lecture_text, min_len=4, stopwords=sw)
    missing: List[str] = []
    covered: List[str] = []

    for body in body_items:
        body_terms = get_distinctive_terms(body, min_len=4, stopwords=sw)
        distinctive = sorted(body_terms, key=lambda t: (-len(t), t))[:3]
        if not distinctive:
            continue
        if any(t in lecture_terms for t in distinctive):
            covered.append(body[:80])
        else:
            missing.append(body[:80])

    return {
        "total": len(body_items),
        "covered": len(covered),
        "missing": len(missing),
        "missing_items": missing,
        "coverage_pct": round(len(covered) / len(body_items) * 100) if body_items else 100,
    }


def audit_alignment(
    body_items: List[str],
    sbc_block: str,
    threshold: float = DEFAULT_ALIGNMENT_THRESHOLD,
    min_overlap: int = DEFAULT_MIN_OVERLAP,
    min_body_terms: int = 6,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Check semantic alignment between body text and SBC block."""
    if not sbc_block:
        return {
            "status": "NO_SBC",
            "jaccard": 0.0,
            "overlap_count": 0,
            "body_terms_count": 0,
            "sbc_terms_count": 0,
            "body_only": [],
            "sbc_only": [],
        }

    sw = (cfg or {}).get("stopwords")
    body_text = " ".join(body_items)
    body_terms = get_distinctive_terms(body_text, stopwords=sw)
    sbc_terms = get_distinctive_terms(sbc_block, stopwords=sw)

    if len(body_terms) < min_body_terms:
        return {
            "status": "SKIPPED",
            "reason": f"too few body terms ({len(body_terms)} < {min_body_terms})",
            "jaccard": 0.0,
            "overlap_count": 0,
            "body_terms_count": len(body_terms),
            "sbc_terms_count": len(sbc_terms),
            "body_only": [],
            "sbc_only": [],
        }

    jacc = jaccard(body_terms, sbc_terms)
    overlap_count = len(body_terms & sbc_terms)
    body_only = sorted(body_terms - sbc_terms)[:10]
    sbc_only = sorted(sbc_terms - body_terms)[:10]

    passes_jaccard = jacc >= threshold
    passes_overlap = overlap_count >= min_overlap

    return {
        "status": "ALIGNED" if (passes_jaccard or passes_overlap) else "MISALIGNED",
        "jaccard": round(jacc, 3),
        "overlap_count": overlap_count,
        "body_terms_count": len(body_terms),
        "sbc_terms_count": len(sbc_terms),
        "body_only": body_only,
        "sbc_only": sbc_only,
        "passes_jaccard": passes_jaccard,
        "passes_overlap": passes_overlap,
    }


def _is_field_label(line: str, field_labels: List[str]) -> bool:
    s = line.strip()
    if s.startswith("* "):
        s = s[2:].strip()
    low = s.lower()
    return any(low.startswith(lbl.lower() + ":") for lbl in field_labels)


def parse_sbc_items(sbc_block: str, field_labels: List[str]) -> Tuple[List[Dict[str, Any]], int]:
    """Parse SBC items from a Slide Body Coverage block."""
    items: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    named = 0

    def _implicit() -> Dict[str, Any]:
        return {"label": "(unstructured block)", "text": "", "_implicit": True}

    for raw in sbc_block.split("\n"):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.upper().startswith("SLIDE BODY COVERAGE"):
            continue
        if _is_field_label(stripped, field_labels):
            if current is None:
                current = _implicit()
            current["text"] += " " + stripped
            continue

        bulleted = stripped.startswith("* ")
        body = stripped[2:].strip() if bulleted else stripped
        is_bare_header = (
            not bulleted
            and body.endswith(":")
            and len(body) <= 90
            and "  " not in body
            and body.count(":") == 1
        )
        if bulleted or is_bare_header:
            if current is not None:
                items.append(current)
            current = {"label": body, "text": ""}
            named += 1
        else:
            if current is None:
                current = _implicit()
            current["text"] += " " + stripped

    if current is not None:
        items.append(current)
    return items, named


def audit_sbc_quality(sbc_block: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Check each SBC item for the declared quality structure."""
    cfg = cfg or {}
    markers = cfg.get("markers") or SBC_QUALITY_MARKERS
    pass_threshold = cfg.get("pass_threshold", 4)
    declared = cfg.get("field_labels") or []
    require_all = cfg.get("require_all_fields", False)

    if not sbc_block:
        return {"status": "NO_SBC", "items": []}

    items, named = parse_sbc_items(sbc_block, declared)

    if named == 0:
        substantive = len(sbc_block.strip()) > 120
        return {
            "status": "NO_ITEMS_PARSED",
            "items": [{"label": i["label"], "text_len": len(i["text"])} for i in items],
            "reason": (
                "content present but no item headers and no declared field labels"
                if substantive
                else "SBC header present but no content"
            ),
            "declared_fields": declared,
            "block_chars": len(sbc_block.strip()),
        }

    quality_items = []
    for item in items:
        full_text = item["label"] + " " + item["text"]
        markers_found = {}
        for marker_name, pattern in markers:
            markers_found[marker_name] = bool(re.search(pattern, full_text))

        score = sum(1 for v in markers_found.values() if v)
        missing_fields = []
        if require_all:
            for label in declared:
                if not re.search(r'(?i)' + re.escape(label) + r'\s*:', full_text):
                    missing_fields.append(label)

        quality_items.append({
            "label": item["label"][:80],
            "score": score,
            "max_score": len(markers),
            "markers": markers_found,
            "missing_markers": [k for k, v in markers_found.items() if not v],
            "missing_fields": missing_fields,
        })

    if not quality_items:
        return {
            "status": "NO_ITEMS_PARSED",
            "items": [],
            "reason": "SBC block present but no items or declared field labels parsed",
            "declared_fields": declared,
        }

    max_score = len(markers)
    avg_score = round(sum(i["score"] for i in quality_items) / len(quality_items), 1)
    below = [i for i in quality_items if i["score"] < pass_threshold]
    items_missing_fields = [i for i in quality_items if i["missing_fields"]]

    if avg_score >= pass_threshold and not items_missing_fields:
        status = "PASS"
    elif avg_score >= pass_threshold and items_missing_fields:
        status = "WEAK"
    elif avg_score >= 2:
        status = "WEAK"
    else:
        status = "FAIL"

    return {
        "status": status,
        "item_count": len(quality_items),
        "average_score": avg_score,
        "max_score": max_score,
        "pass_threshold": pass_threshold,
        "items_below_threshold": len(below),
        "items_below_4": len(below),
        "items_missing_fields": len(items_missing_fields),
        "require_all_fields": require_all,
        "items": quality_items,
    }


def _norm_field(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")


def _rule_for(field: str, cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    rules = dict(PARAGRAPH_RULES)
    for k, v in ((cfg or {}).get("paragraph_rules") or {}).items():
        rules[_norm_field(k)] = {**rules.get(_norm_field(k), {}), **(v or {})}
    key = _norm_field(field)
    if key in rules and key != "default":
        r = dict(rules[key])
    else:
        r = dict(rules.get("default", {"min": 2}))
        if (cfg or {}).get("min_paragraphs") is not None:
            r["min"] = int(cfg["min_paragraphs"])
    r.setdefault("min", 1)
    return r


def _count_paragraphs(segment: str) -> int:
    seg = (segment or "").strip().strip('"').strip()
    if not seg:
        return 0
    parts = [p.strip() for p in re.split(r"\n\s*\n", seg)]
    parts = [p for p in parts if not re.match(r"(?i)^[\*\-•]?\s*sources?\s*:", p)]
    return sum(1 for p in parts if len(p) >= 40)


def _judge(field: str, body: str, cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    rule = _rule_for(field, cfg)
    paras = _count_paragraphs(body)
    clean = "\n".join(ln for ln in body.splitlines() if not re.match(r"(?i)^\s*[\*\-•]?\s*sources?\s*:", ln))
    return {
        "field": field,
        "paragraphs": paras,
        "min": rule.get("min"),
        "max": rule.get("max"),
        "below": paras < rule.get("min", 1),
        "over": bool(rule.get("max")) and paras > rule["max"],
        "not_prose": bool(rule.get("prose_only")) and bool(_BULLET_LINE.search(clean)),
        "chars": len(body.strip()),
        "words": len(body.split()),
    }


def _depth_status(items: List[Dict[str, Any]]) -> str:
    if any(i["below"] for i in items):
        return "BELOW_DEPTH"
    if any(i["over"] for i in items):
        return "OVER_MAX_PARAGRAPHS"
    if any(i["not_prose"] for i in items):
        return "NOT_PROSE"
    return "DEPTH_OK"


def audit_sbc_depth(sbc_block: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Check per-field paragraph standard for SBC."""
    cfg = cfg or {}
    declared = cfg.get("field_labels") or []
    min_paras = int(cfg.get("min_paragraphs", 2))
    if not sbc_block:
        return {"status": "NO_SBC", "items": [], "min_paragraphs": min_paras}

    labels = list(declared) if declared else [
        "Plain English", "Deep Research", "Concrete Example",
        "Bigger Picture", "Assessment Link", "Manager's So What",
    ]
    label_re = re.compile(
        r"(?i)(?:^|\n)\s*\*?\s*("
        + "|".join(re.escape(x) for x in sorted(labels, key=len, reverse=True))
        + r")\s*:"
    )

    matches = list(label_re.finditer(sbc_block))
    fields = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(sbc_block)
        fields.append(_judge(m.group(1), sbc_block[start:end], cfg))

    if not fields:
        return {"status": "NO_FIELDS_PARSED", "items": [], "min_paragraphs": min_paras}

    return {
        "status": _depth_status(fields),
        "min_paragraphs": min_paras,
        "fields_checked": len(fields),
        "fields_below": sum(1 for f in fields if f["below"]),
        "average_paragraphs": round(sum(f["paragraphs"] for f in fields) / len(fields), 1),
        "items": fields,
        "below": [f["field"] for f in fields if f["below"]],
        "over": [f["field"] for f in fields if f["over"]],
        "not_prose": [f["field"] for f in fields if f["not_prose"]],
    }


def audit_zone_a_depth(speaker_text: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Check KEY POINT: 1–3 paragraphs of prose."""
    cfg = cfg or {}
    rule = _rule_for("KEY POINT", cfg)
    if not speaker_text:
        return {"status": "NO_ZONE_A", "items": [], "min_paragraphs": rule["min"]}

    stop = (
        "SOCRATIC", "COMMON STUDENT", "ACTIVITY", "TEACHER GUIDANCE",
        "TRANSITION", "BRIDGE", "NARRATIVE OPENING", "VIDEO CUE",
        "--- VISUAL DECONSTRUCTION ---",
    )
    items = []
    for m in re.finditer(r"(?im)^\s*\*?\s*KEY POINT\s*:", speaker_text):
        rest = speaker_text[m.end():]
        ends = [rest.find(s) for s in stop if rest.find(s) > 0]
        seg = rest[:min(ends)] if ends else rest
        items.append(_judge("KEY POINT", seg.strip(), cfg))

    if not items:
        return {"status": "NO_KEY_POINT", "items": [], "min_paragraphs": rule["min"]}

    return {
        "status": _depth_status(items),
        "min_paragraphs": rule["min"],
        "max_paragraphs": rule.get("max"),
        "fields_checked": len(items),
        "fields_below": sum(1 for i in items if i["below"]),
        "average_paragraphs": round(sum(i["paragraphs"] for i in items) / len(items), 1),
        "items": items,
    }


def audit_example_sources(lecture_text: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Check if every Concrete Example ends with a Sources: line."""
    checks = check_example_sourcing(lecture_text or "", (cfg or {}).get("field_labels") or None)
    if not checks:
        return {"status": "NO_EXAMPLES", "examples": 0, "unsourced": []}
    unsourced = [c["item"] for c in checks if c["status"] == "NO_SOURCE"]
    return {
        "status": "EXAMPLE_UNSOURCED" if unsourced else "SOURCED",
        "examples": len(checks),
        "unsourced": unsourced,
    }


def audit_formatting(slide: Any, cfg: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Verify run-level formatting against the spec."""
    cfg = cfg or {}
    if not cfg.get("verify_formatting"):
        return None

    try:
        tf = slide.notes_slide.notes_text_frame
    except (AttributeError, ValueError):
        return None
    if tf is None:
        return None

    fonts = cfg.get("fonts") or {}
    sz_timing = (fonts.get("timing", 1100)) / 100.0
    sz_header = (fonts.get("header", 1000)) / 100.0
    sz_body = (fonts.get("body", 1000)) / 100.0
    sz_sub = (fonts.get("sub", 900)) / 100.0
    bold_labels = [l.upper() for l in (cfg.get("bold_labels") or [])]
    field_labels = cfg.get("field_labels") or []

    mismatches = []

    def _check(text: str, run: Any, exp_bold: Optional[bool] = None, exp_italic: Optional[bool] = None, exp_size: Optional[float] = None) -> None:
        actual_bold = run.font.bold
        actual_italic = run.font.italic
        actual_size = run.font.size.pt if run.font.size is not None else None
        problems = []
        if exp_bold is not None and bool(actual_bold) != exp_bold:
            problems.append(f"bold expected={exp_bold} actual={actual_bold}")
        if exp_italic is not None and bool(actual_italic) != exp_italic:
            problems.append(f"italic expected={exp_italic} actual={actual_italic}")
        if exp_size is not None and actual_size is not None and abs(actual_size - exp_size) > 0.01:
            problems.append(f"size expected={exp_size}pt actual={actual_size}pt")
        if problems:
            mismatches.append({"text": text[:60], "problems": problems})

    for para in tf.paragraphs:
        for run in para.runs:
            t = run.text.strip()
            if not t:
                continue
            up = t.upper()
            if t.startswith("⏱"):
                _check(t, run, exp_bold=True, exp_size=sz_timing)
            elif (
                up.startswith("--- SPEAKER NOTES ---")
                or up.startswith("--- LECTURE NOTES ---")
                or up.startswith("--- VISUAL DECONSTRUCTION ---")
            ):
                _check(t, run, exp_bold=True, exp_size=sz_header)
            elif up.startswith("• CORE NARRATIVE") or up.startswith("SLIDE BODY COVERAGE"):
                _check(t, run, exp_bold=True, exp_size=sz_header)
            elif any(up.startswith(f"* {l}") or up.startswith(l) for l in bold_labels):
                _check(t, run, exp_bold=True, exp_size=sz_header)
            elif any(t.startswith(l) for l in field_labels):
                _check(t, run, exp_bold=True, exp_size=sz_sub)
            elif len(t) > 1 and t.startswith('"') and t.endswith('"'):
                _check(t, run, exp_italic=True, exp_size=sz_body)

    return {
        "status": "FORMATTING_OK" if not mismatches else "FORMATTING_ISSUES",
        "run_mismatches": len(mismatches),
        "mismatches": mismatches[:25],
    }


def audit_cadence(prs: Any, cfg: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Deck-level engagement cadence (online delivery only)."""
    cfg = cfg or {}
    if str(cfg.get("delivery_mode") or "").lower() != "online":
        return None

    eng = cfg.get("engagement") or {}
    max_gap = eng.get("max_gap_minutes", 12)
    required = list(eng.get("required_formats") or [])

    timeline = []
    no_timing = 0
    total_min = 0.0
    chat_poll_slides: List[int] = []
    breakout_slides: List[int] = []
    breakout_no_deliverable: List[int] = []

    for i, slide in enumerate(prs.slides):
        num = i + 1
        text = get_slide_notes_text(slide)
        if not text:
            timeline.append((num, 0.0, set()))
            no_timing += 1
            continue
        m = TIMING_RE.search(text)
        mins = float(m.group(1)) if m else 0.0
        if not m:
            no_timing += 1
        total_min += mins

        markers = {name for name, rx in ENGAGEMENT_MARKERS if rx.search(text)}
        timeline.append((num, mins, markers))

        if CHAT_POLL_RE.search(text):
            chat_poll_slides.append(num)
        if BREAKOUT_RE.search(text):
            breakout_slides.append(num)
            if not DELIVERABLE_RE.search(text):
                breakout_no_deliverable.append(num)

    best, gap, cur_start, best_span = 0.0, 0.0, None, None
    interactions = 0
    for num, mins, markers in timeline:
        if markers:
            interactions += 1
            if cur_start is not None and gap > best:
                best, best_span = gap, (cur_start, num - 1)
            gap, cur_start = 0.0, None
        else:
            if cur_start is None:
                cur_start = num
            gap += mins
    if cur_start is not None and gap > best:
        best, best_span = gap, (cur_start, len(timeline))

    missing = []
    if "chat" in required and not chat_poll_slides:
        missing.append("chat")
    if "breakout_deliverable" in required and not (
        [s for s in breakout_slides if s not in breakout_no_deliverable]
    ):
        missing.append("breakout_deliverable")

    gap_fail = best > max_gap
    if gap_fail and missing:
        status = "CADENCE_GAP+MISSING_FORMATS"
    elif gap_fail:
        status = "CADENCE_GAP"
    elif missing:
        status = "MISSING_FORMATS"
    else:
        status = "CADENCE_OK"

    return {
        "status": status,
        "delivery_mode": "online",
        "max_gap_minutes": max_gap,
        "longest_gap_minutes": round(best, 1),
        "longest_gap_slides": list(best_span) if best_span else None,
        "interactions": interactions,
        "total_minutes": round(total_min, 1),
        "slides_without_timing": no_timing,
        "gap_is_floor": no_timing > 0,
        "required_formats": required,
        "missing_formats": missing,
        "chat_poll_slides": chat_poll_slides[:20],
        "breakout_slides": breakout_slides[:20],
        "breakouts_without_deliverable": breakout_no_deliverable,
    }


# Every status audit_slide can emit. Callers should treat anything outside
# ("PASS", "SKIPPED") as a finding rather than allow-listing individual statuses —
# an allow-list silently drops statuses added later.
AUDIT_STATUSES = (
    "PASS",
    "GAPS",
    "MISALIGNED",
    "WEAK_QUALITY",
    "SHALLOW_DEPTH",
    "WEAK_ZONE_A",
    "UNSOURCED_EXAMPLES",
    "UNPARSED_SBC",
    "NO_SBC",
    "NO_NOTES",
    "SKIPPED",
)

# Depth verdicts that mean "the writing is too thin", as opposed to "the field is absent".
_DEPTH_FAILURES = ("BELOW_DEPTH", "NOT_PROSE", "OVER_MAX_PARAGRAPHS")


def summarise_results(results: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Count slides per status, keyed lowercase."""
    counts = {status.lower(): 0 for status in AUDIT_STATUSES}
    for result in results:
        key = str(result.get("status", "")).lower()
        counts[key] = counts.get(key, 0) + 1
    return counts


def audit_slide(
    slide: Any,
    slide_num: int,
    threshold: float = DEFAULT_ALIGNMENT_THRESHOLD,
    min_overlap: int = DEFAULT_MIN_OVERLAP,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run all SBC audit passes on a single slide."""
    title = get_slide_title(slide)
    body_items, chrome_items = get_body_items(slide)
    has_visuals = has_visual_content(slide)

    if not body_items and not has_visuals:
        return {
            "slide": slide_num,
            "title": title,
            "status": "SKIPPED",
            "reason": "no body text or visuals",
        }

    if not getattr(slide, "has_notes_slide", False):
        return {
            "slide": slide_num,
            "title": title,
            "status": "NO_NOTES",
            "body_items": len(body_items),
        }

    full_text = get_slide_notes_text(slide)
    if not full_text:
        return {
            "slide": slide_num,
            "title": title,
            "status": "NO_NOTES",
            "body_items": len(body_items),
            "reason": "notes slide present but has no text frame",
        }

    speaker_text, lecture_text = split_speaker_and_lecture(
        full_text, (cfg or {}).get("speaker_first", True)
    )
    sbc_block = extract_sbc_block(lecture_text)

    coverage = audit_coverage(body_items, lecture_text, cfg) if body_items else None
    alignment = audit_alignment(body_items, sbc_block, threshold, min_overlap, cfg=cfg)
    quality = audit_sbc_quality(sbc_block, cfg)
    depth = audit_sbc_depth(sbc_block, cfg)
    zone_a_depth = audit_zone_a_depth(speaker_text, cfg)
    example_sources = audit_example_sources(lecture_text, cfg)
    formatting = audit_formatting(slide, cfg)

    # Every pass below is computed above; each one that can judge the notes must be
    # able to fail them. Depth, Zone A depth and example sourcing used to be computed
    # and then ignored, so a slide whose six SBC fields each held one word scored PASS.
    if not sbc_block:
        overall = "NO_SBC"
    elif quality["status"] == "NO_ITEMS_PARSED":
        overall = "UNPARSED_SBC"
    elif alignment["status"] == "MISALIGNED":
        overall = "MISALIGNED"
    elif quality["status"] in ("WEAK", "FAIL"):
        overall = "WEAK_QUALITY"
    elif depth["status"] in _DEPTH_FAILURES:
        overall = "SHALLOW_DEPTH"
    elif zone_a_depth["status"] in _DEPTH_FAILURES:
        overall = "WEAK_ZONE_A"
    elif example_sources["status"] == "EXAMPLE_UNSOURCED":
        overall = "UNSOURCED_EXAMPLES"
    elif coverage and coverage["missing"] > 0:
        overall = "GAPS"
    else:
        overall = "PASS"

    return {
        "slide": slide_num,
        "title": title,
        "status": overall,
        "body_items": len(body_items),
        "chrome_items": len(chrome_items),
        "has_visuals": has_visuals,
        "coverage": coverage,
        "alignment": alignment,
        "quality": quality,
        "depth": depth,
        "zone_a_depth": zone_a_depth,
        "example_sources": example_sources,
        "formatting": formatting,
    }


def run_audit(
    pptx_path: str,
    threshold: float = DEFAULT_ALIGNMENT_THRESHOLD,
    min_overlap: int = DEFAULT_MIN_OVERLAP,
    slide_num: Optional[int] = None,
    depth_summary: bool = False,
    jaccard_threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """Run SBC audit on a PPTX presentation file."""
    if jaccard_threshold is not None:
        threshold = jaccard_threshold
    if not os.path.exists(pptx_path):
        raise FileNotFoundError(f"Presentation not found: {pptx_path}")

    spec, report = load_format_spec(pptx_path)
    cfg = resolve_cfg(pptx_path, spec)

    prs = Presentation(pptx_path)
    results = []

    for i, slide in enumerate(prs.slides):
        if slide_num is not None and (i + 1) != slide_num:
            continue
        results.append(audit_slide(slide, i + 1, threshold, min_overlap, cfg))

    return {
        "file": os.path.basename(pptx_path),
        "total_slides": len(results),
        "threshold": threshold,
        "min_overlap": min_overlap,
        "summary": summarise_results(results),
        "cadence": audit_cadence(prs, cfg),
        "format_spec": {
            "found": report["found"],
            "bound": report["bound"],
            "draft": report["draft"],
            "errors": report["errors"],
            "sources": report["sources"],
            "pass_threshold": cfg["pass_threshold"],
            "require_all_fields": cfg["require_all_fields"],
            "verify_formatting": cfg["verify_formatting"],
        },
        "results": results,
    }
