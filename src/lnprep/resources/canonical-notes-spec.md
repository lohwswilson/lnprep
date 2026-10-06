# Canonical Lecture Notes Specification

> **This is the single source of truth for the note format.**
>
> Referenced by: `SKILL.md`, `scripts/common.py`, `generate_notes.py`,
> `enhance_notes.py`, `update_pptx_notes.py`, `sbc_audit.py`, `format_notes.py`.
>
> Before 2026-09-30 the SBC rules lived in three places — this file (as
> `sbc-quality-standard.md`), the `SKILL.md` body, and the prompt constants in
> `scripts/common.py` — which is how a divergent `LABELS_LIST` survived
> undetected. The human-readable standard is now here and only here.

Two representations of the canon exist, deliberately:

| Representation | Where | Consumer | Guarded by |
|---|---|---|---|
| **Prose canon** (this file) | `references/canonical-notes-spec.md` | Wilson, agents, reviewers | review |
| **Prompt canon** | `scripts/common.py` → rule constants (`KEY_POINT_RULE`, `PLAIN_ENGLISH_RULE`, `EXAMPLE_SOURCES_RULE`, `VISUAL_DECONSTRUCTION_RULE`), gold examples, `DEFAULT_FORMAT_SPEC` | generation prompts, `sbc_audit.py` | `scripts/tests/test_format_spec_sync.py` |

They are two renderings of one standard, not two standards. **Change this file,
then change the constants in `common.py`, then run the test suite** — the sync test
fails if the rule text or the gold examples differ between the two.

> Until 2026-10-06 this table named `scripts/verify_format_spec.py` as the guard. That
> script never existed, and the paragraph rule had drifted into four versions across
> five files. The sync test replaces it.

---

## The Wilson Test

**Could Wilson pick up this SBC block 5 minutes before a lecture on a topic he
hasn't taught in 6 months, and teach the slide competently with full academic
authority and real-world data?** If the answer is no, the SBC is too shallow.

---

## Required Structure for EVERY SBC Item

Every slide body item in a Slide Body Coverage block must be a standalone block
headed by the exact slide bullet text (`<Exact Slide Bullet / Item Header>:`),
followed by ALL SIX canonical labeled fields separated by blank lines:

```
<Exact Slide Bullet / Item Header>:

Plain English: [1–3 paragraphs of jargon-free prose: definition → "Think of it like..." metaphor → (optional) where it breaks down]

Deep Research:
- Classical Foundation: [Seminal citation (Author, Year) establishing the foundational theoretical mechanism (doi:10.xxxx/... or ISBN)]
- Contemporary Frontier (2024-2026): [Recent peer-reviewed research (Author, 2024-2026) updating the concept for digital/geopolitical contexts (doi:10.xxxx/...)]

Concrete Example: [Begins with "For example, " pairing an APAC/Singapore regional ecosystem anchor (e.g. PSA Tuas Port, SIA Cargo, Grab, TSMC, BYD, Shein) with a global benchmark (Apple, Amazon, Toyota, FedEx), complete with quantitative operational metrics, each carrying an inline (Org, Year) marker]

Sources: [<Org> (<Year>) "<Title>", <URL or DOI>; <next source>]

Bigger Picture: [Begins with "Strategically, " + systemic implications, trade-offs, network effects, competitive advantage]

Assessment Link: [Direct link to module coursework brief sections, task word counts, evaluation criteria, or analysis tasks]

Manager's So What: [Begins with "Actionable takeaway: " + pragmatic executive rule of thumb and decision protocol]
```

### The six canonical fields

| Field Label | Required Lead-in / Standard | Purpose |
|---|---|---|
| `Plain English:` | 1–3 prose paragraphs; metaphor: *"Think of it like..."* | Intuitive definition without jargon |
| `Deep Research:` | Dual-anchor: Seminal `(Author, Year)` + `(Author, 2024-2026)`, each with DOI/ISBN/URL | Classical mechanism + modern research update |
| `Concrete Example:` | Dual-geography: Lead-in *"For example, "* + APAC + Global; inline `(Org, Year)` + closing `Sources:` line | Grounded in Singapore/Asia + global benchmarks, every figure sourced |
| `Bigger Picture:` | Lead-in: *"Strategically, "* | Strategic trade-offs and macro operational effects |
| `Assessment Link:` | Explicit coursework mapping (Task & word count) | Guidance on how to apply in assignment sections |
| `Manager's So What:` | Lead-in: *"Actionable takeaway: "* | Executive decision rule of thumb |

