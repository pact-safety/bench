# Proposals

Design drafts for changes that need explicit operator approval before any code lands. Each doc states the problem, sketches the design, calls out open decisions that need operator input, and estimates scope.

Status legend:

- **draft** — written by a contributor, awaiting operator review
- **approved** — operator has signed off on the design; implementation PR(s) can proceed
- **rejected** — operator declined; doc preserved as a record of the consideration
- **superseded** — replaced by a later proposal (linked)

## Current proposals

| File | Status | One-liner |
|---|---|---|
| [`chat-outcomes-table.md`](./chat-outcomes-table.md) | **approved 2026-05-25** — PR A shipped (#253) | Migrate MCP-written chat outcomes from `user_settings.chat_outcomes` JSON to a dedicated `chat_outcomes` table |
| [`per-attempt-initiative-tagging.md`](./per-attempt-initiative-tagging.md) | **approved 2026-05-25** — ship after chat-outcomes verifies | Tag attempts/reflections with `initiative_slug` so `/focus` stops attributing all bench-surface activity to all bench-surface initiatives |
| [`rss-news-feed.md`](./rss-news-feed.md) | **approved 2026-05-25** — Phase 1 only initially | RSS poller → `/news`. Surfaces JD-relevant AI news. Home-margin surfacing (Phase 3) deferred to "if /news usage proves the bench is the right surface" |
| [`connecting-route.md`](./connecting-route.md) | **draft — Low priority, post-capstone (post-2026-07-15)** | Networking tracker with warmth monitor. Linked from GH #256; ships only when arXiv deadline isn't crowding cognitive space |
| [`writing-pipeline.md`](./writing-pipeline.md) | **draft — Low / phased, post-capstone (post-2026-07-15)** | Expand `/writings` into a kanban pipeline + Markdown editor + live preview + export. Sonnet assists structure & clarity only — **never writes substance**. Linked from GH #258 |
| [`onboarding-zero-states.md`](./onboarding-zero-states.md) | **draft — operator decision** | Pattern C contextual-CTA polish on `/tracks`, `/reflect`, `/aim`. Audit + 3-PR scope. Trigger: when next showing the bench to an unfamiliar visitor |
| [`regression-testing-coverage.md`](./regression-testing-coverage.md) | **draft — operator decision** | Five regressions slipped past unit tests in the past two weeks. Phased plan: content lints → script smoke → MCP integration → HTML route smoke → post-deploy. Phases 1-3 are ~7h total |

**Cross-cutting decisions (operator 2026-05-25):**

1. **Shipping order**: `chat-outcomes` → `per-attempt tagging` → `rss-news` (substrate first, then data-quality, then user-facing)
2. **Tagging mode** (per-attempt proposal): optional, defaults to `settings.active_initiative`
3. **News surface** (rss-news proposal): `/news` only initially. Home margin deferred — Phase 3 ships only if `/news` usage shows the bench is the right surface for news consumption
4. **next_actions storage** (chat-outcomes proposal): `TEXT` string. Matches current MCP behavior; no tool-signature change required

## How to use

1. Operator reads the doc, leaves comments on the PR (or in-thread)
2. Operator updates the doc's open-decisions section with their answers (or asks the proposer to)
3. Status changes from `draft` to `approved`
4. Implementation issues filed against the design, work proceeds

This pattern keeps strategy decisions visible and revisitable. It also means the operator's "no, not yet" can land somewhere durable — the doc stays as a rationale record even if the work doesn't happen.
