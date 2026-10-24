# Initiatives (cross-surface strategy units)

How the bench models long-horizon work that spans Linear tickets, GitHub repos, bench routes, and external chat threads.

## Why this entity exists

The operator does not run a single queue. In practice, work is split across parallel strategic lanes (for example capstone research, applications, product maintenance, and publication cadence). Each lane creates artifacts in different systems:

- Linear (planning tickets)
- GitHub (code/repos)
- bench (daily execution surface)
- chat/writing tools (drafting, review, synthesis)

Without an explicit entity, this context is fragmented and hard to reason about in one place. **Initiative** is the shared name for that lane.

## Data shape

Initiatives are authored in `content/initiatives/*.md` using YAML frontmatter.

```yaml
---
slug: capstone
title: MSCS Sycophancy Capstone
status: active
priority: 1
linear:
  team: "Li's Space"
  ticket_prefix: LIS
  label: capstone
github:
  repos:
    - LiBearden/sycophancy-eval
bench:
  surface: null
target_date: 2026-07-01
notes: |
  Initiative-level context, constraints, and why this lane matters.
---
```

The loader (`app/services/initiatives.py`) parses these files into typed models and exposes:

- `load_initiatives() -> list[Initiative]`
- `get_initiative(slug: str) -> Initiative | None`

This is read-only config loading. No user-state writes and no DB side effects.

## Relationship to LIS and BEN issues

Initiatives sit **above** issue trackers:

- A single initiative may map to many `LIS-*` tickets (operator strategy + external applications).
- The same initiative may also map to `BEN-*` tickets (bench implementation work).
- Issue trackers remain execution detail; initiative tracks intent and cross-surface grouping.

So the hierarchy is:

1. Initiative (strategic lane)
2. Issue(s) (`LIS-*`, `BEN-*`, and potentially others)
3. Concrete tasks/artifacts (PRs, docs, submissions, messages)

## Why config-first (not DB-first)

Initiatives are low-churn strategic metadata, not high-frequency user state. Config-first is preferred because it:

- keeps operator strategy version-controlled with normal diffs/review;
- makes intent auditable in-repo alongside architecture docs;
- avoids introducing new persistence/migrations for a small, stable domain;
- supports future consumers (`/focus`, MCP) from a deterministic source at boot.

If initiative state ever becomes dynamic (for example per-user progress, auto-status transitions, analytics joins), DB-backed state can be added later. Current scope deliberately keeps initiative as authored configuration.