---

## SBC Bullet Hierarchy Rules

The SBC MUST mirror the slide's own bullet structure exactly:

| Slide Structure | SBC Structure |
|----------------|---------------|
| `• Main bullet` | `<Main bullet text>:` followed by the 6 canonical fields |
| `  • Sub-bullet` | `<Sub-bullet text>:` followed by the 6 canonical fields |
| Table row | `<Row header text>:` followed by the 6 canonical fields |
| Diagram label | `<Label text>:` followed by the 6 canonical fields |

**Critical rules:**
- Every item in SBC must use the **exact same label text** as the slide bullet — don't paraphrase
- Distinct headers: each bullet gets its own header and complete 6-element block, blank-line separated
- If the slide has 8 bullets, the SBC has exactly 8 items — no skipping, no merging
- If the slide has a table with 6 rows, the SBC has exactly 6 items — one per row
- The SBC header name must match the slide section it covers (e.g. `• SLIDE BODY COVERAGE — KEY PROPERTIES:`)
- **Audit precision:** exact heading matches let `sbc_audit.py` pass all keyword coverage checks at 100%

---

## Paragraph & Depth Standard (v2.12.0)

**KEY POINT and Plain English are written as 1–3 paragraphs of prose** (Wilson,
2026-10-06). One well-made paragraph is enough for a simple point; more than
three is a monologue. No bullets or lists inside either field. The exact rule
text rendered into every prompt (from `common.py`) is:

> KEY POINT: 1–3 paragraphs of continuous prose, separated by blank lines. No bullets or lists. Para 1 (required): the core principle — what it is and why it matters. Para 2 (if needed): the mechanism, trade-off, or organisational friction. Para 3 (if needed): the strategic consequence and assessment relevance. Stop when the idea is complete; never pad to reach 3.

> Plain English: 1–3 paragraphs of jargon-free prose, separated by blank lines. No bullets. Para 1 (required): the definition and how it works, in everyday words. Para 2 (required unless the metaphor fits in Para 1): an explicit pedagogical metaphor ("Think of it like..."). Para 3 (optional): where it breaks down — a boundary condition or edge case.

The other five SBC fields keep **2–3 paragraphs where feasible**:

| Field | Paragraph structure |
|---|---|
| **`KEY POINT:`** (Zone A) | **1–3 prose paragraphs.** **Para 1 (required)**: core principle — what it is and why it matters.<br>**Para 2 (if needed)**: mechanism, trade-off or organisational friction.<br>**Para 3 (if needed)**: strategic consequence and assessment relevance. |
| **`Plain English:`** | **1–3 prose paragraphs.** **Para 1 (required)**: definition and how it works, in everyday words.<br>**Para 2**: explicit pedagogical metaphor (`Think of it like...`) — may share Para 1 when the note is one paragraph.<br>**Para 3 (optional)**: boundary condition or edge case. |
| **`Deep Research:`** | **Para 1**: Classical Foundation: Seminal citation (Author, Year) + theoretical mechanism.<br>**Para 2**: Contemporary Frontier (2024-2026): Peer-reviewed finding (Author, Year).<br>**Para 3**: Theoretical synthesis & modern digital/geopolitical friction. |
| **`Concrete Example:`** | **Para 1**: APAC / Singapore regional anchor (e.g. PSA, SIA Cargo, Grab, SingHealth) with quantitative metrics and `(Org, Year)` markers.<br>**Para 2**: Global benchmark anchor (Apple, Amazon, Toyota, FedEx, Maersk) with quantitative metrics and `(Org, Year)` markers.<br>**Para 3 (optional)**: Cross-ecosystem comparative contrast and operational transferability.<br>**Closing line**: `Sources:` with URL/DOI for every marker (not counted as a paragraph). |
| **`Bigger Picture:`** | **Para 1**: Strategic industry-level trade-offs, network effects, scale dynamics.<br>**Para 2**: Enterprise risk, regulatory mandates (e.g. CSRD, CSDDD), compliance floor vs capability.<br>**Para 3**: Long-term competitive positioning and business model transformation. |
| **`Assessment Link:`** | **Para 1**: Direct coursework brief alignment (Task 1–3) and MLO anchor.<br>**Para 2**: Distinction criteria: analytical depth required for Level 6 First-Class marks.<br>**Para 3**: Critical pitfalls and superficial student errors to penalize/avoid. |
| **`Manager's So What:`** | **Para 1**: Actionable executive rule of thumb and immediate decision protocol.<br>**Para 2**: Implementation sequence: 30-60-90 day roadmap and organizational friction.<br>**Para 3**: Operational guardrail / early warning KPI threshold to prevent catastrophic failure. |

