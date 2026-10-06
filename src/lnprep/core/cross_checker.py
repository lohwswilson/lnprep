"""
Cross-check validation engine for session guides (LECTURE_NOTES_GUIDE.md).
Automates time budget audits, assessment linkages, learning outcome anchoring,
and deck/reading file coverage.
"""

from __future__ import annotations

import glob
import os
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set

from lnprep.core.common import parse_guide

OK, FAIL, NOT_CHECKABLE, PARTIAL = "OK", "FAIL", "NOT_CHECKABLE", "PARTIAL"

HEADINGS = {
    "identity": ("Session Identity", "Module Identity"),
    "flow": ("Suggested Session Flow",),
    "linkage": (
        "Assessment-Linkage Reminders",
        "Assessment Linkage Reminders",
        "Assessment-Linkage",
        "Assessment Links",
    ),
    "openq": ("Open Question for Wilson", "Open Questions", "Open Question"),
    "rules": ("Formatting & Notes Rules", "Formatting and Notes Rules"),
}

BLOCK_RE = re.compile(
    r'^#{2,4}\s+Block\s+\d+\s*[–—-][^\n]*?\((\d+(?:\.\d+)?)\s*min',
    re.I | re.M,
)
BREAK_RE = re.compile(
    r'^#{2,4}\s+Break\s+\d+[^\n]*?\((\d+(?:\.\d+)?)\s*min',
    re.I | re.M,
)
DURATION_MIN_RE = re.compile(r'(\d+)\s*min', re.I)
DURATION_HOURS_RE = re.compile(r'(\d+(?:\.\d+)?)\s*hours?', re.I)

NOTATIONS = (
    ("A1-section", re.compile(r'\bA\d+\s*§\s*(\d+(?:\.\d+)?)')),
    ("A1-S", re.compile(r'\bA\d+\s+S\s*(\d+(?:\.\d+)?)')),
    ("section-sign", re.compile(r'§\s*(\d+(?:\.\d+)?)')),
    ("task", re.compile(r'\bTask\s*(\d+)\b', re.I)),
    ("lo", re.compile(r'\b(?:I)?LO\s*(\d+)\b', re.I)),
    ("mlo", re.compile(r'\bMLO\s*(\d+)\b', re.I)),
)


def _section(md: str, key: str) -> Optional[str]:
    """Return text of first matching section, or None."""
    for name in HEADINGS[key]:
        m = re.search(r'^##\s+' + re.escape(name) + r'[^\n]*$', md, re.I | re.M)
        if m:
            nxt = re.search(r'^##\s+', md[m.end():], re.M)
            return md[m.end():m.end() + nxt.start()] if nxt else md[m.end():]
    return None


def _minutes(s: Any) -> Optional[int]:
    if not s:
        return None
    m = DURATION_MIN_RE.search(str(s))
    if m:
        return int(m.group(1))
    h = DURATION_HOURS_RE.search(str(s))
    if h:
        return int(round(float(h.group(1)) * 60))
    return None


def _normalise(name: str) -> str:
    stem = os.path.splitext(name)[0]
    return re.sub(r'\s+', ' ', re.sub(r'[_\-–—]+', ' ', stem)).strip().lower()


def _code(name: str) -> Optional[str]:
    m = re.match(r'^(\d{1,2}[A-Za-z]?)\s*[\.\s\[]', name)
    return m.group(1) if m else None


def _flat(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r'\\([\[\]_\#\*])', r'\1', s)
    s = re.sub(r'[_\-\u2013\u2014]+', ' ', s.lower())
    return re.sub(r'\s+', ' ', s).strip()


def _mentioned(guide_md: str, filename: str) -> bool:
    low = _flat(guide_md)
    if _flat(filename) in low:
        return True
    norm = _normalise(filename)
    if norm and norm in low:
        return True
    for n in (40, 28, 20):
        if len(norm) >= n and norm[:n] in low:
            return True
    code = _code(filename)
    if code and re.search(r'\b' + re.escape(code) + r'\b', guide_md, re.I):
        return True
    return False


