"""
Prompt compilation engine for single-slide, batched, and enhancement prompts.
Integrates 3-Zone Architecture rules, SBC quality bars, and verified citation cache.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from lnprep.core.citation_db import age_days, DEFAULT_TTL_DAYS, normalise_key
from lnprep.core.common import (
    BATCH_SLIDE_SEP,
    DEEP_RESEARCH_EVIDENCE_RULE,
    DEFAULT_FORMAT_SPEC,
    EXAMPLE_SOURCES_RULE,
    extract_slide_body_text,
    get_slide_title,
    has_visual_content,
    KEY_POINT_RULE,
    PLAIN_ENGLISH_RULE,
    render_sbc_spec,
    render_zone_a_spec,
    SLIDE_END,
    SLIDE_START,
    split_prompt,
    VISUAL_DECONSTRUCTION_RULE,
    GOLD_KEY_POINT_EXAMPLE,
    GOLD_SBC_EXAMPLE,
    GOLD_VISUAL_DECONSTRUCTION_EXAMPLE,
)

BATCH_INSTRUCTION = """

---

## Batch Output Requirement (N slides in this prompt)

You have been given {n} slides above. Return **one JSON object** and nothing
else — no prose, no markdown fence:

```json
{{"slides": [
  {{"slide": <number>, "notes": "<the complete note text exactly as it would be written for that single slide>"}}
]}}
```

Rules:
- One entry per slide listed above. Do not skip, merge, or renumber.
- `notes` is the full note body — both `--- SPEAKER NOTES ---` and
  `--- LECTURE NOTES ---` sections, starting at `--- SPEAKER NOTES ---`.
- Apply the standard above to **every** slide independently. A slide later in
  the batch gets the same depth and rigor as the first.
- Each slide's content above is separated by a `---` rule under its own
  `## Slide Content` header. That is where one slide ends and the next begins —
  do not merge slides into one entry.
