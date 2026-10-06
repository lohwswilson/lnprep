"""Tests for format spec synchronization and prompt canon."""

from pathlib import Path
import re

from lnprep.core import common
from lnprep.core import prompt_engine as pe

SPEC_PATH = Path(__file__).resolve().parent.parent / "src" / "lnprep" / "resources" / "canonical-notes-spec.md"
FABRICATED = "Mitchell et al. (2024)"


def test_rule_text_in_canonical_spec():
    assert SPEC_PATH.exists()
    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    for name in (
        "KEY_POINT_RULE",
        "PLAIN_ENGLISH_RULE",
        "DEEP_RESEARCH_EVIDENCE_RULE",
        "EXAMPLE_SOURCES_RULE",
        "VISUAL_DECONSTRUCTION_RULE",
    ):
        assert getattr(common, name) in spec_text


def test_gold_examples_in_spec():
    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    assert common.GOLD_KEY_POINT_EXAMPLE in spec_text
    assert common.GOLD_VISUAL_DECONSTRUCTION_EXAMPLE in spec_text
    assert common.GOLD_SBC_EXAMPLE in spec_text
    assert FABRICATED not in common.GOLD_SBC_EXAMPLE


def test_paragraph_rules_configuration():
    pr = common.PARAGRAPH_RULES
    assert pr["key_point"] == {"min": 1, "max": 3, "prose_only": True}
    assert pr["plain_english"] == {"min": 1, "max": 3, "prose_only": True}
    assert common.KEY_POINT_RULE.startswith("KEY POINT: 1–3")
    assert common.PLAIN_ENGLISH_RULE.startswith("Plain English: 1–3")
    assert common.DEFAULT_FORMAT_SPEC["audit"]["paragraphs"] is pr


def test_prompts_carry_rules():
    ctx = {
        "slide": 3,
        "title": "Stakeholders",
        "body_text": "• Major Corporate Stakeholders",
        "visuals": [],
        "existing_notes": "",
    }
    prompt = pe.build_generation_prompt(ctx, {"module_code": "TEST"})
    for name in (
        "KEY_POINT_RULE",
        "PLAIN_ENGLISH_RULE",
        "DEEP_RESEARCH_EVIDENCE_RULE",
        "EXAMPLE_SOURCES_RULE",
        "VISUAL_DECONSTRUCTION_RULE",
        "GOLD_KEY_POINT_EXAMPLE",
        "GOLD_VISUAL_DECONSTRUCTION_EXAMPLE",
        "GOLD_SBC_EXAMPLE",
    ):
        assert getattr(common, name) in prompt

    assert FABRICATED not in prompt
    assert not re.search(r"KEY POINT[^\n]{0,120}2–3 paragraphs", prompt)
    assert not re.search(r"Plain English[^\n]{0,80}\(1–2 paragraphs\)", prompt)

    batch = pe.build_batch_prompt([ctx, dict(ctx, slide=4)], {"module_code": "TEST"})
    assert common.GOLD_SBC_EXAMPLE in batch


def test_legacy_spec_derived():
    assert common.SBC_QUALITY_SPEC == common.render_sbc_spec(common.DEFAULT_FORMAT_SPEC)
    assert common.ZONE_A_HOOK_SPEC == common.render_zone_a_spec(common.DEFAULT_FORMAT_SPEC)