def check_budget(md: str, ident: Dict[str, Any]) -> Dict[str, Any]:
    """Check time budget balance."""
    blocks = BLOCK_RE.findall(md)
    breaks = BREAK_RE.findall(md)
    if not blocks:
        return {
            "check": "budget",
            "status": NOT_CHECKABLE,
            "reason": "no '### Block N — … (N min)' headings — cannot sum a budget",
        }
    teach = sum(float(v) for v in blocks)
    brk = sum(float(v) for v in breaks)
    total = teach + brk

    declared = _minutes(ident.get("duration"))
    flow = _section(md, "flow")
    footer = None
    flow_items = None
    if flow:
        m = re.search(r'=\s*(\d+)\s*min', flow)
        if m:
            footer = int(m.group(1))
        items = [int(x) for x in re.findall(r'\((\d+)\s*min\)', flow)]
        if items:
            flow_items = sum(items)

    out: Dict[str, Any] = {
        "check": "budget",
        "status": OK,
        "block_minutes": teach,
        "break_minutes": brk,
        "total_minutes": total,
        "declared_minutes": declared,
        "footer_minutes": footer,
        "flow_items_minutes": flow_items,
    }
    problems = []
    if declared is None:
        out["status"] = NOT_CHECKABLE
        out["reason"] = "no duration: in the identity block"
        return out

    if total != declared:
        floor = flow_items is not None and flow_items > total
        problems.append(
            f"blocks+breaks = {total:g} but duration declares {declared}"
            + (
                f" (block headings are a floor here — the flow list totals "
                f"{flow_items}, so {flow_items - total:g} min sit in timed "
                f"sections that are not Blocks)"
                if floor
                else ""
            )
        )
        out["status"] = FAIL
    if footer is not None and footer != total:
        problems.append(f"the flow footer claims {footer} while the blocks sum to {total:g}")
        out["status"] = FAIL
    if flow_items is not None and flow_items != total:
        problems.append(f"the flow list items sum to {flow_items} while the block headings sum to {total:g}")
        out["status"] = FAIL
    out["problems"] = problems
    return out


def check_assessment(coverage_by_session: Dict[str, Any]) -> Dict[str, Any]:
    """Check assessment section linkage across sessions."""
    per_notation: Dict[str, Set[str]] = {n: set() for n, _ in NOTATIONS}
    union: Set[str] = set()
    session_sets: Dict[str, Set[str]] = {}
    for sess, refs in coverage_by_session.items():
        session_sets[sess] = set(refs["sections"])
        union |= session_sets[sess]
        for n, hits in refs["notations"].items():
            per_notation[n] |= set(hits)

    matched = {n: sorted(v) for n, v in per_notation.items() if v}
    if not union:
        return {
            "check": "assessment",
            "status": NOT_CHECKABLE,
            "reason": "no assessment-section references found in any 'Assessment-Linkage Reminders' section",
        }
    orphan = sorted(s for s, refs in session_sets.items() if not refs)
    thin = {s: sorted(v) for s, v in session_sets.items() if len(v) == 1}
    return {
        "check": "assessment",
        "status": PARTIAL,
        "sections": sorted(union),
        "section_count": len(union),
        "notation_matched": matched,
        "sessions_with_no_links": orphan,
        "sections_in_only_one_session": thin,
        "reason": "universe derived from guides; verifying against brief requires docx/pdf analysis",
    }


def check_los(md_by_session: Dict[str, str]) -> Dict[str, Any]:
    """Check every LO is anchored in at least two sessions."""
    mlo: Dict[str, Set[str]] = {}
    lo: Dict[str, Set[str]] = {}
    for sess, md in md_by_session.items():
        for n in set(re.findall(r'\bMLO\s*(\d+)\b', md, re.I)):
            mlo.setdefault(n, set()).add(sess)
        for n in set(re.findall(r'\b(?:I)?LO\s*(\d+)\b', md, re.I)):
            lo.setdefault(n, set()).add(sess)

    if not mlo and not lo:
        return {
            "check": "lo_coverage",
            "status": NOT_CHECKABLE,
            "reason": "no MLO/LO references found in any guide",
        }
    thin = {f"MLO {k}": sorted(v) for k, v in mlo.items() if len(v) < 2}
    thin.update({f"LO {k}": sorted(v) for k, v in lo.items() if len(v) < 2})
    return {
        "check": "lo_coverage",
        "status": FAIL if thin else OK,
        "mlo_sessions": {f"MLO {k}": sorted(v) for k, v in sorted(mlo.items())},
        "lo_sessions": {f"LO {k}": sorted(v) for k, v in sorted(lo.items())},
        "anchored_in_one_session_only": thin,
    }