---

## Zone A High-Engagement Hook Standard

Every slide in Zone A must open with a delivery-ready, verbatim hook script
(1–2 paragraphs) using one of the 4 Executive Pedagogical Hook Archetypes:

1. **High-Stakes Crisis / 3 AM Dilemma** — places students in the shoes of an operations leader facing an urgent breakdown (e.g. PSA Tuas crane outage, cold-chain failure at SIA Cargo).
2. **Counter-Intuitive Paradox** — opens with a real-world business move that seems irrational on the surface (e.g. Zara flying fast-fashion dresses by air freight yet doubling profit margin).
3. **Provocative Trade-Off / 'Choose Your Poison'** — forces students to confront hard operational trade-offs and impossible constraints (e.g. cutting inventory 40% while maintaining 99% next-day delivery).
4. **Startling Reality-Check / Eye-Opening Metric** — reveals a verified, shocking industry statistic that shatters naive assumptions (e.g. 72% of CSOs having zero visibility beyond Tier-1).

**Depth:** `NARRATIVE OPENING / HOOK` spans 1–2 paragraphs; `KEY POINT` and
`Plain English` span 1–3 prose paragraphs; the other five SBC elements span 2–3
paragraphs where feasible.

**How paragraphs are counted (matters for how you write).** A paragraph is a run of
text separated from the next by a **blank line**. The renderer
(`update_pptx_notes.py`) turns each blank line into a real new paragraph, so prose
with no blank lines renders as **one wall of text** no matter how many sentences it
contains — and will be counted as one paragraph. Write the blank lines.

**This is audited.** `sbc_audit.py` reports a per-field paragraph count for `KEY POINT`
and the six SBC fields (`audit_sbc_depth`, `audit_zone_a_depth`) with statuses
`BELOW_DEPTH`, `OVER_MAX_PARAGRAPHS` (more than 3 in KEY POINT / Plain English) and
`NOT_PROSE` (bullet lines in a prose-only field). It is reported in a **DEPTH & SOURCES
(advisory)** line and deliberately **not** part of PASS/FAIL. Until v2.10.1 keyword
markers scored a 65-word item 6/6 — identical to a properly developed one.

Rules live in `PARAGRAPH_RULES` (`common.py`): KEY POINT and Plain English `min 1, max 3,
prose_only`; every other field `min 2` (`audit.min_paragraphs`, default 2). A module
overrides any of these under `audit.paragraphs` in its `NOTES_FORMAT.md`:

```yaml
audit:
  paragraphs:
    key_point:     {min: 1, max: 3, prose_only: true}
    plain_english: {min: 1, max: 3, prose_only: true}
    default:       {min: 2}
```

**TEACHER GUIDANCE & EXPECTED ANSWERS:** must be followed by a blank line and
5-space indented sub-bullets with dashes:

```
     - Expected:
     - Guidance:
     - Assessment Link:
     - Key Insight:
```

**CRITICAL:** Never use dry, flat openings like *"On this slide, we will discuss..."*.
Make it dramatic, provocative, and delivery-ready.

---

## Visual Deconstruction Standard (v2.13.0)

For slides containing a diagram, framework, chart, table, SmartArt, process flow, or image, the notes contain a dedicated top-level section: `--- VISUAL DECONSTRUCTION ---`, positioned between `--- SPEAKER NOTES ---` and `--- LECTURE NOTES ---`. It is omitted for pure text, quote, or agenda slides.

The rule mirrored verbatim from `VISUAL_DECONSTRUCTION_RULE` in `common.py` is:

