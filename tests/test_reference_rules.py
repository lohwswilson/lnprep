"""Tests for reference verification rules and gates."""

import http.server
import os
import shutil
import socketserver
import tempfile
import threading

import pytest

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
    devnull = open(os.devnull, "w")
    try:
        with open(os.path.join(deck_dir, "LECTURE_NOTES_GUIDE.md"), "w") as f:
            f.write("# guide\n")
        deck = os.path.join(deck_dir, "deck.pptx")

        bad = "Item:\n\nConcrete Example: For example, Grab moved 30% more deliveries.\n\nBigger Picture: x"

        assert vr.gate({1: bad}, deck, out=devnull) is False
        assert vr.gate({1: bad}, deck, allow_unverified=True, out=devnull) is True

        override_log = os.path.join(deck_dir, vr.OVERRIDE_LOG)
        assert os.path.exists(override_log)
        with open(override_log, "r") as f:
            assert "NO_SOURCE" in f.read()

        assert vr.gate({1: 'BRIDGE: "hello"'}, deck, out=devnull) is True
    finally:
        devnull.close()
        shutil.rmtree(deck_dir, ignore_errors=True)


def test_gate_blocks_when_the_network_is_unreachable(monkeypatch):
    """A transport failure means the check never happened, so it must block.

    Regression: UNREACHABLE was absent from BLOCKING, so an offline machine, a
    captive portal, or a Crossref 429 rate-limit produced exactly the same gate
    decision as a citation that had actually been verified.
    """
    def unreachable_doi(*args, **kwargs):
        return {"status": "UNREACHABLE", "detail": "network: TimeoutError"}

    monkeypatch.setattr(vr, "check_doi", unreachable_doi)

    deck_dir = tempfile.mkdtemp(prefix="vr-gate-")
    devnull = open(os.devnull, "w")
    try:
        with open(os.path.join(deck_dir, "LECTURE_NOTES_GUIDE.md"), "w") as f:
            f.write("# guide\n")
        deck = os.path.join(deck_dir, "deck.pptx")
        notes = {1: "Deep Research:\n- Chor (2023) argued X (doi:10.1234/abc123).\n"}

        rep = vr.verify_notes(notes, cache_root=deck_dir)
        assert rep["blocking"] >= 1
        assert "UNREACHABLE" in rep["counts"]

        assert vr.gate(notes, deck, out=devnull) is False
        # The documented escape hatch still works.
        assert vr.gate(notes, deck, allow_unverified=True, out=devnull) is True
    finally:
        devnull.close()
        shutil.rmtree(deck_dir, ignore_errors=True)


def test_check_url_refuses_private_loopback_and_metadata_hosts():
    """Notes are often LLM-authored, so a URL in them is untrusted input.

    Without a host check the tool would fetch loopback, RFC1918 and cloud-metadata
    addresses from the user's machine and echo the page title back.
    """
    for url in (
        "http://127.0.0.1:8000/secret",
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        "http://10.0.0.5/admin",
        "http://192.168.1.1/",
        "http://[::1]:9000/",
        "http://localhost:8080/",
        "file:///etc/hosts",
    ):
        res = vr.check_url(url)
        assert res["status"] == "BROKEN_LINK", url
        assert "refused" in res["detail"], url


def test_fetch_blocks_a_redirect_into_a_private_address(monkeypatch):
    """A public URL must not be able to bounce the fetcher into loopback or metadata."""
    real_is_public = vr._is_public_host
    # Relax only the first hop so the local test server is reachable; every redirect
    # target still goes through the real check.
    monkeypatch.setattr(
        vr, "_is_public_host", lambda host: True if host == "127.0.0.1" else real_is_public(host)
    )

    class RedirectToMetadata(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()

        def log_message(self, *args):
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), RedirectToMetadata) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        with pytest.raises(vr.BlockedFetchError, match="blocked address"):
            vr._fetch(f"http://127.0.0.1:{port}/", timeout=5)
        srv.shutdown()


def test_check_url_fails_closed_on_non_2xx_and_empty_bodies(monkeypatch):
    """A 3xx out of the redirect loop, or a 2xx with an empty body, used to fall
    through to VERIFIED and then be written into the cache for 180 days."""
    monkeypatch.setattr(vr, "_url_is_fetchable", lambda url: (True, ""))

    # 1xx and 3xx are not retrievable pages. (2xx stays VERIFIED provided it has a
    # body — 299 with content is treated exactly like 200 with content.)
    for status in (100, 300, 301, 302, 307, 308):
        monkeypatch.setattr(
            vr, "_fetch", lambda *a, _s=status, **k: (_s, "https://x/", "text/html", b"<title>x</title>")
        )
        assert vr.check_url("https://example.org/a")["status"] == "UNREACHABLE", status

    monkeypatch.setattr(vr, "_fetch", lambda *a, **k: (200, "https://x/", "text/html", b""))
    assert vr.check_url("https://example.org/a")["status"] == "UNREACHABLE"

    monkeypatch.setattr(
        vr, "_fetch", lambda *a, **k: (200, "https://x/", "text/html", b"<title>Real Page</title>body")
    )
    assert vr.check_url("https://example.org/a")["status"] == "VERIFIED"
