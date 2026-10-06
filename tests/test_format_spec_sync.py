"""Tests for format spec synchronization and prompt canon."""

import re
from pathlib import Path

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


def _module(tmp_path, guide_body="# Guide\n", spec_body=None):
    module = tmp_path
    (module / common.GUIDE_FILENAME).write_text(guide_body, encoding="utf-8")
    if spec_body is not None:
        (module / common.FORMAT_FILENAME).write_text(spec_body, encoding="utf-8")
    return str(module / "deck.pptx")


def test_parse_guide_tolerates_crlf(tmp_path):
    """A guide last saved by Word on Windows must still parse.

    The fenced-block regexes anchor on a bare "\\n" after the fence, so CRLF matched
    zero blocks and the module's whole context was silently dropped.
    """
    body = '# Guide\n\n## Module Identity\n\n```yaml\nmodule_code: "MO9529"\ninstitution: "Northumbria"\n```\n'
    guide = str(tmp_path / common.GUIDE_FILENAME)
    with open(guide, "w", newline="") as f:
        f.write(body.replace("\n", "\r\n"))

    parsed = common.parse_guide(guide)
    assert parsed.get("module_code") == "MO9529"
    assert parsed.get("institution") == "Northumbria"


def test_load_format_spec_tolerates_crlf(tmp_path):
    """A CRLF NOTES_FORMAT.md must bind, not be discarded for the built-in default."""
    deck = _module(tmp_path, spec_body="```yaml\nsbc_quality:\n  pass_threshold: 3\n```\n")
    spec_path = tmp_path / common.FORMAT_FILENAME
    spec_path.write_text(
        spec_path.read_text(encoding="utf-8").replace("\n", "\r\n"), encoding="utf-8", newline=""
    )

    spec, report = common.load_format_spec(deck)
    assert report["bound"] == [str(spec_path)]
    assert spec["sbc_quality"]["pass_threshold"] == 3


def test_malformed_spec_keys_degrade_instead_of_crashing(tmp_path):
    """A wrongly-shaped spec key used to raise out of the CLI.

    `sbc_quality:` (null) was an AttributeError, `paragraphs.default: 3` a TypeError,
    `min_paragraphs: two` a ValueError, and a label-less sbc_fields entry a KeyError.
    """
    cases = [
        "```yaml\nsbc_quality:\n```\n",
        "```yaml\naudit:\n  paragraphs:\n    default: 3\n```\n",
        "```yaml\naudit:\n  min_paragraphs: two\n```\n",
        "```yaml\nsbc_fields:\n  - require_metaphor: true\n```\n",
        "```yaml\nsbc_quality:\n  markers: not-a-mapping\n```\n",
        "```yaml\nfonts: [1000, 900]\n```\n",
    ]
    for body in cases:
        deck = _module(tmp_path, spec_body=body)
        spec, report = common.load_format_spec(deck)

        # None of these may raise.
        common.render_sbc_spec(spec)
        common.render_zone_a_spec(spec)
        common.spec_labels_list(spec)
        common.spec_bold_labels(spec)
        common.spec_font_sizes(spec)

        assert report["errors"], f"expected a reported error for: {body!r}"
        # The default survives wherever the user's value was unusable.
        assert spec["sbc_quality"]["pass_threshold"] == common.DEFAULT_FORMAT_SPEC["sbc_quality"]["pass_threshold"]


def test_returned_spec_cannot_mutate_the_module_default(tmp_path):
    """The loader used to hand back shallow copies, so one mutating caller changed
    DEFAULT_FORMAT_SPEC for the rest of the process."""
    import copy

    before = copy.deepcopy(common.DEFAULT_FORMAT_SPEC)

    deck = _module(tmp_path)
    spec, _ = common.load_format_spec(deck)
    spec["zones"]["speaker_first"] = "MUTATED"
    spec["sbc_fields"].clear()

    assert common.DEFAULT_FORMAT_SPEC == before