```
VISUAL DECONSTRUCTION: Required whenever the slide contains a diagram, framework, chart, table, SmartArt, process flow, or image; omit entirely for text-only/agenda slides. Structure as an explicit top-level zone between --- SPEAKER NOTES --- and --- LECTURE NOTES ---. Include four micro-elements:
1. 🎯 VISUAL OBJECTIVE: One sentence stating what core relationship, mechanism, or data insight this graphic proves.
2. 👁️ GAZE DIRECTION (Where to point first): Physical pointer/eye guidance on where students must look first (axes, inputs, baseline quadrant).
3. 🔄 STEP-BY-STEP WALK-THROUGH: Numbered steps (Step 1 Baseline/Inputs -> Step 2 Mechanism/Flow -> Step 3 Friction/Inflection Point -> Step 4 Punchline Synthesis).
4. 💡 VISUAL PUNCHLINE: One-sentence managerial or theoretical takeaway revealed directly by the visual.
```

```
--- VISUAL DECONSTRUCTION ---
🎯 VISUAL OBJECTIVE:
Demonstrates how small stochastic demand variances amplify exponentially as information moves upstream through supply chain tiers.

👁️ GAZE DIRECTION (Where to point first):
"Direct students' eyes to the far left of the diagram: Consumer Retail Sales (the flat, mild wave)."

🔄 STEP-BY-STEP WALK-THROUGH:
- Step 1 [Consumer to Retailer]: "Point to the retail order line: notice the mild ±5% fluctuation. Explain that batch ordering and lead-time safety buffers slightly exaggerate this wave."
- Step 2 [Retailer to Distributor to Manufacturer]: "Trace your finger to the middle tiers: show how the amplitude doubles at the distributor level and triples at the manufacturing tier due to order batching and price speculation."
- Step 3 [The Tier-2 / Raw Material Whiplash]: "Point to the violent, chaotic wave at the far right (Raw Materials). Highlight that component suppliers experience wild boom-and-bust cycles despite stable end-consumer consumption."
- Step 4 [Punchline Synthesis]: "Synthesize the visual rule: 'The distortion is not caused by unpredictable consumers; it is caused by internal information lag and independent buffer hoarding across silos.'"

💡 VISUAL PUNCHLINE:
"The distortion is not caused by unpredictable consumers; it is caused by internal information lag and independent buffer hoarding across silos."
```

---

## Correct KEY POINT and SBC Pattern (GOOD — every reference verified 2026-10-06)

> The previous gold example cited *"Mitchell et al. (2024) in Academy of Management
> Annals"*. No such paper exists (no Crossref record; the real work is Mitchell, Agle &
> Wood, 1997, *Academy of Management Review*). Because this example is pasted into every
> generation prompt, it was teaching the model to fabricate. Replaced 2026-10-06; every
> reference below was resolved live (Crossref / OpenLibrary / the cited page).
> These blocks are mirrored verbatim from `GOLD_KEY_POINT_EXAMPLE` and `GOLD_SBC_EXAMPLE`
> in `common.py` (sync-tested).

```
KEY POINT: "A stakeholder is anyone who can affect, or is affected by, what the firm does, and managers rarely have the time or resources to serve all of them equally.

That is why salience matters. Groups with power, legitimacy and urgency get attention first, and a group can move up the list quickly when it gains one of those attributes.

For your Task 2 analysis, the strongest answers rank stakeholders and explain how that ranking changes the firm's operational priorities."
```

