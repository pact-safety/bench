---
slug: c04-oss-contribution
title: "A merged contribution to a safety tool"
track: technical
weight: 3
effort_hours: 25
axes: [debugging, eval_design]
authored_by: claude_code_signal
authored_date: 2026-08-21
version: 1
---

## What it is

Code you wrote that now lives in a tool the field uses — Inspect, TransformerLens,
SAELens, nnsight, METR's task standard, or a comparable safety-relevant library.
Merged, in a release, used by people who do not know you. This is not on the
published criteria lists as its own bullet, but it is the fastest way to
demonstrate that you can work inside someone else's codebase, which is most of
what a research engineering role is.

## What strong looks like

- Merged into the upstream repo, not a fork you maintain alone.
- It solves a problem someone else had: an open issue, a bug you hit and
  reported first, a gap discussed in the repo's issues or Discord.
- The PR includes tests. In an eval library, an untested contribution is a
  liability and maintainers treat it as one.
- The PR conversation shows you taking review well — you changed the design when
  the maintainer pushed back, and you can point at the exchange.
- Scope is coherent: one behaviour change, not a drive-by refactor bundled with
  a feature.
- Non-trivial. A new solver, a scorer, a provider integration, a correctness fix
  in the sampling path — something a maintainer would otherwise have had to do.
- Ideally it is now used: someone's eval imports your scorer.

## What weak looks like

- Typo and docs-link PRs. They are genuinely welcome contributions and they are
  worth nothing as evidence of engineering ability. Do not list five of them.
- A large unsolicited refactor, opened cold, still unmerged eight months later.
  This is a negative signal about judgement, not a neutral one.
- A fork with your feature in it and no upstream PR.
- A PR that was merged because the maintainer rewrote it for you.
- Adding a dependency to do something the library already does — the reviewer
  reads this as not having read the codebase.
- Contributions to a repo with no users, including your own.
- An open PR listed as if merged. Reviewers click the link.

## How to produce it

1. Pick the tool you already use. If you built `c01` in Inspect, you have hit
   its rough edges — that is your issue list. Contributing to a library you do
   not use produces the weak version by default.
2. Read `CONTRIBUTING.md` and the last twenty merged PRs before writing anything.
   Match the house style; maintainers reject on style friction more than on
   substance.
3. Start with a reproduction issue, not a PR. A clean bug report with a minimal
   repro is itself a contribution and it tells you whether the maintainers want
   the fix.
4. Wait for a maintainer to confirm the direction. Unsolicited large PRs are the
   most common way this effort is wasted.
5. Keep the diff small. Tests in the same PR.
6. Respond to review within a day or two while the context is live. Stalled PRs
   die.
7. If it is rejected, ask what would have been accepted, and write that down —
   the rejection reason is more useful feedback than most applications return.

## How a selector sees it

They open the PR link and look at three things: merged or not, size of the diff,
and whether the conversation shows a maintainer engaging seriously with you.
Fifteen seconds. What makes it skippable: an unmerged link, a docs-only diff, or
a PR with no discussion. The conversation is the signal — it is a public record
of you being reviewed, which is the closest thing a reviewer has to seeing you
work with a mentor.