- Escape newlines as `\\n` so the value is valid JSON.
"""


def render_cached_citations(
    citations_data: Optional[Dict[str, Any]],
    slide_context: Optional[Dict[str, Any]] = None,
    max_entries: int = 8,
) -> str:
    """Format fresh verified citations from module cache into a prompt section."""
    if not citations_data or not isinstance(citations_data, dict):
        return ""

    citations = citations_data.get("citations", {})
    if not citations:
        return ""

    fresh = []
    for key, entry in citations.items():
        age = age_days(entry)
        if age is not None and age <= DEFAULT_TTL_DAYS:
            fresh.append((key, entry))

    if not fresh:
        return ""

    slide_text = ""
    if slide_context:
        slide_text = (
            f"{slide_context.get('title', '')} "
            f"{slide_context.get('body_text', '')} "
            f"{slide_context.get('existing_notes', '')}"
        ).lower()

    priority = []
    others = []

    for key, entry in fresh:
        author = str(entry.get("author", ""))
        title = str(entry.get("title", ""))
        notes = str(entry.get("notes", ""))
        author_norm = normalise_key(author, "").split("|")[0]
        words = [w for w in re.findall(r"\b[a-zA-Z]{5,}\b", f"{title} {notes}".lower())]
        is_relevant = bool(author_norm and author_norm in slide_text) or any(w in slide_text for w in words)
        if is_relevant:
            priority.append(entry)
        else:
            others.append(entry)

    selected = (priority + others)[:max_entries]
    if not selected:
        return ""

    lines = [
        "## Verified Academic Citations (Pre-Cached for this Module)",
        "The following citations have been verified within their 180-day TTL. "
        "Use them where relevant in `Deep Research:` without needing re-verification:",
    ]
    for e in selected:
        author = e.get("author", "Unknown")
        year = e.get("year", "")
        title = e.get("title", "")
        doi = e.get("doi", "")
        url = e.get("url", "")
        notes = e.get("notes", "")

        entry_line = f"- **{author} ({year})**: *{title}*."
        if doi:
            entry_line += f" DOI: {doi}"
        elif url:
            entry_line += f" URL: {url}"
        if notes:
            entry_line += f" — {notes}"
        lines.append(entry_line)

    return "\n" + "\n".join(lines) + "\n"


def build_generation_prompt(
    slide_context: Dict[str, Any],
    module_context: Dict[str, Any],
    session_info: Optional[Dict[str, Any]] = None,
    spec: Optional[Dict[str, Any]] = None,
    cached_citations: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a structured prompt for single-slide AI note generation."""
    spec = spec or DEFAULT_FORMAT_SPEC
    zone_a_spec_text = render_zone_a_spec(spec)
    sbc_spec_text = render_sbc_spec(spec)
    n_fields = len(spec.get("sbc_fields", []))

    online_spec_text = ""
    if str(spec.get("delivery_mode") or "").lower() == "online":
        eng = spec.get("engagement") or {}
        formats = eng.get("required_formats") or []
        gap = eng.get("max_gap_minutes", 12)
        bits = []
        if "chat" in formats:
            bits.append(
                "**Chat/poll prompt** — at least one in the deck. A remote cohort will\n"
                "  not unmute but it will type: a chat waterfall (\"type now, don't press\n"
                "  enter until I say\"), a poll, or \"type the number you'd choose\"."
            )
        if "breakout_deliverable" in formats:
            bits.append(
                "**Breakout with a deliverable and a named reporter** — every room\n"
                "  produces one artifact (a number, a ranked list, a one-line\n"
                "  recommendation) and names who reports it back."
            )
        online_spec_text = f"""

## Online Delivery Requirements (this module's spec says delivery_mode: online)

This session is delivered **online**, and `sbc_audit.py` enforces the cadence rule.

REQUIRED interaction formats:
{chr(10).join('  ' + b for b in bits)}

**Cadence: no more than {gap} minutes of continuous monologue without an
interaction.** An interaction is any of: an ACTIVITY block, a SOCRATIC PROMPT /
COLD CALL, a quiz/poll/chat prompt, or a TEACHER GUIDANCE block.
"""

    module_code = module_context.get("module_code", "UNKNOWN")
    module_name = module_context.get("module_name", "Unknown Module")
    institution = module_context.get("institution", "Unknown Institution")
    level = module_context.get("level", "Intermediate")
    class_size = module_context.get("class_size", "30")
    style = module_context.get("style", "generic")

    style_instructions = {
        "strategic-case-based": (
            "Use Harvard-style case methods. Include Asian business context, "
            "supply chain crisis examples, operations mapping, and peer learning activities. "
            "Reference real companies and recent (2024-2026) supply chain events."
        ),
        "practical": (
            "Focus on employability skills. Include hands-on tool references, "
            "step-by-step demonstrations, and direct exam alignment."
        ),
        "analytical": (
            "Emphasise research methodology, data evaluation, consumer behavior, "
            "and structured analytical frameworks."
        ),
        "theoretical": (
            "Focus on strategic decisions, corporate governance, decision frameworks, "
            "and multi-stakeholder trade-offs."
        ),
    }
    style_guide = style_instructions.get(style, "Balanced academic approach.")

    level_instructions = {
        "Foundational": "Use clear definitions, step-by-step explanations, concrete everyday analogies.",
        "Intermediate": "Use industry frameworks, tool walkthroughs, case cause-and-effect mappings.",
        "Advanced": "Use critical synthesis, multi-stakeholder trade-offs, recent Google Scholar references.",
    }
    level_guide = level_instructions.get(level, level_instructions["Intermediate"])

    if isinstance(class_size, str) and "+" in class_size:
        size_num = int(class_size.replace("+", ""))
    else:
        size_num = int(class_size) if str(class_size).isdigit() else 30

    if size_num > 35:
        activity_guide = "Use real-time polls (Mentimeter), anonymous Q&A, rapid checks for understanding."
    elif size_num >= 20:
        activity_guide = "Use Think-Pair-Share, small group worksheets, structured team brainstorms."
    else:
        activity_guide = "Use debates, role-play, peer feedback, interactive boards."

    session_block = ""
    if session_info:
        session_block = f"""
## Session Context
- Session {session_info.get('number', '?')}: {', '.join(session_info.get('topics', ['Unknown']))}
- Format: {session_info.get('format', 'Unknown')}
- Date: {session_info.get('date', 'Unknown')}
"""

    citations_block = ""
    if cached_citations:
        rendered = render_cached_citations(cached_citations, slide_context=slide_context)
        if rendered:
            citations_block = f"\n{rendered.strip()}\n"

    prompt = f"""# Lecture Note Generation Task

## Module Context
- **Module:** {module_code} — {module_name}
- **Institution:** {institution}
- **Level:** {level}
- **Class Size:** {class_size}
- **Teaching Style:** {style}

## Pedagogical Guidelines
- **Level approach:** {level_guide}
- **Style approach:** {style_guide}
- **Activity design:** {activity_guide}
{session_block}{citations_block}
## Slide Content

**Slide {slide_context['slide']}: {slide_context['title']}**

### Body Text
{slide_context['body_text'] if slide_context['body_text'] else '(No body text — title slide or visual-only slide)'}

### Visual Elements
{json.dumps(slide_context['visuals'], indent=2) if slide_context['visuals'] else '(No visual elements detected)'}

### Existing Notes
{slide_context['existing_notes'][:500] if slide_context['existing_notes'] else '(No existing notes — generate from scratch)'}

---

## Required Output Format

Generate lecture notes following this EXACT structure:

```
--- SPEAKER NOTES ---
⏱ X.X min | 🎯 [Hook Title / Pedagogical Focus]

BRIDGE: "Verbatim link from previous slide's key concept"
NARRATIVE OPENING / HOOK: "Detailed verbatim delivery script (1–2 paragraphs) using one of the 4 archetypes (Crisis Dilemma, Paradox, Trade-off, or Metric) setting up real-world operational stakes with specific context."
[Optional 2nd paragraph of NARRATIVE OPENING for deeper operational context and dramatic tension]

KEY POINT: "Paragraph 1 (required): the core principle — what it is and why it matters."
[Optional paragraph 2, after a blank line: the mechanism, trade-off, or organisational friction]
[Optional paragraph 3, after a blank line: the strategic consequence and assessment relevance]

SOCRATIC PROMPT / COLD CALL: "Polarizing operational dilemma question to throw to the room to spark debate"
COMMON STUDENT MISCONCEPTION: "Anticipated conceptual error or pitfall in coursework/exams"
ACTIVITY (Format, N min): "Debate, mapping, or interactive exercise prompt"
TEACHER GUIDANCE & EXPECTED ANSWERS:

     - Expected: What students typically answer
     - Guidance: How to push superficial responses to deeper analysis
     - Assessment Link: How this connects to the assignment
     - Key Insight: The takeaway students should walk away with
VIDEO CUE (<length>): "<title>" — <channel> — <url> — <play cue> (include when video recommendations or media cues are present)
TRANSITION: "Verbatim bridge to the next slide"

--- VISUAL DECONSTRUCTION ---
(REQUIRED when the slide contains a diagram, framework, chart, table, SmartArt, process flow, or image. OMIT entirely for text-only, agenda, or quote slides)

🎯 VISUAL OBJECTIVE:
[1 sentence stating the core relationship, mechanism, or data insight this graphic proves]

👁️ GAZE DIRECTION (Where to point first):
"Direct students' eyes to [specific starting point: e.g. horizontal axis, top-left input node, baseline quadrant]."

🔄 STEP-BY-STEP WALK-THROUGH:
- Step 1 [Baseline / Inputs]: "Trace the initial flow from [Point A] to [Point B]..."
- Step 2 [Mechanism / Interaction]: "Show how [Variable X] influences [Variable Y]..."
- Step 3 [Friction / Non-linear Inflection Point]: "Direct attention to [the non-linear elbow / bottleneck / trade-off zone] where..."
- Step 4 [Punchline Synthesis]: "Synthesize the visual rule: '[One-sentence managerial takeaway revealed by the graphic].'"

💡 VISUAL PUNCHLINE:
"Synthesize the visual takeaway: '[One-sentence managerial takeaway revealed by the graphic].'"

--- LECTURE NOTES ---

• CORE NARRATIVE:
* MLO Anchor: [Relevant Module Learning Outcomes, e.g. MLO 1 & MLO 4]
* Thematic Framing: Structured narrative context using bullet points
* Structural Architecture / Conceptual Mechanism: Underlying operational architecture and mechanisms
* Strategic Empirical Anchor / Pedagogical Focus: Empirical real-world anchor and pedagogical learning goal

• SLIDE BODY COVERAGE — [SECTION NAME]:

[Exact Slide Bullet 1 Title]:

Plain English: Paragraph 1 (required): the definition and how it works, in everyday words.
[Paragraph 2, after a blank line: "Think of it like..." metaphor — may share paragraph 1 if the note is one paragraph]
[Optional paragraph 3, after a blank line: where it breaks down — boundary condition or edge case]

Deep Research:
- Classical Foundation: Seminal citation (Author, Year) establishing the baseline operational mechanism (doi:10.xxxx/... or ISBN).
- Contemporary Frontier (2024-2026): Recent peer-reviewed research (Author, 2024-2026) updating the concept for digital/geopolitical contexts (doi:10.xxxx/...).

Concrete Example: For example, <APAC/Singapore anchor> <metric with data year> (<Org>, <Year>).

Globally, <global benchmark> <metric with data year> (<Org>, <Year>).

Sources: <Org> (<Year>) "<Title>", <URL or DOI>; <Org> (<Year>) "<Title>", <URL or DOI>

Bigger Picture: Begins with "Strategically, " linking to organizational trade-offs, network effects, and macro implications.

Assessment Link: Direct mapping to module coursework brief sections, task word counts, and evaluation criteria.

Manager's So What: Begins with "Actionable takeaway: " with executive rule of thumb and decision protocol.

[Exact Slide Bullet 2 Title]:
...
```

### SBC Rules (MO9529 Session-4 Gold Standard Architecture — W5-L1 Slide 3)

The SBC MUST mirror the slide's own bullet structure exactly:
- Every item in SBC must use the **exact same label text** as the slide bullet as its header (`[Exact Slide Bullet Title]:`)
- Each bullet item gets a complete {n_fields}-element analysis block separated by blank lines
- If the slide has 8 bullets, the SBC has exactly 8 items — no skipping, no merging
- If the slide has a table with 6 rows, the SBC has exactly 6 items — one per row
- The SBC header name must match the slide section it covers (e.g., `• SLIDE BODY COVERAGE — KEY PROPERTIES:`)
- **Audit precision:** Exact heading matches ensure `sbc_audit.py` passes all keyword coverage checks with 100% precision

## Generation Rules

1. **Timing:** Estimate ⏱ based on content density (2 min for simple, 4-6 min for complex, 8-10 min for case studies). Include target focus badge (⏱ X.X min | 🎯 <Focus>).
2. **BRIDGE, NARRATIVE OPENING, KEY POINT, TRANSITION:** Must be verbatim delivery lines in quotes. **NARRATIVE OPENING / HOOK** can span **1–2 paragraphs**. {KEY_POINT_RULE}
3. **ACTIVITY & TEACHER GUIDANCE:** Every content slide needs an activity matching the class size ({class_size}). Include TEACHER GUIDANCE & EXPECTED ANSWERS: followed by a blank line and 5-space indented sub-bullets with dashes (     - Expected:,      - Guidance:,      - Assessment Link:,      - Key Insight:).
4. **SBC & Multi-Paragraph Depth:** Follow the SBC Quality Standard (6 elements per item). {PLAIN_ENGLISH_RULE} The other five fields (`Deep Research`, `Concrete Example`, `Bigger Picture`, `Assessment Link`, `Manager's So What`) should have **2–3 paragraphs where feasible** to unpack operational mechanisms, empirical regional/global data, and executive trade-offs.
5. **Case Study & Concrete Example sources:** Use 2024-2026 data. Real companies, real numbers, real events. {EXAMPLE_SOURCES_RULE}
5b. **Citations:** {DEEP_RESEARCH_EVIDENCE_RULE} Every reference is checked by `verify_references.py` before write-back.
6. **No praise language.** Be direct and pedagogical.
7. **No emoji** beyond ⏱ and 🎯 in the final output.
8. **If the slide has a table:** Walk through every row in SBC.
9. **If the slide has a chart:** Explain what the chart shows, what the axes mean, and what the trend implies.
10. **Visual Deconstruction (v2.13.0):** {VISUAL_DECONSTRUCTION_RULE}

---

## Zone A High-Engagement Hook Standard (CRITICAL — per SKILL.md)

{zone_a_spec_text}

---

## SBC Quality Standard (CRITICAL — per SKILL.md Feature 7)

The Slide Body Coverage block is the **most important section** Wilson reads mid-lecture. It must be written so that Wilson can teach directly from it — explaining every concept on the slide as if to a student encountering it for the first time.

{sbc_spec_text}{online_spec_text}

### Correct KEY POINT, Visual Deconstruction and SBC Pattern (GOOD — every reference verified 2026-10-06)

```
{GOLD_KEY_POINT_EXAMPLE}
```

```
{GOLD_VISUAL_DECONSTRUCTION_EXAMPLE}
```

```
{GOLD_SBC_EXAMPLE}
```

### Anti-Patterns to NEVER Write (BAD)

```
❌ "Explains the concept of path length" — circular, says nothing
❌ "Focuses on the network efficiency objective" — what objective? why?
❌ "This is important for SCM" — why? how? what happens if ignored?
❌ "Sets the academic foundation" — meaningless filler
❌ "Path length is the distance between nodes" — definition only, no example, no 'so what'
```
"""
    return prompt