```
• SLIDE BODY COVERAGE — MAJOR CORPORATE STAKEHOLDERS:

Major Corporate Stakeholders:

Plain English: Major corporate stakeholders are any group, individual, or ecological entity that is affected by, or can influence, what an organisation does, how it transforms resources, and what it produces.

Think of it like building a major airport: you cannot satisfy only the airline passengers; you must also answer to air traffic controllers, the neighbourhoods living with the noise, the municipal drainage system, and the retail staff in the terminal.

The idea breaks down when every group is treated as equally important. A firm that tries to satisfy everyone equally ends up prioritising no one, which is why stakeholder salience (who actually counts, and when) matters.

Deep Research:
- Classical Foundation: Freeman (1984) *Strategic Management: A Stakeholder Approach* founded stakeholder theory (ISBN 9780273019138); Mitchell, Agle & Wood (1997) in *Academy of Management Review* explained which stakeholders managers actually attend to through salience: power, legitimacy and urgency (doi:10.5465/amr.1997.9711022105).
- Contemporary Frontier (2024-2026): Matthews et al. (2025) in *Journal of Management* review AI, algorithms and robots through a stakeholder lens, showing that intelligent machines often create both advantages and disadvantages for different stakeholders (doi:10.1177/01492063241311855).

Concrete Example: For example, PSA's flagship Singapore terminal handled a record 40.9 million TEUs in 2024, up 5.5% (PSA International, 2025), volume that depends on keeping shipping lines, port unions, regulators and coastal communities aligned at the same time.

Globally, Nike, long the subject of sweatshop allegations, in 2005 became the first major footwear and apparel company to publish the names and locations of its more than 700 active contract factories (Nike Inc., 2005; Teather, 2005).

Sources: PSA International (2025) "PSA International's 2024 Container Throughput Performance", https://www.singaporepsa.com/2025/01/16/psa-internationals-2024-container-throughput-performance/; Nike Inc. (2005) "Nike Publishes List of Global Contract Factories in Push for Greater Transparency", https://csrwire.com/press-release/nike-publishes-list-of-global-contract-factories-in-push-for-greater-transparency-and-collaboration-to-improve-footwear-and-apparel-industry-labor-conditions/; Teather, D. (2005) "Nike lists abuses at Asian factories", The Guardian, https://www.theguardian.com/business/2005/apr/14/ethicalbusiness.money

Bigger Picture: Strategically, stakeholder legitimacy works like a licence to operate: once a firm loses it, regulators, customers and investors can withdraw support at the same time, so the damage compounds.

The trade-off is attention. Managers cannot serve every group fully, so the advantage goes to firms that read salience early and act before a latent stakeholder becomes a definitive one.

Assessment Link: Use stakeholder salience analysis in Task 2 to justify why your selected MNC must address specific operational sustainability challenges.

Distinction-level answers classify each stakeholder by power, legitimacy and urgency and show how that ranking changes the firm's priorities; listing stakeholders without ranking them stays descriptive.

Manager's So What: Actionable takeaway: build a stakeholder salience map that tracks latent, expectant and definitive stakeholders across every sourcing region.

Review the map whenever a stakeholder gains a new attribute, such as a community group gaining media attention and with it urgency, because that is the moment it moves up the priority list.
```

---

## Reference Standard (v2.12.0)

**Every reference that ships to students is verified by a script, not by memory.**

> Put a DOI (doi:10.xxxx/...) after every journal citation, and an ISBN or publisher URL after every book, so verify_references.py can check it. NEVER fabricate or cite from memory: an unverifiable citation blocks write-back.

> Every figure or company fact carries an inline (Organisation/Author, Year) marker, and the field ENDS with one line: Sources: <Org> (<Year>) "<Title>", <URL or DOI>; <next source>. State the data year of every figure (e.g. FY2024). Prefer primary sources — annual reports, investor relations, regulators (MPA, SingStat, MAS), peer-reviewed papers. No Wikipedia, AI summaries, undated blogs, or search-engine redirect links. A Concrete Example without a Sources line blocks write-back.

`scripts/verify_references.py` checks every reference in the notes, and
`update_pptx_notes.py` runs it before writing:

```
extract per slide: (Author, Year) · Org (Year) · DOI · URL · ISBN
   ├─ DOI  ─► Crossref (fallback doi.org) — exists? first author + year match?
   ├─ ISBN ─► OpenLibrary
   ├─ URL  ─► HTTP GET — live? not a soft-404? not a search-redirect link?
   │           Concrete Example sources: are the cited figures on the page?
   └─ cache ─► module .citation_cache.json (verified within TTL → CACHED)
```

| Status | Meaning | Write-back |
|---|---|---|
| `VERIFIED` / `CACHED` | Resolved and matched, now or within the cache TTL | proceeds |
| `EXISTS_SUPPORT_UNCONFIRMED` | Source exists; claim not machine-confirmed (PDF, blocked site, figure not found, book reissue year) | proceeds — reviewer confirms |
| `UNREACHABLE` | Network/server problem — could not check | proceeds — rerun or reviewer checks |
| `MISMATCH` | DOI/ISBN resolves, but author or year differs from the citation | **refused** |
| `NOT_FOUND` | DOI/ISBN does not resolve | **refused** |
| `BROKEN_LINK` | URL returns 404/410, soft-404, or a dead domain | **refused** |
| `EPHEMERAL_URL` | Search-engine redirect link (expires) instead of the real page | **refused** |
| `NO_SOURCE` | Concrete Example has no `Sources:` line with a URL/DOI/ISBN | **refused** |
| `UNRESOLVED` | In-text citation with no DOI/URL/ISBN and not in the module cache | **refused** |

