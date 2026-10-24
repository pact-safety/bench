# Curriculum tracks (ARENA 3.0 and beyond)

How the bench supports structured, sequential curricula — starting with [ARENA 3.0](https://github.com/callummcdougall/ARENA_3.0) — and how the existing daily-flow picker yields to a track's ordering when one is active.

## Problem

The existing daily-flow picker is **axis-fit-driven**: it looks at the user's weakest axes and surfaces problems/content that exercise those. That works well for "drill toward your gaps." It works poorly for curricula like ARENA, which have an **intentional ordering** — Chapter 0.2 builds on 0.1, and you shouldn't be drilling Chapter 2.4 before you've done Chapter 1.

Operator wants ARENA 3.0 to feel like a first-class curriculum inside the bench, not a link dump.

## Posture

**Tracks are an ordered overlay on top of the existing content + problem corpus.** A track is just a sequence of references; each reference points to a content item (which can be external URL, local file, or both), a problem, or a reflection prompt. When a track is active, the daily-flow picker yields to the track's cursor instead of running the axis-fit logic.

This shape keeps the content + problem authoring model the same (single source of truth per item) and adds a small new entity (the track) that's purely about *order*. Authoring a new track is just listing references in a YAML/markdown file; no new content has to be authored unless we choose to.

## Decisions baked in

| Question | Decision | Why |
|---|---|---|
| Multiple active tracks? | **One at a time** | The daily flow already picks one next-action; one track per user keeps that mental model. Multi-track is a future feature if it ever becomes a real need. |
| Track satisfies daily slots? | **Yes — track owns the slots when active** | Adding to the daily slots would mean drilling the existing scheduler-picks AND the track — too much load. The track replaces. |
| Cursor on opt-out + back in? | **Resume at cursor** | Preserve progress. Re-opting-in starts where you stopped. |
| External-only sections? | **Yes — track entries can be external URLs** | ARENA's primary authoritative form is GitHub notebooks. We link, don't copy. |
| Phase 1 scope | **ARENA 3.0 Chapter 0 + Chapter 1** | Two chapters is enough to validate the track shape without months of authoring. |

## Data model

### Track config (markdown, content-source-style)

`content/tracks/arena_3.md`:

```yaml
---
slug: arena_3
title: "ARENA 3.0"
description: "Callum McDougall's Alignment Research Engineer Accelerator curriculum."
source_url: "https://github.com/callummcdougall/ARENA_3.0"
chapters:
  - title: "Chapter 0 — Fundamentals"
    sections:
      - title: "0.1 Prerequisites"
        url: "https://arena-chapter0-fundamentals.streamlit.app/[0.1]_Prerequisites"
        kind: external_reading
        duration_min: 60
        domain_tags: [python, pytorch, prerequisites]
        axes: [transformer_internals, algorithmic]
      - title: "0.2 CNNs & ResNets"
        url: "https://arena-chapter0-fundamentals.streamlit.app/[0.2]_CNNs_&_ResNets"
        kind: external_reading
        duration_min: 240
        domain_tags: [cnn, resnet, computer_vision]
        axes: [transformer_internals]
      # ... more sections
  - title: "Chapter 1 — Mechanistic Interpretability"
    sections:
      # ...
---

# ARENA 3.0

(Long-form notes about the track, its lineage, recommended cadence,
prerequisites. Rendered on the /tracks/arena_3 page.)
```

The frontmatter is the structural data; the body is human-readable notes about the track.

### User settings

```python
user_settings["active_track"] = {
    "slug": "arena_3",
    "cursor": 7,           # which section we're up to (0-indexed across all sections in order)
    "started_at": "2026-05-18T14:00:00Z",
    "completed_sections": [0, 1, 2, 3, 4, 5, 6],
    "section_reflections": {
        "0": "MLP forward pass is straightforward; backward derivation was the part I'd forgotten.",
        # ...
    },
}
```

When the user advances past a section, `cursor` increments and the section index is added to `completed_sections`. Reflections are optional but encouraged (see Phase 2).

## Daily-flow picker yields to the track

In `app/services/daily_flow.py:compute_next()`, add an early branch:

```python
def compute_next(*, today, user_settings, ...):
    active_track = (user_settings or {}).get("active_track")
    if active_track:
        track_action = _next_action_for_track(active_track)
        if track_action is not None:
            return track_action
        # If the track is exhausted, fall through to the regular picker.
    # ... existing axis-fit logic ...
```

`_next_action_for_track`:
- Load the track config (cached at boot like content_items / problems)
- Find the section at `active_track["cursor"]`
- Return a NextAction with kind="track_section", url to the section (external or internal), why="ARENA 3.0 — Chapter X.Y", etc.
- If the cursor has advanced past the last section, return None (track is done; let the axis-fit picker take over)

The home page's slot strip needs to handle the new kind — probably renders "Course" or "ARENA" as the slot when active. Or simpler: the slot strip is hidden entirely when a track is active, replaced by "ARENA 3.0 — section X of N" progress bar.

## Routes

- `GET /tracks` — list of available tracks + the active-track status. Opt-in button per track.
- `GET /tracks/{slug}` — track detail page: chapter/section list, progress visualization, "make active" button.
- `POST /tracks/{slug}/activate` — set as active.
- `POST /tracks/clear-active` — opt out (cursor preserved).
- `POST /tracks/{slug}/sections/{idx}/complete` — mark section done, advance cursor.

These mirror the JD activation pattern (`/aim/jd/{slug}/activate`).

## What about retention? (Phase 2)

Once the basic track flow is live, layer Reflect retention on top:

- After a section is marked complete, the next page asks for a 30-second reflection: "What's the key insight from this section?"
- Stored in `active_track["section_reflections"]`
- 1 day / 3 days / 7 days later, the weekly Reflect surfaces: "On {date} you wrote this about {section title}. Does it still hold? What would you say differently?"
- This is the Moore & Healy calibration loop (cited in [imposter-syndrome.md](imposter-syndrome.md)) applied to learning retention.

Phase 2 is its own design pass once the track foundation is live and we have actual reflection data to work with.

## What about companion problems? (Phase 3, opportunistic)

For high-value ARENA sections (e.g., mech-interp introductions, RL fundamentals), author a small bench-native problem that the user does *after* the ARENA notebook. The problem uses the existing compose/debug + hint + voice review stack — full ecosystem participation.

Phase 3 is **opt-in per section**, not comprehensive. Pick the 5-10 sections most worth the authoring overhead; let the rest stay as external-link sections.

## Implementation plan

| # | Sub-issue | Complexity | Notes |
|---|---|---|---|
| A | Track entity + content loader | `m` | New `content/tracks/`, new `app/services/tracks.py`, loaded at boot |
| B | Daily-flow picker integration | `m` | Touches `daily_flow.py` (just-fixed for the practice double-tick); careful |
| C | `/tracks` index + detail + activate routes | `m` | New routes + templates |
| D | ARENA 3.0 Chapter 0+1 track config | `s` | Author `content/tracks/arena_3.md`; ~30 sections to map |
| E | Home page slot-strip override when track active | `s` | Hide daily slots, show track progress |
| F | Phase 2 reflection scaffold | `m` | Designed separately when A-E land |
| G | Phase 3 first companion problem(s) | `s` × N | Opportunistic, one PR per ARENA section we want to deepen |

### Order of landing

1. **A** (track entity) lands first — no dependencies.
2. **D** can be authored in parallel with A (it's just a config file matching A's expected shape).
3. **B** + **C** + **E** ship after A.
4. **F** is its own design pass after the foundation is live.
5. **G** is ongoing.

## ARENA 3.0 specifics

[Source repo](https://github.com/callummcdougall/ARENA_3.0). MIT-licensed. The Streamlit-hosted version is the canonical reading surface; the GitHub repo has the Jupyter notebooks.

**Chapter 0 — Fundamentals**: 5–7 sections covering Python/PyTorch prerequisites, CNNs, optimizers, backpropagation, autograd, transformer building blocks. Total estimated time ~25–35 hours.

**Chapter 1 — Transformer Interpretability**: 8–10 sections covering TransformerLens, attention pattern analysis, induction heads, indirect object identification, sparse autoencoders, function vectors. Total ~40–60 hours.

(Chapter 2 — RL — and Chapter 3 — LLM Evals — deferred to Phase 1.5 / Phase 2.)

For each section in the track config, we record:
- `title`, `url` (Streamlit canonical or GitHub raw)
- `kind: external_reading` (or `external_exercise` if it's the heavy-exercise sections)
- `duration_min` (from ARENA's own estimates)
- `domain_tags` (sub-topic vocabulary — see [tag-vocabulary.md](tag-vocabulary.md))
- `axes` (assessment-axis IDs; reuse the existing 13)

The mapping to bench axes is mostly mechanical:
- Chapter 0 → transformer_internals, algorithmic, training_mechanics
- Chapter 1 → mechanistic_interpretability (almost exclusively)
- Chapter 2 → training_mechanics, ai_safety_fundamentals
- Chapter 3 → eval_design, ai_safety_fundamentals, ai_governance_strategy

## What this is NOT

- **Not** a copy of ARENA's content into the bench. ARENA lives at its source; we point at it.
- **Not** a replacement for working through the notebooks. The bench tracks progress and adds retention; ARENA is still the work.
- **Not** a fork. If ARENA 3.0 updates to 3.1 or 4.0, the track config can be updated; no code changes needed.

## See also

- [`docs/architecture/tag-vocabulary.md`](tag-vocabulary.md) — how track entries inherit the tag taxonomy
- [`docs/architecture/imposter-syndrome.md`](imposter-syndrome.md) — companion piece on sustainable framing
- [`docs/architecture/rest-days.md`](rest-days.md) — the rest-day counterweight to track grinding
- [ARENA 3.0 repo](https://github.com/callummcdougall/ARENA_3.0)

## Phase 2 — Dynamic curriculum engine (ingestion + generation)

The Phase 1 design above describes hand-authored tracks: someone sits down with the source curriculum and writes `content/tracks/<slug>.md` by hand. That works for ARENA 3.0 but doesn't scale to "I want to follow [other curriculum]" without an authoring session per source.

Phase 2 (Linear epic BEN-86) adds a **dynamic curriculum engine**: point at a source, ingest it into a dependency-ordered node graph, generate per-node multi-modal content, and gate progression on a checkpoint per node.

Phase 2 ships in four sub-issues:

| Sub | Linear | What |
|---|---|---|
| A | BEN-87 | Source ingestion → dependency-ordered node graph (this section) |
| B | BEN-88 | Per-node multi-modal content generation (readings/videos/exercises/debugging) |
| C | BEN-89 | Checkpoint-gated progression + Socratic per-node understanding check |
| D | BEN-91 | Run real ARENA 3.0 through the pipeline as the dogfood (replaces the hand-authored config) |

### Resolved design decisions (locked in sub-issue A)

The parent epic (BEN-86) raised three open decisions. The operator's recommended defaults are adopted as-is below.

**1. Ingestion source format = GitHub notebook repo only.** PDF, arbitrary documentation sites, and structured "gauntlets" are deferred until the GitHub-notebook path is proven on the ARENA 3.0 dogfood. Notebook repos have predictable structure (chapter directories, section notebooks with metadata) that the ingestion tool can rely on. Generalizing to arbitrary sources before validating the simpler case is premature.

**2. Dependency extraction = manifest-assisted.** Pure inference from repo structure is fragile:

- Alphabetical filename ordering misleads (e.g., `1.10_*` sorts before `1.2_*`).
- Cross-chapter dependencies are not encoded in filesystem layout (Chapter 1 needs Chapter 0 done first; no notebook says so).
- Author intent for branched curricula (1.3.x, 1.4.x, 1.5.x in ARENA are largely independent of each other given 1.2) is not recoverable from filenames alone.

The compromise: a small per-source **YAML manifest** declares the node graph explicitly. The ingestion tool validates the manifest, topologically sorts, and emits a track config. This is more work than pure inference but produces a correct ordering on first run, every time.

**3. Content generation = operator-review-gated.** Generated readings, exercises, and debugging problems do **not** land directly in the live track. They land in a draft state (`content/<kind>/_drafts/` or equivalent — schema to be locked in sub-issue B) and the operator promotes them to live via a small review surface. Auto-publishing hallucinated or subtly-wrong exercises into the curriculum is the principal risk of this whole epic; the review gate is non-negotiable.

The Socratic understanding-check (sub-issue C) is similarly bounded: it prompts the operator with questions, **never** supplies the reasoning. Generated content is an authoring aid and a test, not an answer key.

### Manifest schema (sub-issue A deliverable)

`content/tracks/manifests/<slug>.yaml`:

```yaml
source:
  kind: github_notebooks               # MVP: only this value is allowed
  repo_url: https://github.com/callummcdougall/ARENA_3.0
  # Optional: branch, subdirectory, etc. Add when needed; not required for MVP.

track:
  slug: arena_3                        # Must match the eventual track file's slug
  title: "ARENA 3.0"
  description: "Callum McDougall's ARENA 3.0 curriculum…"

chapters:
  - title: "Chapter 0 — Fundamentals"
    nodes:
      - id: "0.0"
        title: "0.0 Prerequisites"
        url: "https://arena-chapter0-fundamentals.streamlit.app/[0.0]_Prerequisites"
        kind: external_reading         # Same vocab as the existing loader
        duration_min: 120
        domain_tags: [python, pytorch, prerequisites]
        axes: [algorithmic]
        prereqs: []                    # Empty = no prerequisites (start node)
      - id: "0.1"
        title: "0.1 Ray Tracing"
        url: "https://arena-chapter0-fundamentals.streamlit.app/[0.1]_Ray_Tracing"
        kind: external_exercise
        duration_min: 300
        domain_tags: [ray tracing, linear algebra]
        axes: [algorithmic, transformer_internals]
        prereqs: ["0.0"]               # IDs of nodes that must precede this one
      # …
```

**Constraints:**

- Every `prereqs` entry must reference an `id` declared **in the same chapter**. Cross-chapter prereqs are a manifest authoring error: if Chapter 1's "1.1" requires Chapter 0 done, place 1.1 in Chapter 1 (chapter order is preserved) — don't try to declare `prereqs: ["0.4"]` from 1.1.
- The node-graph within each chapter must be a DAG. Cycles are a hard error.
- `slug`, `title`, `kind`, `url`, `duration_min`, `domain_tags`, `axes` correspond exactly to the existing loader's fields. The ingestion tool's only job is to flatten the DAG into the linear `chapters → sections` order that `app/services/tracks.py` already understands.

### Ingestion pipeline

1. **Load** the manifest YAML; validate top-level structure (`source`, `track`, `chapters`).
2. **Validate per-chapter**: every `prereqs` entry references a declared `id` within the same chapter. Missing references abort with a clear error.
3. **Cycle-detect** each chapter's DAG via DFS. Any cycle aborts with a clear error naming the involved IDs.
4. **Topologically sort** each chapter's nodes. Within the sort, preserve the manifest's declaration order for tie-breaking (stable sort), so authoring intent shows through where the DAG doesn't constrain.
5. **Emit** a track config file matching the existing loader's shape — `slug`, `title`, `description`, `source_url`, `chapters[].sections[]` with the loader's expected per-section fields.
6. **Round-trip validate** the emitted file by loading it via `app/services/tracks._parse_track_file`. If the round-trip fails, the ingestion tool aborts before writing — the loader is the source of truth for shape correctness.

The output is intentionally a **flat per-chapter section list** in the existing loader's shape. The DAG is consumed at ingest time; the runtime never sees prereq edges. This keeps Phase 1's loader and routes unchanged.

### Why preserve chapter boundaries

The existing loader and home progress bar group by chapter (the user sees "Chapter 0 — Fundamentals" / "Chapter 1 — Transformer Interp" / etc., with progress per chapter). Allowing cross-chapter prereqs would either (a) require the ingestion tool to reshuffle nodes across chapters — destructive of authoring intent — or (b) introduce hidden gating that the UI doesn't represent. Keeping chapter boundaries hard simplifies both the tool and the user-facing model.

### What's NOT in BEN-87

- **Auto-extraction of structure from a real GitHub repo.** The MVP manifest is hand-authored. A future enhancement could scaffold a manifest by walking a repo (`extract_manifest --repo …`), but BEN-87 only consumes manifests.
- **Replacing the existing hand-authored `arena_3.md`.** The dogfood replacement is BEN-91's job. BEN-87 ships the tool + manifest + tests; the existing track file stays untouched. Operator runs the tool and reviews the output before committing any replacement.
- **Any content generation.** All of B / C / D's territory is out of scope here.
- **Schema changes to `TrackSection` / `TrackChapter` / `Track`.** Future sub-issues (C in particular) may add `node_id` or `checkpoint` fields, but A is constrained to the loader as it stands today.

## References (curriculum/learning design)

- Mastery learning (Bloom 1968) — re-cited from the imposter doc; underpins the sequential-progression approach.
- Spaced repetition (Cepeda et al. 2008) — informs the Phase 2 reflection scaffold.
- Cognitive load theory (Sweller, Ayres, Kalyuga 2011) — supports ordered curriculum over self-directed picking for early stages of skill acquisition.
- Variability of practice (Schmidt 1975) — supports mixing reflection retention prompts in with new material.
