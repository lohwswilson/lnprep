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
| `lnprep cache <subcommand>` | Manage the module-level citation cache — `lookup`, `record`, `report`, `prune`, `hit` |
| `lnprep cross-check <module_path>` | Validate session guides (time budget, assessment linkages, file references) |
| `lnprep sync <module_path>` | Parse syllabus, MLOs, and assessment briefs from documents |
| `lnprep brief <pptx_path>` | Build review brief for independent evaluation |
| `lnprep check <pptx_path>` | Composite pre-flight validation (SBC audit + reference verification) |

## The verification gate

`lnprep write` refuses to inject notes while any reference finding is **blocking**.
The blocking statuses are:

| Status | Meaning |
|---|---|
| `MISMATCH` | The record's author or year contradicts the citation |
| `NOT_FOUND` | The DOI resolves to nothing |
| `BROKEN_LINK` | The URL 404s, is a soft-404, or points at a private/loopback host |
| `EPHEMERAL_URL` | A search-engine redirect link that will expire |
| `NO_SOURCE` | A `Concrete Example` with no `Sources:` line |
| `UNRESOLVED` | A citation with no evidence attached to it |
| `UNREACHABLE` | The check could not run — offline, timeout, rate limit, or proxy |

`UNREACHABLE` is blocking deliberately. A transport failure means the reference was
never checked, so an offline machine or a Crossref rate limit must not pass a deck
that a verified citation would pass.

Two escape hatches, both logged:

```bash
lnprep verify <pptx> --offline                  # report without touching the network
lnprep write <pptx> 3 --notes "..." --allow-unverified   # override, logged to .reference_overrides.log
```

## Safety model for `write`

- A **verified backup** is written before any modification; freshness is decided by
  content hash, so a deck replaced by a copy-based restore still gets a new backup.
- Notes are injected into a **private per-invocation staging copy**, never the original.
- Publishing is **atomic** (`os.replace` + `fsync`) and refused outright if the deck
  changed on disk while notes were being written — so an edit made in PowerPoint is
  never silently discarded.
- Empty note payloads are rejected rather than erasing a slide's existing notes.

## Development & Testing

```bash
# Run test suite
uv run pytest

# Run linting
uv run ruff check

# With coverage
uv run pytest --cov=lnprep --cov-report=term-missing
```