def build_batch_prompt(
    slide_contexts: Sequence[Dict[str, Any]],
    module_context: Dict[str, Any],
    session_info: Optional[Dict[str, Any]] = None,
    spec: Optional[Dict[str, Any]] = None,
    cached_citations: Optional[Dict[str, Any]] = None,
) -> str:
    """Build ONE prompt covering N slides, with the standard inlined once."""
    if not slide_contexts:
        raise ValueError("build_batch_prompt requires at least one slide")

    prompts = [
        build_generation_prompt(
            sc,
            module_context,
            session_info,
            spec=spec,
            cached_citations=cached_citations,
        )
        for sc in slide_contexts
    ]
    prefix, first_block, suffix = split_prompt(prompts[0])

    blocks = [first_block]
    for p in prompts[1:]:
        _, blk, _ = split_prompt(p)
        blocks.append(blk)

    body = BATCH_SLIDE_SEP.join(SLIDE_START + b.strip("\n") for b in blocks)

    return (
        prefix.rstrip("\n")
        + "\n\n"
        + body
        + SLIDE_END
        + suffix
        + BATCH_INSTRUCTION.format(n=len(slide_contexts))
    )


def parse_slide_spec(spec_text: Optional[str], total_slides: int) -> Optional[List[int]]:
    """Parse a --batch spec like '1,5-12' or 'all' into a sorted slide list."""
    if spec_text is None:
        return None
    spec_text = spec_text.strip().lower()
    if spec_text == "all":
        return list(range(1, total_slides + 1))

    slides = set()
    for part in spec_text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, _, hi = part.partition("-")
            lo_i, hi_i = int(lo), int(hi)
            if lo_i > hi_i:
                raise ValueError(f"inverted range: {part}")
            slides.update(range(lo_i, hi_i + 1))
        else:
            slides.add(int(part))
    return sorted(s for s in slides if 1 <= s <= total_slides)


