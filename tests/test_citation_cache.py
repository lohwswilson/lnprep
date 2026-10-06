"""Tests for citation_db core logic."""

import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
import pytest

from lnprep.core import citation_db as cc


@pytest.fixture
def temp_module_root():
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "LECTURE_NOTES_GUIDE.md"), "w") as f:
        f.write("module: TEST101\n")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_key_normalisation():
    assert (
        cc.normalise_key("Biggs & Tang", "2011")
        == cc.normalise_key("biggs and tang", "2011")
        == cc.normalise_key("Biggs, Tang", "2011")
    )
    assert cc.normalise_key("Chor et al.", "2023") == cc.normalise_key("Chor", "2023")
    assert cc.normalise_key("Smith", "2011a") == cc.normalise_key("Smith", "2011")
    assert cc.normalise_key("Smith", "2011") != cc.normalise_key("Smith", "2012")
    assert cc.normalise_key("Smith", "2011") != cc.normalise_key("Smyth", "2011")


def test_empty_cache_miss(temp_module_root):
    data = cc.load(temp_module_root)
    st, e, left = cc.lookup(data, "Nobody", "1999")
    assert st == "MISS"
    assert e is None


def test_record_and_lookup_hit_fresh(temp_module_root):
    res = cc.record_entry(
        temp_module_root,
        "Biggs & Tang",
        "2011",
        title="Teaching for Quality Learning",
        url="https://example.org/x",
    )
    assert res == 0

    data = cc.load(temp_module_root)
    st, e, left = cc.lookup(data, "Biggs and Tang", "2011")
    assert st == "HIT_FRESH"
    assert e is not None
    assert e.get("url") == "https://example.org/x"
    assert left is not None and 179 < left <= 180
    assert bool(e.get("verified_at"))


def test_default_ttl_and_expiry(temp_module_root):
    assert cc.DEFAULT_TTL_DAYS == 180
    res = cc.record_entry(
        temp_module_root,
        "Biggs & Tang",
        "2011",
        title="Teaching for Quality Learning",
        url="https://example.org/x",
    )
    assert res == 0

    data = cc.load(temp_module_root)
    key = cc.normalise_key("Biggs & Tang", "2011")

    # 31 days old -> Fresh
    data["citations"][key]["verified_at"] = (
        datetime.now(timezone.utc).astimezone() - timedelta(days=31)
    ).isoformat()
    cc.save(temp_module_root, data)
    st, _, left = cc.lookup(cc.load(temp_module_root), "Biggs & Tang", "2011")
    assert st == "HIT_FRESH"
    assert left is not None and 148 < left <= 150

    # 181 days old -> Stale
    data["citations"][key]["verified_at"] = (
        datetime.now(timezone.utc).astimezone() - timedelta(days=181)
    ).isoformat()
    cc.save(temp_module_root, data)
    st, _, _ = cc.lookup(cc.load(temp_module_root), "Biggs & Tang", "2011")
    assert st == "HIT_STALE"

    # Widened TTL to 365 -> Fresh
    st2, _, _ = cc.lookup(cc.load(temp_module_root), "Biggs & Tang", "2011", ttl_days=365)
    assert st2 == "HIT_FRESH"


def test_corrupt_cache_handling(temp_module_root):
    cache_f = os.path.join(temp_module_root, ".citation_cache.json")
    with open(cache_f, "w") as f:
        f.write("{not valid json")

    data = cc.load(temp_module_root)
    assert data.get("_load_failed") is True
    st, e, _ = cc.lookup(data, "Biggs & Tang", "2011")
    assert st == "MISS"

    # Refuse to overwrite corrupt cache
    code = cc.record_entry(temp_module_root, "Someone", "2020", title="Test")
    assert code == 2


def test_require_evidence_to_record(temp_module_root):
    code = cc.record_entry(temp_module_root, "Nobody", "1999")
    assert code == 2


def test_prune_and_hits(temp_module_root):
    cc.record_entry(temp_module_root, "OldAuthor", "2020", title="Old Paper")
    cc.record_entry(temp_module_root, "FreshAuthor", "2025", title="Fresh Paper")

    data = cc.load(temp_module_root)
    old_key = cc.normalise_key("OldAuthor", "2020")
    data["citations"][old_key]["verified_at"] = (
        datetime.now(timezone.utc).astimezone() - timedelta(days=200)
    ).isoformat()
    cc.save(temp_module_root, data)

    cc.log_hit(temp_module_root, "OldAuthor", "2020")
    data_after_hit = cc.load(temp_module_root)
    assert data_after_hit["citations"][old_key]["hits"] == 1

    kept, dropped, keys = cc.prune(temp_module_root, ttl_days=180)
    assert dropped == 1
    assert kept == 1
    d_pruned = cc.load(temp_module_root)
    assert old_key not in d_pruned["citations"]
    assert cc.normalise_key("FreshAuthor", "2025") in d_pruned["citations"]