def check_linkage(folder: Optional[str], md: Optional[str], kind: str, exts: Sequence[str], recurse: bool = False) -> Dict[str, Any]:
    """Check every deck / reading file on disk is referenced in the guide."""
    label = "deck" if kind == "deck" else "reading"
    if folder is None or not os.path.isdir(folder):
        return {"check": label, "status": NOT_CHECKABLE, "reason": "session folder not found"}
    pattern = os.path.join(folder, "**", "*") if recurse else os.path.join(folder, "*")
    files = [f for e in exts for f in glob.glob(pattern, recursive=recurse) if f.lower().endswith(e)]
    files = [f for f in files if not os.path.basename(f).startswith("~$") and "_backup_" not in os.path.basename(f)]
    if not files:
        return {"check": label, "status": NOT_CHECKABLE, "reason": f"no {'/'.join(exts)} files in folder"}
    if md is None:
        return {"check": label, "status": NOT_CHECKABLE, "reason": "no guide to check against"}
    missing = [os.path.basename(f) for f in files if not _mentioned(md, os.path.basename(f))]
    return {
        "check": label,
        "status": FAIL if missing else OK,
        "on_disk": len(files),
        "unreferenced": missing,
    }


def _session_label(guide_path: str, module_root: str) -> str:
    rel = os.path.relpath(os.path.dirname(guide_path), module_root)
    return "(module root)" if rel == "." else rel


def cross_check_module(module_root: str, only: Optional[str] = None) -> Dict[str, Any]:
    """Validate all session guides in a module."""
    guides = sorted(glob.glob(os.path.join(module_root, "**", "LECTURE_NOTES_GUIDE.md"), recursive=True))
    if not guides:
        return {
            "module": os.path.basename(module_root),
            "status": "NO_GUIDES",
            "reason": "no LECTURE_NOTES_GUIDE.md found",
        }

    sessions: Dict[str, Any] = {}
    md_by_session: Dict[str, str] = {}
    coverage: Dict[str, Any] = {}
    legacy: List[str] = []

    for g in guides:
        label = _session_label(g, module_root)
        try:
            with open(g, "r", encoding="utf-8") as f:
                md = f.read()
        except Exception as exc:
            sessions[label] = {"status": NOT_CHECKABLE, "reason": f"unreadable: {exc}"}
            continue

        ident = parse_guide(g)
        if "session" not in ident and ident.get("total_sessions"):
            legacy.append(label)
        md_by_session[label] = md
        coverage[label] = {"sections": [], "notations": {n: [] for n, _ in NOTATIONS}}
        link = _section(md, "linkage")
        if link is None:
            coverage[label]["status"] = NOT_CHECKABLE
            coverage[label]["reason"] = "no 'Assessment-Linkage Reminders' section — nothing to check"
        else:
            for n, rx in NOTATIONS:
                coverage[label]["notations"][n] = sorted(set(rx.findall(link)))
            refs = set()
            for n, rx in NOTATIONS:
                for v in rx.findall(link):
                    refs.add(
                        ("§" if "section" in n else "Task " if n == "task" else "MLO " if n == "mlo" else "LO ")
                        + v
                    )
            coverage[label]["sections"] = sorted(refs)

        sessions[label] = {
            "guide": os.path.relpath(g, module_root),
            "format": "legacy-module-root" if label in legacy else "per-session",
            "headings": {k: (_section(md, k) is not None) for k in HEADINGS},
        }

    checks: Dict[str, Any] = {}
    if only in (None, "budget"):
        for label, md in md_by_session.items():
            ident = parse_guide(os.path.join(module_root, sessions[label]["guide"]))
            sessions[label]["budget"] = check_budget(md, ident)
    if only in (None, "assessment"):
        checks["assessment"] = check_assessment(coverage)
    if only in (None, "lo"):
        checks["lo_coverage"] = check_los(md_by_session)
    if only in (None, "deck", "reading"):
        for label, md in md_by_session.items():
            folder = os.path.dirname(os.path.join(module_root, sessions[label]["guide"]))
            if only in (None, "deck"):
                sessions[label]["deck"] = check_linkage(folder, md, "deck", (".pptx",), recurse=False)
            if only in (None, "reading"):
                sessions[label]["reading"] = check_linkage(folder, md, "reading", (".pdf",), recurse=True)

    return {
        "module": os.path.basename(module_root),
        "module_root": module_root,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sessions": sessions,
        "legacy_guides": legacy,
        "module_checks": checks,
    }