def audit_notes_structure(notes_text: str) -> Dict[str, Any]:
    """Audit existing notes for structural completeness."""
    markers = {
        "timing": "⏱" in notes_text,
        "speaker_section": "--- SPEAKER NOTES ---" in notes_text,
        "visual_deconstruction": "--- VISUAL DECONSTRUCTION ---" in notes_text,
        "lecture_section": "--- LECTURE NOTES ---" in notes_text,
        "bridge": bool(re.search(r"(?:\* )?BRIDGE:", notes_text, re.IGNORECASE)),
        "opening_line": bool(
            re.search(
                r"(?:\* )?(?:Opening line|NARRATIVE OPENING|OPENING HOOK):",
                notes_text,
                re.IGNORECASE,
            )
        ),
        "key_point": bool(re.search(r"(?:\* )?KEY POINT:", notes_text, re.IGNORECASE)),
        "socratic_prompt": bool(re.search(r"(?:\* )?SOCRATIC PROMPT", notes_text, re.IGNORECASE)),
        "transition": bool(re.search(r"(?:\* )?TRANSITION:", notes_text, re.IGNORECASE)),
        "core_narrative": bool(re.search(r"• Core Narrative:", notes_text, re.IGNORECASE)),
        "sbc": bool(re.search(r"• Slide Body Coverage", notes_text, re.IGNORECASE)),
    }

    missing = [k for k, v in markers.items() if not v]
    present = [k for k, v in markers.items() if v]

    return {
        "markers": markers,
        "missing": missing,
        "present": present,
        "completeness_pct": round(len(present) / len(markers) * 100),
    }


