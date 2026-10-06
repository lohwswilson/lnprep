# lnprep

**Lecture Notes Preparation CLI** — standalone tool for academic slide notes engineering, 3-Zone architecture formatting, direct XML notes injection, Slide Body Coverage (SBC) auditing, and live reference verification.

## Architecture

`lnprep` implements the v2.13.0 3-Zone Architecture:
1. `--- SPEAKER NOTES ---`: Timing badge, verbatim narrative opening hook (1–2 paragraphs), key point (1–3 prose paragraphs), Socratic prompts, misconceptions, activities, and teacher guidance.
2. `--- VISUAL DECONSTRUCTION ---`: Required for slides containing diagrams, charts, frameworks, tables, or SmartArt (Visual Objective, Gaze Direction, Step-by-Step Walk-Through, and Visual Punchline).
3. `--- LECTURE NOTES ---`: Core narrative (MLO anchor, framing, mechanisms, empirical anchors) and Slide Body Coverage (SBC) with 6 canonical fields (Plain English, Deep Research, Concrete Example with sources, Bigger Picture, Assessment Link, Manager's So What).

## Installation

```bash
# Editable install as a global tool via uv
uv tool install --editable /opt/lnprep

# Local development install with test dependencies
uv pip install -e ".[test]"
```

## CLI Commands

| Command | Description |
|---|---|
| `lnprep init <module_path>` | Scaffold or update `LECTURE_NOTES_GUIDE.md` for a module folder |
| `lnprep extract <pptx_path>` | Extract slide notes, body text, tables, charts, SmartArt, and shapes |
| `lnprep generate <pptx_path>` | Generate single-slide or batched notes generation prompts |
| `lnprep enhance <pptx_path>` | Generate targeted gap-enhancement prompts for partial slides |
| `lnprep audit <pptx_path>` | Audit Slide Body Coverage (coverage, semantic alignment, quality, depth) |
| `lnprep verify <pptx_path>` | Verify academic references, DOIs, ISBNs, and live URLs |
| `lnprep write <pptx_path>` | Safe Direct XML note injection with automated `.bak` backup and verification gate |
| `lnprep cache <subcommand>` | Query, record, report, or prune the module-level citation cache |
| `lnprep cross-check <module_path>` | Validate session guides (time budget, assessment linkages, file references) |
| `lnprep sync <module_path>` | Parse syllabus, MLOs, and assessment briefs from documents |
| `lnprep brief <pptx_path>` | Build review brief for independent evaluation |
| `lnprep check <pptx_path>` | Composite pre-flight validation (SBC audit + reference verification) |

## Development & Testing

```bash
# Run test suite
uv run pytest

# Run linting
uv run ruff check
```
