"""Tests for reference verification rules and gates."""

import os
import tempfile

from lnprep.core import audit_engine as sa
from lnprep.core import common
from lnprep.core import ref_verifier as vr


def test_citation_extraction():
    cits = vr.citations_by_slide({
        1: (
            "Freeman (1984) founded it; Mitchell, Agle & Wood (1997) added salience; "
            "(Donaldson & Preston, 1995; Camm et al., 2024) agree; Freeman, R.E. (1984) again. "
            "PSA grew (PSA International, 2025). Revenue was (USD 2.1 billion in 2024) and "
            "Contemporary Frontier (2024-2026) is a label, as is (January 2025)."
        )
    })
    keys = set(cits)
    assert ("Freeman", "1984") in keys
    assert ("Mitchell, Agle & Wood", "1997") in keys
    assert ("Donaldson & Preston", "1995") in keys
    assert ("Camm et al.", "2024") in keys
    assert ("PSA International", "2025") in keys
    assert not any("USD" in a for a, _ in keys)
    assert not any(a.startswith(("Contemporary", "Frontier", "January")) for a, _ in keys)


def test_evidence_extraction():
    ev = vr.extract_evidence(
        "see (doi:10.5465/amr.1997.9711022105). Also https://doi.org/10.1177/0149206324131185 "
        "and https://example.org/page). ISBN 978-0-273-01913-8."
    )
    kinds = [(e["kind"], e["value"]) for e in ev]
    assert ("doi", "10.5465/amr.1997.9711022105") in kinds
    assert ("doi", "10.1177/0149206324131185") in kinds
    assert ("url", "https://example.org/page") in kinds
    assert ("isbn", "9780273019138") in kinds


def test_numbers_in_claims():
    nums = vr.extract_numbers(
        "handled 40.9 million TEUs in 2024, up 5.5% and 1,200 trucks, Tier 1 (PSA, 2025)"
    )
    assert nums == ["40.9", "5.5", "1200"]


def test_concrete_example_sourcing():
    gold = common.GOLD_SBC_EXAMPLE
    ex = vr.check_example_sourcing(gold)
    assert [e["status"] for e in ex] == ["SOURCED"]
    assert ex[0]["evidence_count"] == 3

    bad = "Item:\n\nConcrete Example: For example, Grab moved 30% more deliveries.\n\nBigger Picture: x"
    assert vr.check_example_sourcing(bad)[0]["status"] == "NO_SOURCE"

    src_no_link = bad.replace("deliveries.", "deliveries.\n\nSources: Grab (2025) annual report")
    assert vr.check_example_sourcing(src_no_link)[0]["status"] == "NO_SOURCE"
    assert sa.audit_example_sources(bad)["status"] == "EXAMPLE_UNSOURCED"


def test_statuses_with_stubbed_network(monkeypatch):
    calls = []

    def fake_doi(doi, author=None, year=None, timeout=0):
        calls.append(doi)
        if doi.startswith("10.9999"):
            return {"status": "NOT_FOUND", "detail": "stub"}
        if year == "2024" and "1997" in doi:
            return {"status": "MISMATCH", "detail": "cited year 2024 vs record [1997]"}
        return {"status": "VERIFIED", "detail": "stub", "evidence": {"title": "T"}}

    def fake_url(url, numbers=None, timeout=0):
        calls.append(url)
        if "dead" in url:
            return {"status": "BROKEN_LINK", "detail": "HTTP 404"}
        return {
            "status": "VERIFIED",
            "detail": "stub",
            "evidence": {"title": "Page", "numbers_found": list(numbers or []), "numbers_missing": []},
        }

    def fake_isbn(isbn, year=None, timeout=0):
        calls.append(isbn)
        return {"status": "VERIFIED", "detail": "stub", "evidence": {"title": "Book"}}

    monkeypatch.setattr(vr, "check_doi", fake_doi)
    monkeypatch.setattr(vr, "check_url", fake_url)
    monkeypatch.setattr(vr, "check_isbn", fake_isbn)

    gold = common.GOLD_SBC_EXAMPLE
    rep = vr.verify_notes({3: gold}, cache_root=None)
    assert rep["blocking"] == 0

    notes = (
        "Deep Research:\n- Contemporary Frontier (2024-2026): Mitchell et al. (2024) updated it "
        "(doi:10.5465/amr.1997.9711022105).\n- Smith (2023) found X (doi:10.9999/fake).\n"
        "- Jones (2022) claimed Y.\n- Old link https://example.org/dead-page\n"
        "- Bad https://vertexaisearch.cloud.google.com/grounding-api-redirect/AbC\n"
    )
    st = {(f.get("citation") or f["ref"]): f["status"] for f in vr.verify_notes({1: notes})["findings"]}
    assert st.get("Mitchell et al. (2024)") == "MISMATCH"
    assert st.get("Smith (2023)") == "NOT_FOUND"
    assert st.get("Jones (2022)") == "UNRESOLVED"
    assert st.get("https://example.org/dead-page") == "BROKEN_LINK"
    assert [v for k, v in st.items() if "grounding-api-redirect" in k] == ["EPHEMERAL_URL"]


def test_write_back_gate():
    deck_dir = tempfile.mkdtemp(prefix="vr-gate-")
    with open(os.path.join(deck_dir, "LECTURE_NOTES_GUIDE.md"), "w") as f:
        f.write("# guide\n")
    deck = os.path.join(deck_dir, "deck.pptx")

    bad = "Item:\n\nConcrete Example: For example, Grab moved 30% more deliveries.\n\nBigger Picture: x"
    devnull = open(os.devnull, "w")

    assert vr.gate({1: bad}, deck, out=devnull) is False
    assert vr.gate({1: bad}, deck, allow_unverified=True, out=devnull) is True

    override_log = os.path.join(deck_dir, vr.OVERRIDE_LOG)
    assert os.path.exists(override_log)
    with open(override_log, "r") as f:
        assert "NO_SOURCE" in f.read()

    assert vr.gate({1: 'BRIDGE: "hello"'}, deck, out=devnull) is True