def build_enhancement_prompt(
    slide: Any,
    slide_num: int,
    existing_notes: str,
    audit: Dict[str, Any],
    module_context: Dict[str, Any],
    session_info: Optional[Dict[str, Any]] = None,
    freshness: Optional[Dict[str, Any]] = None,
    spec: Optional[Dict[str, Any]] = None,
    cached_citations: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a targeted enhancement prompt adding only missing elements."""
    if cached_citations and not freshness:
        freshness = cached_citations
    spec = spec or DEFAULT_FORMAT_SPEC
    sbc_spec_text = render_sbc_spec(spec)

    online_spec_text = ""
    if str(spec.get("delivery_mode") or "").lower() == "online":
        eng = spec.get("engagement") or {}
        formats = eng.get("required_formats") or []
        gap = eng.get("max_gap_minutes", 12)
        need = []
        if "chat" in formats:
            need.append('a chat/poll prompt (chat waterfall, poll, or "type the number you\'d choose")')
        if "breakout_deliverable" in formats:
            need.append("a breakout whose every room produces one artifact and names a reporter")
        online_spec_text = f"""

### Online Delivery (delivery_mode: online — enforced by sbc_audit.py)

If you add or sharpen an ACTIVITY, it must serve online delivery. This module
requires: {'; '.join(need)}.

Cadence rule: no more than **{gap} minutes** of continuous monologue without an
interaction (ACTIVITY, SOCRATIC PROMPT / COLD CALL, quiz/poll/chat, or TEACHER
GUIDANCE).
"""

    module_code = module_context.get("module_code", "UNKNOWN")
    module_name = module_context.get("module_name", "Unknown Module")
    class_size = module_context.get("class_size", "30")
    style = module_context.get("style", "generic")

    title = get_slide_title(slide)
    body_text = extract_slide_body_text(slide)
    has_visuals = has_visual_content(slide)

    missing_speaker = [
        m
        for m in audit["missing"]
        if m
        in (
            "timing",
            "bridge",
            "opening_line",
            "key_point",
            "socratic_prompt",
            "activity",
            "teacher_guidance",
            "transition",
        )
    ]
    missing_lecture = [m for m in audit["missing"] if m in ("core_narrative", "sbc")]
    missing_sections = [m for m in audit["missing"] if m in ("speaker_section", "lecture_section")]

    speaker_additions = ""
    if missing_speaker:
        speaker_additions = f"""
### Add These SPEAKER NOTES Elements

The following structural elements are MISSING from the speaker notes section.
Add ONLY these — do not rewrite existing content:

{chr(10).join(f'- **{m.replace("_", " ").title()}**: Add this element following the standard format' for m in missing_speaker)}
"""

    lecture_additions = ""
    if missing_lecture:
        lecture_additions = f"""
### Add These LECTURE NOTES Elements

The following structural elements are MISSING from the lecture notes section.
Add ONLY these — do not rewrite existing content:

{chr(10).join(f'- **{m.replace("_", " ").title()}**: Add this element following the standard format' for m in missing_lecture)}
"""

    section_additions = ""
    if missing_sections:
        section_additions = f"""
### Add Missing Section Dividers

The following section dividers are MISSING:
{chr(10).join(f'- `--- {m.replace("_", " ").upper()} ---`' for m in missing_sections)}
"""

    sbc_instructions = ""
    if "sbc" in audit["missing"]:
        n_fields = len(spec.get("sbc_fields", []))
        field_lines = "\n".join(
            f"   - `{f['label']}:`" + (f' (lead-in: "{f["lead_in"]}")' if f.get("lead_in") else "")
            for f in spec.get("sbc_fields", [])
        )
        sbc_instructions = f"""
### SBC Generation (CRITICAL — per NOTES_FORMAT.md / SKILL.md Feature 7)

Since SBC is missing, generate it from scratch.

**SBC Rules**:
1. Every bullet or item on the slide gets a standalone block headed by the exact slide bullet text: `[Exact Slide Bullet Title]:`
2. Each bullet item gets a complete {n_fields}-element analysis block separated by blank lines:
{field_lines}

**Quality bar**:
{sbc_spec_text}{online_spec_text}
"""

    freshness_instructions = ""
    if freshness and freshness.get("freshness_score", 100) < 80:
        f = freshness
        freshness_instructions = f"""
### Content Freshness Enhancement (CRITICAL)

The gap scan flagged this slide as having **stale content** (freshness score: {f['freshness_score']}/100).
The slide body text contains outdated references, pre-COVID case studies, or hot topics without recent context.

**Do NOT change the slide body text.** Instead, enhance the LECTURE NOTES section to add:
"""
        if f.get("stale_references"):
            refs = f["stale_references"][:3]
            freshness_instructions += "\n**Old citations found — add recent (2024-2026) research alongside them:**\n"
            for ref in refs:
                freshness_instructions += f"- Old citation ({ref['year']}): {ref['context'][:100]}\n"

        if f.get("stale_events"):
            events = f["stale_events"][:3]
            freshness_instructions += "\n**Pre-COVID case studies found — add a recent parallel event:**\n"
            for ev in events:
                freshness_instructions += f"- {ev}\n"

        if f.get("missing_recent_context"):
            topics = f["missing_recent_context"][:5]
            freshness_instructions += "\n**Hot topics without recent (2024-2026) context:**\n"
            for t in topics:
                freshness_instructions += f"- {t}\n"

    prompt = f"""# Lecture Note Enhancement Task

## Module Context
- **Module:** {module_code} — {module_name}
- **Class Size:** {class_size}
- **Teaching Style:** {style}

## Enhancement Scope

This is a **targeted enhancement** — NOT a full regeneration. The existing notes are mostly complete.
Only add the missing structural elements listed below. Preserve ALL existing content exactly as-is.

**Completeness:** {audit['completeness_pct']}% — {len(audit['missing'])} elements missing

**Present elements:** {', '.join(audit['present'])}
**Missing elements:** {', '.join(audit['missing'])}

{speaker_additions}
{lecture_additions}
{section_additions}
{sbc_instructions}
{freshness_instructions}

## Slide Content

**Slide {slide_num}: {title}**

### Body Text
{body_text if body_text else '(No body text — title slide or visual-only slide)'}

### Visual Elements
{'This slide contains tables, charts, images, or diagrams that need SBC coverage.' if has_visuals else 'No visual elements detected.'}

## Existing Notes (PRESERVE ALL OF THIS)

```
{existing_notes}
```

---

## Enhancement Rules

1. **PRESERVE EVERYTHING.** Do not delete, rewrite, or shorten any existing content.
2. **INSERT only the missing elements** at the correct position in the structure.
3. **Match the existing tone and style** — don't introduce a different voice.
4. **If adding SBC:** follow the SBC Quality Standard exactly (6 elements per item, bullet hierarchy, exact label matching). {PLAIN_ENGLISH_RULE} The other five fields should have **2–3 paragraphs where feasible**. Concrete Example: {EXAMPLE_SOURCES_RULE} Deep Research: {DEEP_RESEARCH_EVIDENCE_RULE}
5. **If adding ACTIVITY & TEACHER GUIDANCE:** match the class size ({class_size}). Include TEACHER GUIDANCE & EXPECTED ANSWERS: followed by a blank line and 5-space indented sub-bullets with dashes (     - Expected:,      - Guidance:,      - Assessment Link:,      - Key Insight:).
6. **If adding BRIDGE/TRANSITION/HOOK/KEY POINT:** write verbatim delivery lines in quotes with clean un-bulleted headers matching W5-L1 Slide 3. **NARRATIVE OPENING / HOOK** can span **1–2 paragraphs**. {KEY_POINT_RULE}
7. **If adding timing:** estimate ⏱ based on content density (e.g. ⏱ X.X min | 🎯 <Hook Focus>).
8. **No praise language.** Be direct and pedagogical.
9. **No emoji** beyond ⏱ and 🎯.
10. **If adding Visual Deconstruction:** {VISUAL_DECONSTRUCTION_RULE}

## Output Format

Return the COMPLETE notes with all existing content preserved and new elements inserted at the correct positions.
"""
    return prompt
