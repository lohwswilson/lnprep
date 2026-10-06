"""Tests for writer_engine direct XML injection, backup, and payload parsing."""

import os
import shutil
import tempfile
import pytest
from pptx import Presentation

from lnprep.core import writer_engine as we
from lnprep.core.common import get_slide_notes_text


@pytest.fixture
def sample_deck():
    tmp_dir = tempfile.mkdtemp(prefix="lnprep-test-deck-")
    deck_path = os.path.join(tmp_dir, "test_deck.pptx")
    prs = Presentation()
    slide_layout = prs.slide_layouts[1]
    slide1 = prs.slides.add_slide(slide_layout)
    slide1.shapes.title.text = "Introduction"
    slide2 = prs.slides.add_slide(slide_layout)
    slide2.shapes.title.text = "Core Principles"
    prs.save(deck_path)

    yield deck_path
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_load_notes_payload():
    valid = '{"slides": [{"slide": 1, "notes": "Test notes"}]}'
    res = we.load_notes_payload(valid)
    assert res["slides"][0]["slide"] == 1

    fenced = "```json\n" + valid + "\n```"
    res_f = we.load_notes_payload(fenced)
    assert res_f["slides"][0]["slide"] == 1

    with pytest.raises(ValueError):
        we.load_notes_payload("this is not json at all")


def test_backup_once(sample_deck):
    bak = we.backup_once(sample_deck)
    assert os.path.exists(bak)
    assert "_backup_" in bak
    # Calling again returns same backup without overwriting
    bak2 = we.backup_once(sample_deck)
    assert bak == bak2


def test_update_slide_xml_injection(sample_deck):
    notes = """--- SPEAKER NOTES ---
⏱ 3.0 min | 🎯 Supply Chain Friction

BRIDGE: "Linking from inventory principles"
NARRATIVE OPENING / HOOK: "When the Suez Canal was blocked, shipping rates tripled overnight."

KEY POINT: "Operational bottlenecks propagate non-linearly across interconnected networks."

--- VISUAL DECONSTRUCTION ---
🎯 VISUAL OBJECTIVE:
Map the ripple effect across European port terminals.

👁️ GAZE DIRECTION:
Look first at the horizontal axis.

🔄 STEP-BY-STEP WALK-THROUGH:
- Step 1: Trace the initial blockage at point A.
- Step 2: Observe queue build-up at port B.

💡 VISUAL PUNCHLINE:
"Single points of failure dictate network capacity."

--- LECTURE NOTES ---
• CORE NARRATIVE:
* MLO Anchor: [MLO 1]

• SLIDE BODY COVERAGE — KEY MECHANISMS:
Supply Chain Friction:
Plain English: Every delay compounds as orders travel upstream.
"""
    res = we.update_slide(sample_deck, 1, notes)
    assert res["updated"] == 1

    # Verify notes readable via python-pptx
    prs = Presentation(sample_deck)
    read_back = get_slide_notes_text(prs.slides[0])
    assert "⏱ 3.0 min" in read_back
    assert "--- SPEAKER NOTES ---" in read_back
    assert "--- VISUAL DECONSTRUCTION ---" in read_back
    assert "--- LECTURE NOTES ---" in read_back
    assert "Supply Chain Friction" in read_back
