"""
Reference verification engine.
Validates in-text citations, DOIs, ISBNs, and live URLs before slides ship.
Connects with Crossref, OpenLibrary, doi.org, and local citation cache.
"""

from __future__ import annotations

import html
import json
import os
import re
import socket
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import lnprep.core.citation_db as citation_db
from lnprep.config import (
    BROWSER_UA,
    CROSSREF_UA,
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_TTL_DAYS,
    MAX_DOWNLOAD_BYTES,
    OVERRIDE_LOG,
)

BLOCKING = ("MISMATCH", "NOT_FOUND", "BROKEN_LINK", "EPHEMERAL_URL", "NO_SOURCE", "UNRESOLVED")
PASSING = ("VERIFIED", "CACHED")

SBC_LABELS = [
    "Plain English",
    "Deep Research",
    "Concrete Example",
    "Bigger Picture",
    "Assessment Link",
    "Manager's So What",
]

_NAME = r"[A-Z][A-Za-zÀ-ÿ'’\-]+"
_INITIALS = r"(?:,\s*[A-Z]\.(?:\s*[A-Z]\.?)*)"
_NARR = re.compile(
    r"("
    + _NAME
    + _INITIALS
    + r"?"
    r"(?:\s+et\s+al\.?"
    r"|(?:,\s*"
    + _NAME
    + _INITIALS
    + r"?)*(?:,?\s+(?:and|&)\s+"
    + _NAME
    + _INITIALS
    + r"?)?)?)"
    r"\s*\(((?:19|20)\d{2}[a-z]?)\)"
)
_PAREN = re.compile(r"\(([^()]*?(?:19|20)\d{2}[a-z]?[^()]*?)\)")
_PAREN_PART = re.compile(
    r"^\s*(?:e\.g\.,?\s*|see\s+|cf\.\s*)?([A-Z][^;]{0,80}?),?\s+((?:19|20)\d{2}[a-z]?)"
    r"(?:,\s*(?:p|pp)\.?\s*[\d\-–]+)?\s*$"
)

_MONTHS = {
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December"
}

NOT_AUTHORS = _MONTHS | {
    "Author", "Authors", "Org", "Organisation", "Organization",
    "Frontier", "Foundation", "Anchor", "Empirical", "Classical", "Contemporary",
    "Year", "Month", "Week", "Day", "Quarter", "Fiscal", "Calendar", "FY",
    "Case", "Thread", "Topic", "Figure", "Table", "Source", "Sources", "Assessment",
    "Quiz", "Module", "Block", "Activity", "Step", "Note", "Check", "Stage", "Part",
    "Phase", "Level", "Tier", "Slide", "Session", "Unit", "Section",
    "Appendix", "Chapter", "Exhibit", "Version", "Edition", "Rule", "Law",
    "Principle", "Protocol", "Framework", "Model", "Method", "Theory",
    "Investigations", "Subcommittee", "Senate", "Committee", "Since", "In", "By",
    "From", "Until", "Before", "After", "During", "The", "This", "That", "Recent",
    "Updated", "Research", "Context", "Q1", "Q2", "Q3", "Q4", "H1", "H2", "Est",
}

_TRAILING_CONNECTORS = {
    "in", "of", "by", "from", "since", "to", "for", "at", "on",
    "and", "the", "during", "until", "around", "about", "than",
}

_DOI = re.compile(r"(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?\b(10\.\d{4,9}/[^\s\"'<>]+)", re.I)
_URL = re.compile(r"https?://[^\s\"'<>]+", re.I)
_ISBN = re.compile(r"\bISBN(?:-1[03])?:?\s*((?:97[89][\s\-]?)?(?:\d[\s\-]?){9}[\dXx])\b")
_EPHEMERAL = (
    "vertexaisearch.cloud.google.com/grounding-api-redirect",
    "google.com/url?",
    "bing.com/ck/",
    "r.jina.ai/",
)
_NUM = re.compile(r"(?<![\w.,/])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(\s?%|\s?per\s?cent)?(?![\w/])")


def _clean_author(a: str) -> str:
    a = a.strip().rstrip("'’").strip()
    a = re.sub(r"\s+", " ", a)
    return a


