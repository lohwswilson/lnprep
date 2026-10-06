"""
Per-module citation verification cache with TTL management.
Scope: Per module, stored beside LECTURE_NOTES_GUIDE.md as .citation_cache.json.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from lnprep.config import CACHE_FILENAME, DEFAULT_TTL_DAYS

SCHEMA_VERSION = 1


class CacheUnreadableError(RuntimeError):
    """The cache file exists but cannot be parsed, so it must not be rewritten."""

_AND = re.compile(r"\s*(?:&|\band\b|,)\s*", re.I)
_NONWORD = re.compile(r"[^a-z0-9 ]")
_ETAL = re.compile(r"\s+et\s*al\.?", re.I)


def normalise_key(author: Any, year: Any) -> str:
    """Return a stable cache key for a citation (author surnames + year)."""
    a = str(author or "").strip().lower()
    a = _ETAL.sub("", a)
    a = _AND.sub(" ", a)
    a = _NONWORD.sub("", a)
    a = " ".join(a.split())
    y = str(year or "").strip().lower().rstrip("abcdefghijklmnopqrstuvwxyz")
    return f"{a}|{y}"


def find_module_root(pptx_path: Optional[str] = None, override: Optional[str] = None) -> str:
    """Locate the module root folder containing LECTURE_NOTES_GUIDE.md.

    Accepts either a deck inside the module or the module folder itself. A folder
    argument used to be resolved from its *parent*, so `cache record <module>` wrote
    a cache beside the course directory while `verify`/`write` read one inside it —
    the two halves silently disagreed.
    """
    if override:
        return os.path.abspath(override)
    if not pptx_path:
        return os.path.abspath(os.getcwd())

    start = os.path.abspath(pptx_path)
    current = start if os.path.isdir(start) else os.path.dirname(start)
    fallback = current
    for _ in range(5):
        if os.path.exists(os.path.join(current, "LECTURE_NOTES_GUIDE.md")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return fallback


def cache_path(module_root: str) -> str:
    return os.path.join(module_root, CACHE_FILENAME)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_iso(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def age_days(entry: Dict[str, Any], now: Optional[datetime] = None) -> Optional[float]:
    v = parse_iso(entry.get("verified_at", ""))
    if v is None:
        return None
    now = now or datetime.now(timezone.utc).astimezone()
    if v.tzinfo is None:
        v = v.replace(tzinfo=now.tzinfo)
    return (now - v).total_seconds() / 86400.0


def is_fresh(entry: Dict[str, Any], ttl_days: int = DEFAULT_TTL_DAYS, now: Optional[datetime] = None) -> bool:
    age = age_days(entry, now)
    if age is None:
        return False
    return age <= ttl_days


def load(module_root: str) -> Dict[str, Any]:
    """Load the cache. A corrupt or missing file returns an empty cache structure."""
    p = cache_path(module_root)
    if not os.path.exists(p):
        return {
            "schema_version": SCHEMA_VERSION,
            "module": os.path.basename(module_root),
            "created": now_iso(),
            "citations": {},
        }
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("cache root is not an object")
        if "citations" in data and not isinstance(data["citations"], dict):
            raise ValueError("'citations' is not an object")
        data.setdefault("schema_version", SCHEMA_VERSION)
        data.setdefault("citations", {})
        return data
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        message = f"{CACHE_FILENAME} unreadable ({exc.__class__.__name__}: {exc})"
        sys.stderr.write(
            f"WARNING: {message}; treating as empty. No cached citation will be served.\n"
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "module": os.path.basename(module_root),
            "created": now_iso(),
            "citations": {},
            "_load_failed": True,
            "load_error": message,
        }


def save(module_root: str, data: Dict[str, Any]) -> str:
    """Save the cache atomically.

    A unique temp name plus fsync before os.replace, so two concurrent runs cannot
    interleave into one temp file and a crash cannot leave a truncated cache where a
    valid one stood.
    """
    p = cache_path(module_root)
    directory = os.path.dirname(p) or "."
    fd, tmp = tempfile.mkstemp(prefix=".citation_cache-", suffix=".tmp", dir=directory)
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return p


def lookup(
    data: Dict[str, Any],
    author: Any,
    year: Any,
    ttl_days: Optional[int] = DEFAULT_TTL_DAYS,
    now: Optional[datetime] = None,
) -> Tuple[str, Optional[Dict[str, Any]], Optional[float]]:
    """Return (status, entry, days_left). status in ('HIT_FRESH', 'HIT_STALE', 'MISS')."""
    if data.get("_load_failed"):
        return "MISS", None, None
    key = normalise_key(author, year)
    entry = data.get("citations", {}).get(key)
    if entry is None:
        return "MISS", None, None

    ttl = DEFAULT_TTL_DAYS if ttl_days is None else ttl_days
    a = age_days(entry, now)
    if a is None:
        return "HIT_STALE", entry, None
    left = ttl - a
    if left <= 0:
        return "HIT_STALE", entry, left
    return "HIT_FRESH", entry, left


def record_entry(
    module_root: str,
    author: str,
    year: Any,
    title: str = "",
    url: str = "",
    doi: str = "",
    isbn: str = "",
    verified_at: Optional[str] = None,
    verified_by: str = "live-search",
    ttl_days: int = DEFAULT_TTL_DAYS,
    quiet: bool = True,
) -> int:
    """Record one citation verification into cache."""
    data = load(module_root)
    key = normalise_key(author, year)
    if data.get("_load_failed"):
        sys.stderr.write(
            "ERROR: refusing to record into an unreadable cache (it would discard "
            f"existing entries). Inspect or delete {cache_path(module_root)} and retry.\n"
        )
        return 2

    existing = data["citations"].get(key, {})
    entry = {
        "author": author,
        "year": str(year),
        "title": title or existing.get("title", ""),
        "url": url or existing.get("url", ""),
        "doi": doi or existing.get("doi", ""),
        "isbn": isbn or existing.get("isbn", ""),
        "verified_at": verified_at or now_iso(),
        "verified_by": verified_by or "live-search",
        "ttl_days": ttl_days,
        "hits": existing.get("hits", 0),
    }

    if not (entry["title"] or entry["url"] or entry["doi"] or entry["isbn"]):
        sys.stderr.write(
            "ERROR: refusing to record a citation with no title, url, doi, or isbn. "
            "A cache entry must carry the evidence of a real verification.\n"
        )
        return 2

    data["citations"][key] = entry
    p = save(module_root, data)
    if not quiet:
        print(f"recorded {key!r} -> {p}")
    return 0


def log_hit(module_root: str, author: str, year: Any) -> int:
    """Record that a cached verification was used in an audit trail."""
    data = load(module_root)
    key = normalise_key(author, year)
    if data.get("_load_failed"):
        sys.stderr.write(f"ERROR: no cache entry for {key!r} (cache unreadable); cannot log hit.\n")
        return 2

    entry = data.get("citations", {}).get(key)
    if entry is None:
        sys.stderr.write(f"ERROR: no cache entry for {key!r}; cannot log hit.\n")
        return 2

    entry["hits"] = int(entry.get("hits", 0)) + 1
    entry.setdefault("hit_log", []).append(now_iso())
    entry["hit_log"] = entry["hit_log"][-20:]
    save(module_root, data)
    return 0


def prune(module_root: str, ttl_days: int = DEFAULT_TTL_DAYS, now: Optional[datetime] = None) -> Tuple[int, int, List[str]]:
    """Prune expired entries. Returns (dropped_count, kept_count, dropped_keys).

    Refuses to touch an unreadable cache: rewriting it would discard every entry it
    holds, and the previous version persisted the `_load_failed` sentinel to disk,
    which bricked the cache permanently. It also prunes by the stored key rather than
    re-deriving one from the entry's author/year, which silently dropped any entry
    whose key no longer round-tripped.
    """
    data = load(module_root)
    if data.get("_load_failed"):
        raise CacheUnreadableError(
            f"{data.get('load_error', 'cache unreadable')}. Refusing to prune: that would "
            f"discard every entry. Inspect or delete {cache_path(module_root)} and retry."
        )

    now = now or datetime.now(timezone.utc).astimezone()
    keep: Dict[str, Any] = {}
    dropped: List[str] = []

    for key, entry in data.get("citations", {}).items():
        age = age_days(entry, now)
        if age is not None and (ttl_days - age) > 0:
            keep[key] = entry
        else:
            dropped.append(key)

    data["citations"] = keep
    save(module_root, data)
    return len(dropped), len(keep), dropped


def get_report_data(module_root: str, ttl_days: int = DEFAULT_TTL_DAYS, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Retrieve audit statistics and rows for citation report."""
    data = load(module_root)
    cits = data.get("citations", {})
    now = now or datetime.now(timezone.utc).astimezone()
    fresh = 0
    stale = 0
    rows: List[Dict[str, Any]] = []

    for key, e in sorted(cits.items()):
        age = age_days(e, now)
        if age is None:
            status, left = "HIT_STALE", None
        else:
            left = ttl_days - age
            status = "HIT_FRESH" if left > 0 else "HIT_STALE"
        if status == "HIT_FRESH":
            fresh += 1
        else:
            stale += 1
        rows.append({
            "key": key,
            "author": e.get("author", "?"),
            "year": e.get("year", "?"),
            "verified_at": (e.get("verified_at") or "")[:10],
            # A stale row has no meaningful "days left"; report it as absent rather
            # than as a string the callers then fed to abs().
            "days_left": round(left, 1) if left is not None else None,
            "hits": e.get("hits", 0),
            "title": e.get("title", ""),
            "doi": e.get("doi", ""),
            "url": e.get("url", ""),
            "isbn": e.get("isbn", ""),
            "status": status,
        })

    return {
        "cache_path": cache_path(module_root),
        "module_root": module_root,
        "ttl_days": ttl_days,
        "total": len(cits),
        "fresh": fresh,
        "stale": stale,
        "unreadable": bool(data.get("_load_failed")),
        "load_error": data.get("load_error", ""),
        "entries": rows,
    }