`--allow-unverified` overrides a refusal; each override is logged to
`.reference_overrides.log` beside the citation cache. Verified citations are recorded
to the module cache automatically, so a reference is checked over the network once per
TTL, not on every write.

---

## Anti-Patterns to NEVER Write (BAD)

```
❌ "Explains the concept of path length" — circular, says nothing
❌ "Focuses on the network efficiency objective" — what objective? why?
❌ "This is important for SCM" — why? how? what happens if ignored?
❌ "Sets the academic foundation" — meaningless filler
❌ "Path length is the distance between nodes" — definition only, no example, no 'so what'
```

---

## SBC Length Rule

| Slide Element | Target Length |
|--------------|---------------|
| **Simple bullet** (one-line definition on slide) | 3-5 sentences (80-150 words) |
| **Complex concept** (multi-line bullet or framework) | 5-8 sentences (150-300 words) |
| **Table row** (comparison table) | 4-6 sentences per row, comparing both columns |
| **Diagram element** | Describe what's visible first, then explain the strategic meaning |

There is **no word cap**, but `KEY POINT` and `Plain English` stop at **3 paragraphs**.
Write as much as the concept needs to be truly understood. A 250-to-500 word SBC item
that teaches the concept is better than a 40-word gloss that assumes prior knowledge.

---

## Content Freshness Enhancement (Feature 4)

When a slide is flagged as stale by gap scan (freshness score < 80), the
enhancement prompt includes targeted freshness additions. The rules are:

1. **NEVER remove or replace existing citations** — they are foundational academic references
2. **Add new content as a complement**, not a replacement
3. **Use real 2024-2026 companies, events, and statistics** with specific numbers
4. **Place additions in the most relevant section** (Key Concepts, Case Study, or Analytical Insight)
5. **Label new additions clearly:** "Recent Context (2024-2026):" or "Updated Research:"

### Freshness Signal → Action Mapping

| Gap Scan Signal | Enhancement Action |
|----------------|-------------------|
| Old citations (year ≤ 2021) | Add 2024-2026 reference that builds on or updates the same concept |
| Pre-COVID case studies | Add a recent parallel event labeled "Recent Context (2024-2026):" |
| Hot topics without recent context | Add 2024-2026 development, statistic, or event with real companies |
| Newest year ≤ 2021 | Add at least one 2024-2026 reference to bring content current |

### Concrete Freshness Enhancement Patterns

SBC item:
```
* [Original bullet text]: [Original 6-element explanation]...
    - Updated Research (2024-2026): [Author] ([Year]) found that [specific finding with numbers].
      This updates the original [Original Author] ([Year]) framework with [new context].
```

Key Concepts section:
```
  * [Original Concept] ([Original Author], [Year]): [Original explanation]...
  * Updated Research (2024-2026): [Author] ([Year]) in [Journal] demonstrated that [specific finding with data].
```

Case Study section:
```
  * Case: [Original case study]...
  * Recent Context (2024-2026): In [Year], [Company] [specific action with numbers].
    This demonstrates [what the new case teaches about the same principle].
```

### Verification Pattern

After writing enhanced notes back, verify freshness additions were embedded:

```bash
python3 scripts/extract_pptx_notes.py "$PPTX" --slide N | grep -E "(Updated Research|Recent Context|Concrete Example|Assessment Link|Manager's So What)"
```

Each marker should appear at least once per enhanced slide. If any are missing,
the enhancement was incomplete.

---

## Prompt Rendering — cost contract

The generation prompt inlines this standard **once per prompt**, not once per
slide. Measured 2026-09-30:

| Mode | Prompt size (5 slides) | Prompt size (8 slides) |
|---|---|---|
| Naive, one prompt per slide | 74,780 chars | 119,648 chars |
| Batched, standard once | 20,513 chars | 23,932 chars |
| **Saving** | **73%** | **80%** |

`generate_notes.py --batch <spec>` is the batched path. The shared region of a
batched prompt is byte-identical to the single-slide path (verified by test), so
batching cannot drift from unbatched output.