def _author_ok(a: str) -> bool:
    if not a or len(a) > 80 or not a[0].isupper():
        return False
    words = re.split(r"[\s,]+", a.strip())
    if words[0].rstrip(".") in NOT_AUTHORS or len(words) > 8:
        return False
    if re.search(r"\d", a):
        return False
    if words[-1].lower() in _TRAILING_CONNECTORS:
        return False
    return True


def extract_citations(text: str) -> List[Dict[str, Any]]:
    """Return in-text citations as dicts {author, year, start, end}."""
    text = text or ""
    found: List[Dict[str, Any]] = []

    def overlaps(s: int, e: int) -> bool:
        return any(not (e <= f["start"] or s >= f["end"]) for f in found)

    for m in _PAREN.finditer(text):
        inner_start = m.start(1)
        offset = 0
        for part in m.group(1).split(";"):
            pm = _PAREN_PART.match(part)
            if pm:
                author = _clean_author(pm.group(1))
                if _author_ok(author) and not author.lower().startswith(("http", "doi")):
                    s = inner_start + offset
                    found.append({
                        "author": author,
                        "year": pm.group(2),
                        "start": s,
                        "end": s + len(part),
                    })
            offset += len(part) + 1

    for m in _NARR.finditer(text):
        author = _clean_author(re.sub(_INITIALS + r"$", "", m.group(1)))
        if not _author_ok(author) or overlaps(m.start(), m.end()):
            continue
        found.append({"author": author, "year": m.group(2), "start": m.start(), "end": m.end()})

    found.sort(key=lambda f: f["start"])
    return found


def citations_by_slide(notes_by_slide: Dict[int, str]) -> Dict[Tuple[str, str], List[int]]:
    """Map {(author, year) -> [slide numbers]}."""
    out: Dict[Tuple[str, str], List[int]] = {}
    for num, body in notes_by_slide.items():
        for c in extract_citations(body):
            out.setdefault((c["author"], c["year"]), []).append(num)
    return out


def _trim(s: str) -> str:
    while s and s[-1] in ".,;:]*_":
        s = s[:-1]
    while s.endswith(")") and s.count(")") > s.count("("):
        s = s[:-1]
        while s and s[-1] in ".,;:":
            s = s[:-1]
    return s


def extract_evidence(text: str) -> List[Dict[str, Any]]:
    """Return evidence items {kind, value, start, end} found in text."""
    text = text or ""
    items: List[Dict[str, Any]] = []
    spans: List[Tuple[int, int]] = []
    for m in _DOI.finditer(text):
        doi = _trim(m.group(1))
        items.append({"kind": "doi", "value": doi, "start": m.start(), "end": m.end()})
        spans.append((m.start(), m.end()))
    for m in _URL.finditer(text):
        if any(s <= m.start() < e for s, e in spans):
            continue
        items.append({"kind": "url", "value": _trim(m.group(0)), "start": m.start(), "end": m.end()})
    for m in _ISBN.finditer(text):
        isbn = re.sub(r"[\s\-]", "", m.group(1)).upper()
        items.append({"kind": "isbn", "value": isbn, "start": m.start(), "end": m.end()})
    items.sort(key=lambda i: i["start"])
    return items


def field_segments(notes: str, labels: Optional[List[str]] = None) -> List[Tuple[str, str, str]]:
    """Return list of (label, body, item_header) for each SBC field in notes."""
    labels = labels or SBC_LABELS
    label_re = re.compile(
        r"(?im)^[ \t]*\*?[ \t]*("
        + "|".join(re.escape(x) for x in sorted(labels, key=len, reverse=True))
        + r")[ \t]*:"
    )
    matches = list(label_re.finditer(notes or ""))
    result = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(notes)
        body = notes[m.end():end]
        before = notes[:m.start()]
        heads = re.findall(r"(?m)^[ \t]*\*?[ \t]*([^\n:]{2,90}):[ \t]*$", before)
        heads = [
            h.strip()
            for h in heads
            if h.strip() not in labels
            and not h.strip().upper().startswith(("SLIDE BODY COVERAGE", "• SLIDE BODY"))
        ]
        result.append((m.group(1), body, (heads[-1] if heads else "(item)")))
    return result


def _sources_lines(text: str) -> List[str]:
    return [ln for ln in (text or "").splitlines() if re.match(r"^\s*[\*\-•]?\s*Sources?\s*:", ln, re.I)]


