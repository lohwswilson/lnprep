# AGENTS.md

Guidance for AI coding agents working in this repository. This is the single source of project conventions.

## Environment
- Python **3.13** (pinned via `.python-version`)
- Package manager: `uv`
- Build backend: `hatchling`
- Entry point: `lnprep = "lnprep.main:main"` (declared in `pyproject.toml`)

## Commands
- Run all tests: `uv run pytest`
- Run a single test: `uv run pytest tests/test_depth_standard.py`
- Run CLI: `uv run lnprep <command>`
- Install (editable global tool): `uv tool install --editable /opt/lnprep`
- Install (editable local virtualenv): `uv pip install -e ".[test]"`

## Architecture

1. **Decoupled Core Logic**:
   - `src/lnprep/core/` contains pure business logic functions and classes. Core logic must not depend on CLI or Typer. All inputs and outputs must be clean Python data structures.
   - `src/lnprep/commands/` contains Typer subcommand handlers that parse CLI options, invoke `src/lnprep/core/`, and render outputs via Rich or JSON formatters.
   - `src/lnprep/console.py` handles Rich console output, markdown rendering, tables, and JSON dumps.
   - `src/lnprep/config.py` contains path resolutions, default format specs, and environment configs.

2. **Core Modules**:
   - `common.py`: 3-zone architecture parsing (`--- SPEAKER NOTES ---`, `--- VISUAL DECONSTRUCTION ---`, `--- LECTURE NOTES ---`), rule texts, gold standard examples, format spec loader and deep merger.
   - `pptx_engine.py`: Presentation extractor (text, notes, tables, charts, SmartArt, images, group shapes).
   - `prompt_engine.py`: Single and batched prompt compilation with standard inlining, structural split markers, and token optimization.
   - `audit_engine.py`: Multi-pass Slide Body Coverage (SBC) auditing: coverage, semantic alignment (Jaccard similarity), quality score, multi-paragraph depth checks, and engagement cadence.
   - `ref_verifier.py`: Automated reference validation (Crossref, DOI, ISBN, live URL checks, evidence verification, and write-back gate).
   - `writer_engine.py`: Safe Direct XML notes injection, automatic `.bak` backup, verification checks, and Google Drive working copy synchronisation.
   - `citation_db.py`: Module-level citation cache manager (`.citation_cache.json`) with 180-day TTL, normalisation, and hit reporting.
   - `cross_checker.py`: Session guide cross-check validation (time budget balance, assessment linkage coverage, open questions, rules, files).
   - `syllabus_sync.py`: Document parser for TLP, assignment briefs, and module specifications (docx, pdf) extracting MLOs and assessment tasks.
   - `brief_builder.py`: Review brief assembler compiling notes, audit results, and reference check findings into a single brief.

3. **Key Engineering Invariants**:
   - Zero corruption: Never write directly to cloud-synced storage without local copy and backup.
   - Verification gate: Reference verification must gate note injection unless explicitly bypassed via `--allow-unverified`.
   - Production readiness: No placeholders, no `TODO`s, and full test suite verification.