def extract_numbers(text: str) -> List[str]:
    """Metric-like numbers in a claim."""
    text = re.sub(_PAREN.pattern, " ", text or "")
    text = _URL.sub(" ", text)
    nums: List[str] = []
    for m in _NUM.finditer(text):
        raw, pct = m.group(1), m.group(2)
        val = raw.replace(",", "")
        if not pct and re.fullmatch(r"(?:19|20)\d{2}", val):
            continue
        if not pct and "." not in val and int(val) < 10:
            continue
        if val not in nums:
            nums.append(val)
    return nums


def _number_on_page(num: str, page_text: str) -> bool:
    pat = re.escape(num).replace(r"\.", r"\.")
    return re.search(r"(?<![\d.])" + pat + r"(?![\d])", page_text) is not None


def check_example_sourcing(notes: str, labels: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Structural check: Concrete Example ends with Sources: line with URL/DOI/ISBN."""
    out = []
    for label, body, item in field_segments(notes, labels):
        if label != "Concrete Example":
            continue
        src_lines = _sources_lines(body)
        ev = [e for ln in src_lines for e in extract_evidence(ln)]
        claim_text = "\n".join(ln for ln in body.splitlines() if ln not in src_lines)
        out.append({
            "item": item[:80],
            "has_sources": bool(src_lines),
            "evidence_count": len(ev),
            "numbers": extract_numbers(claim_text),
            "status": "SOURCED" if ev else "NO_SOURCE",
        })
    return out


def _fetch(
    url: str,
    accept: Optional[str] = None,
    ua: str = BROWSER_UA,
    timeout: int = DEFAULT_HTTP_TIMEOUT,
) -> Tuple[int, str, str, bytes]:
    """GET url -> (status, final_url, content_type, text)."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": ua, "Accept": accept or "text/html,*/*;q=0.8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = r.headers.get("Content-Type", "")
            raw = r.read(MAX_DOWNLOAD_BYTES)
            return r.status, r.geturl(), ctype, raw
    except urllib.error.HTTPError as e:
        return e.code, url, e.headers.get("Content-Type", "") if e.headers else "", b""


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _csl_years(m: Dict[str, Any]) -> Set[int]:
    years: Set[int] = set()
    for k in ("issued", "published-print", "published-online", "published"):
        parts = (m.get(k) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            years.add(int(parts[0][0]))
    return years


def check_doi(
    doi: str,
    author: Optional[str] = None,
    year: Optional[Any] = None,
    timeout: int = DEFAULT_HTTP_TIMEOUT,
) -> Dict[str, Any]:
    """Resolve a DOI and compare it to in-text citation."""
    meta = None
    try:
        st, _u, _c, raw = _fetch(
            "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/"),
            accept="application/json",
            ua=CROSSREF_UA,
            timeout=timeout,
        )
        if st == 200:
            meta = json.loads(raw.decode("utf-8", "replace")).get("message")
        elif st not in (400, 404):
            return {"status": "UNREACHABLE", "detail": f"Crossref HTTP {st}"}

        if meta is None:
            st, _u, _c, raw = _fetch(
                "https://doi.org/" + doi,
                accept="application/vnd.citationstyles.csl+json",
                timeout=timeout,
            )
            if st == 200:
                try:
                    meta = json.loads(raw.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    meta = None
            elif st not in (400, 404):
                return {"status": "UNREACHABLE", "detail": f"doi.org HTTP {st}"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"status": "UNREACHABLE", "detail": f"network: {e.__class__.__name__}"}

    if not meta:
        return {"status": "NOT_FOUND", "detail": "DOI does not resolve (Crossref + doi.org)"}

    title = meta.get("title")
    title = title[0] if isinstance(title, list) and title else (title or "")
    container = meta.get("container-title")
    container = container[0] if isinstance(container, list) and container else (container or "")
    families = [_fold(a.get("family") or a.get("name") or "") for a in meta.get("author", []) or []]
    years = _csl_years(meta)
    ev = {
        "title": title,
        "container": container,
        "years": sorted(years),
        "authors": families[:6],
        "type": meta.get("type", ""),
    }
    problems = []
    if author:
        first = _fold(re.split(r"[\s,&]+", author.strip())[0]).rstrip(".")
        if families and first and not any(first in f or f in first for f in families if f):
            problems.append(f"first author '{author.split()[0]}' not among {families[:4]}")

    year_note = None
    if year and years:
        y = int(str(year)[:4])
        if not any(abs(y - yy) <= 1 for yy in years):
            book = "book" in ev["type"] or "monograph" in ev["type"]
            if book and min(years) > y:
                year_note = f"record year {sorted(years)} is later than cited {y} (reissue/edition?)"
            else:
                problems.append(f"cited year {y} vs record {sorted(years)}")

    if problems:
        return {"status": "MISMATCH", "detail": "; ".join(problems), "evidence": ev}
    if year_note:
        return {"status": "EXISTS_SUPPORT_UNCONFIRMED", "detail": year_note, "evidence": ev}
    return {
        "status": "VERIFIED",
        "detail": f"{title[:90]} — {container}".strip(" —"),
        "evidence": ev,
    }


def check_isbn(isbn: str, year: Optional[Any] = None, timeout: int = DEFAULT_HTTP_TIMEOUT) -> Dict[str, Any]:
    try:
        st, _u, _c, raw = _fetch(
            f"https://openlibrary.org/isbn/{isbn}.json",
            accept="application/json",
            timeout=timeout,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"status": "UNREACHABLE", "detail": f"network: {e.__class__.__name__}"}

    if st == 404:
        return {"status": "NOT_FOUND", "detail": "ISBN not in OpenLibrary"}
    if st != 200:
        return {"status": "UNREACHABLE", "detail": f"OpenLibrary HTTP {st}"}

    try:
        meta = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return {"status": "UNREACHABLE", "detail": "OpenLibrary returned non-JSON"}

    title = meta.get("title", "")
    pub = str(meta.get("publish_date", ""))
    ev = {"title": title, "publish_date": pub}
    if year and pub and str(year)[:4] not in pub:
        return {
            "status": "EXISTS_SUPPORT_UNCONFIRMED",
            "detail": f"ISBN edition dated '{pub}', cited {year} — check edition",
            "evidence": ev,
        }
    return {"status": "VERIFIED", "detail": f"{title[:90]} ({pub})", "evidence": ev}


def _page_text(raw: bytes, ctype: str) -> Optional[Tuple[str, str]]:
    if "pdf" in (ctype or "").lower():
        return None
    t = raw.decode("utf-8", "replace")
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", t)
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"(?<=\d),(?=\d{3})", "", t)
    t = re.sub(r"\s+", " ", t)
    return (html.unescape(title.group(1)).strip() if title else ""), t


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a: Any, **k: Any) -> None:
        return None


def _online() -> bool:
    try:
        socket.gethostbyname("doi.org")
        return True
    except OSError:
        return False


def _ephemeral_result(url: str, timeout: int = DEFAULT_HTTP_TIMEOUT, resolve: bool = True) -> Dict[str, Any]:
    resolved = None
    if resolve:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA}, method="HEAD")
            opener = urllib.request.build_opener(_NoRedirect)
            opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            resolved = e.headers.get("Location") if e.headers else None
        except Exception:
            pass
    return {
        "status": "EPHEMERAL_URL",
        "detail": "search-engine redirect link (expires) — cite the real page"
        + (f": {resolved}" if resolved else ""),
    }


def check_url(
    url: str,
    numbers: Optional[List[str]] = None,
    timeout: int = DEFAULT_HTTP_TIMEOUT,
) -> Dict[str, Any]:
    if any(p in url for p in _EPHEMERAL):
        return _ephemeral_result(url, timeout)
    try:
        st, final, ctype, raw = _fetch(url, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        if ("Name or service not known" in str(reason) or "nodename nor servname" in str(reason)) and _online():
            return {"status": "BROKEN_LINK", "detail": f"domain does not resolve ({reason})"}
        return {"status": "UNREACHABLE", "detail": f"network: {reason}"}

    if st in (404, 410):
        return {"status": "BROKEN_LINK", "detail": f"HTTP {st}"}
    if st in (401, 403, 429, 999):
        return {
            "status": "EXISTS_SUPPORT_UNCONFIRMED",
            "detail": f"HTTP {st} — site blocks automated checks; open it manually",
        }
    if st >= 500:
        return {"status": "UNREACHABLE", "detail": f"HTTP {st}"}
    if st >= 400:
        return {"status": "BROKEN_LINK", "detail": f"HTTP {st}"}

    parsed = _page_text(raw, ctype)
    if parsed is None:
        return {
            "status": "EXISTS_SUPPORT_UNCONFIRMED",
            "detail": "PDF — live, but figures not machine-checked; confirm manually",
            "evidence": {"final_url": final},
        }
    title, text = parsed
    head = (title + " " + text[:1500]).lower()
    if re.search(
        r"\b(page not found|404 not found|error 404|page does not exist|page (?:you requested|cannot be found))\b",
        head,
    ):
        return {"status": "BROKEN_LINK", "detail": f"soft 404 ('{title[:60]}')"}

    ev = {"title": title[:120], "final_url": final}
    if numbers:
        found = [n for n in numbers if _number_on_page(n, text)]
        ev["numbers_found"] = found
        ev["numbers_missing"] = [n for n in numbers if n not in found]
    return {"status": "VERIFIED", "detail": title[:90] or final, "evidence": ev}


def _first_token_key(author: str, year: Any) -> str:
    tok = re.split(r"[\s,&]+", _fold(author).strip())[0].rstrip(".")
    return f"{tok}|{str(year)[:4]}"


def _sources_entries(notes: str) -> List[Dict[str, Any]]:
    entries = []
    for ln in _sources_lines(notes):
        body = re.sub(r"^\s*[\*\-•]?\s*Sources?\s*:\s*", "", ln, flags=re.I)
        for part in re.split(r";\s+(?=[A-Z0-9])", body):
            m = re.match(r"^\s*(.+?)\s*\(\s*((?:19|20)\d{2}[a-z]?)\s*\)", part)
            ev = extract_evidence(part)
            entries.append({
                "author": _clean_author(m.group(1)) if m else None,
                "year": m.group(2) if m else None,
                "text": part.strip()[:160],
                "evidence": ev,
            })
    return entries


def _example_numbers_for(notes: str, evidence: List[Dict[str, Any]]) -> Optional[List[str]]:
    vals = {e["value"] for e in evidence}
    for label, body, _item in field_segments(notes):
        if label != "Concrete Example":
            continue
        src = _sources_lines(body)
        if any(e["value"] in vals for ln in src for e in extract_evidence(ln)):
            claim = "\n".join(ln for ln in body.splitlines() if ln not in src)
            return extract_numbers(claim)
    return None


def _check_evidence(
    e: Dict[str, Any],
    author: Optional[str],
    year: Optional[Any],
    offline: bool,
    timeout: int,
    url_cache: Dict[Any, Any],
    doi_cache: Dict[Any, Any],
    numbers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if e["kind"] == "url" and any(p in e["value"] for p in _EPHEMERAL):
        return _ephemeral_result(e["value"], timeout, resolve=not offline)
    if offline:
        return {"status": "UNREACHABLE", "detail": "offline mode — not checked"}
    if e["kind"] == "doi":
        ck = (e["value"].lower(), author, year)
        if ck not in doi_cache:
            doi_cache[ck] = check_doi(e["value"], author, year, timeout)
        return dict(doi_cache[ck])
    if e["kind"] == "isbn":
        return check_isbn(e["value"], year, timeout)
    ck = (e["value"], tuple(numbers or ()))
    if ck not in url_cache:
        url_cache[ck] = check_url(e["value"], numbers, timeout)
    return dict(url_cache[ck])


def verify_notes(
    notes_by_slide: Dict[int, str],
    cache_root: Optional[str] = None,
    ttl_days: int = DEFAULT_TTL_DAYS,
    offline: bool = False,
    record: bool = True,
    timeout: int = DEFAULT_HTTP_TIMEOUT,
    record_new: Optional[bool] = None,
) -> Dict[str, Any]:
    """Verify every reference in {slide: notes} dictionary."""
    if record_new is not None:
        record = record_new
    data = citation_db.load(cache_root) if cache_root else {"citations": {}, "_load_failed": True}
    findings: List[Dict[str, Any]] = []
    examples: List[Dict[str, Any]] = []
    url_cache: Dict[Any, Any] = {}
    doi_cache: Dict[Any, Any] = {}
    to_record: List[Dict[str, Any]] = []

    for slide, notes in sorted(notes_by_slide.items()):
        notes = notes or ""
        ex_checks = check_example_sourcing(notes)
        for ex in ex_checks:
            if ex["status"] == "NO_SOURCE":
                findings.append({
                    "slide": slide,
                    "kind": "example",
                    "ref": ex["item"],
                    "citation": None,
                    "status": "NO_SOURCE",
                    "detail": "Concrete Example has no 'Sources:' line with a URL/DOI/ISBN",
                })

        sources = _sources_entries(notes)
        by_key: Dict[str, List[Any]] = {}
        by_tok: Dict[str, List[Any]] = {}
        for se in sources:
            if se["author"] and se["evidence"]:
                by_key.setdefault(citation_db.normalise_key(se["author"], se["year"]), []).extend(se["evidence"])
                by_tok.setdefault(_first_token_key(se["author"], se["year"]), []).extend(se["evidence"])

        attached_ev: Set[Tuple[str, str]] = set()
        cits: List[Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]] = []

        for line in notes.splitlines():
            if re.match(r"^\s*[\*\-•]?\s*Sources?\s*:", line, re.I):
                continue
            lc = extract_citations(line)
            le = extract_evidence(line)
            inline: Dict[int, List[Dict[str, Any]]] = {}
            for e in le:
                prev = [c for c in lc if c["end"] <= e["start"]]
                if prev:
                    inline.setdefault(id(prev[-1]), []).append(e)
            for c in lc:
                cits.append((c, inline.get(id(c), [])))
            for e in le:
                if not any(e in v for v in inline.values()):
                    cits.append((None, [e]))

        seen: Set[Any] = set()
        for c, inline_ev in cits:
            if c is None:
                e = inline_ev[0]
                if (e["kind"], e["value"]) in seen:
                    continue
                seen.add((e["kind"], e["value"]))
                res = _check_evidence(e, None, None, offline, timeout, url_cache, doi_cache)
                findings.append({
                    "slide": slide,
                    "kind": e["kind"],
                    "ref": e["value"],
                    "citation": None,
                    **res,
                })
                continue

            k = citation_db.normalise_key(c["author"], c["year"])
            if k in seen:
                continue
            seen.add(k)
            ev = inline_ev or by_key.get(k) or by_tok.get(_first_token_key(c["author"], c["year"])) or []
            for e in ev:
                attached_ev.add((e["kind"], e["value"]))
            label = f"{c['author']} ({c['year']})"
            status, entry, _left = citation_db.lookup(data, c["author"], c["year"], ttl_days)
            cached_ev = {(entry or {}).get("doi"), (entry or {}).get("url")} - {None, ""}
            if status == "HIT_FRESH" and (not ev or any(e["value"] in cached_ev for e in ev)):
                findings.append({
                    "slide": slide,
                    "kind": "citation",
                    "ref": label,
                    "citation": label,
                    "status": "CACHED",
                    "detail": f"verified {(entry.get('verified_at') or '')[:10]} "
                    f"({entry.get('doi') or entry.get('url') or entry.get('title', '')[:50]})",
                })
                continue
            if not ev:
                findings.append({
                    "slide": slide,
                    "kind": "citation",
                    "ref": label,
                    "citation": label,
                    "status": "UNRESOLVED",
                    "detail": "no DOI/URL/ISBN given and not in the module citation cache",
                })
                continue

            ev_sorted = sorted(ev, key=lambda e: {"doi": 0, "isbn": 1, "url": 2}[e["kind"]])
            nums = _example_numbers_for(notes, ev_sorted)
            res = _check_evidence(
                ev_sorted[0],
                c["author"],
                c["year"],
                offline,
                timeout,
                url_cache,
                doi_cache,
                nums,
            )
            findings.append({
                "slide": slide,
                "kind": ev_sorted[0]["kind"],
                "ref": ev_sorted[0]["value"],
                "citation": label,
                **res,
            })
            if res["status"] == "VERIFIED":
                evd = res.get("evidence") or {}
                to_record.append({
                    "author": c["author"],
                    "year": c["year"],
                    "title": evd.get("title") or label,
                    "doi": ev_sorted[0]["value"] if ev_sorted[0]["kind"] == "doi" else "",
                    "url": ev_sorted[0]["value"] if ev_sorted[0]["kind"] == "url" else "",
                })

        for se in sources:
            for e in se["evidence"]:
                if (e["kind"], e["value"]) in attached_ev or (e["kind"], e["value"]) in seen:
                    continue
                seen.add((e["kind"], e["value"]))
                nums = _example_numbers_for(notes, [e])
                res = _check_evidence(
                    e,
                    se["author"],
                    se["year"],
                    offline,
                    timeout,
                    url_cache,
                    doi_cache,
                    nums,
                )
                findings.append({
                    "slide": slide,
                    "kind": e["kind"],
                    "ref": e["value"],
                    "citation": (f"{se['author']} ({se['year']})" if se["author"] else None),
                    **res,
                })

        for ex in ex_checks:
            if ex["status"] != "SOURCED" or not ex["numbers"]:
                continue
            found, fetched = set(), False
            for f in findings:
                if f.get("slide") == slide and "numbers_found" in (f.get("evidence") or {}):
                    fetched = True
                    found.update(f["evidence"]["numbers_found"])
            if not fetched:
                continue
            missing = [n for n in ex["numbers"] if n not in found]
            examples.append({
                "slide": slide,
                "item": ex["item"],
                "numbers": ex["numbers"],
                "missing": missing,
            })
            if missing and not offline:
                findings.append({
                    "slide": slide,
                    "kind": "claim",
                    "ref": ex["item"],
                    "citation": None,
                    "status": "EXISTS_SUPPORT_UNCONFIRMED",
                    "detail": f"figure(s) not found on the cited page(s): {', '.join(missing)}",
                })

    recorded = 0
    if record and cache_root and not data.get("_load_failed") and to_record and not offline:
        for r in to_record:
            if (
                citation_db.record_entry(
                    cache_root,
                    r["author"],
                    r["year"],
                    title=r["title"],
                    url=r["url"],
                    doi=r["doi"],
                    verified_by="verify_references.py",
                )
                == 0
            ):
                recorded += 1

    counts: Dict[str, int] = {}
    for f in findings:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    blocking = [f for f in findings if f["status"] in BLOCKING]

    return {
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "offline": offline,
        "cache_root": cache_root,
        "counts": counts,
        "blocking": len(blocking),
        "recorded_to_cache": recorded,
        "findings": findings,
        "examples": examples,
    }


def log_override(module_root: str, pptx_path: str, findings: List[Dict[str, Any]], checked_at: str) -> None:
    """Log an explicit --allow-unverified bypass to .reference_overrides.log."""
    if not module_root:
        return
    log_file = os.path.join(module_root, OVERRIDE_LOG)
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            for f in findings:
                if f.get("status") in BLOCKING:
                    fh.write(
                        f"{checked_at}\t{os.path.basename(pptx_path)}\tslide {f.get('slide')}"
                        f"\t{f.get('status')}\t{f.get('citation') or f.get('ref')}\t{f.get('detail', '')}\n"
                    )
    except OSError:
        pass


def gate(
    notes_by_slide: Dict[int, str],
    pptx_path: str,
    allow_unverified: bool = False,
    out: Any = sys.stdout,
) -> bool:
    """Verify before writing. Returns True if the write may proceed."""
    root = citation_db.find_module_root(pptx_path) if pptx_path else None
    rep = verify_notes(notes_by_slide, cache_root=root)
    if not rep["findings"]:
        return True

    if rep["blocking"] == 0:
        return True

    if allow_unverified:
        log_override(root or "", pptx_path, rep["findings"], rep["checked_at"])
        if out:
            print(
                f"⚠️  --allow-unverified: writing despite {rep['blocking']} blocking finding(s) "
                f"(logged to {OVERRIDE_LOG})",
                file=out,
            )
        return True

    if out:
        print(
            f"⛔ Write-back refused: {rep['blocking']} reference finding(s) must be fixed first.\n"
            f"   Fix them (add a DOI/URL, correct the citation, or add a Sources: line), or\n"
            f"   rerun with --allow-unverified to override (logged).",
            file=out,
        )
    return False
