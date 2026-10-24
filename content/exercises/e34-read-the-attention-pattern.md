---
slug: e34-read-the-attention-pattern
kind: exercise
title: "Name the head from its pattern"
source: "prep for ARENA 1.2 Intro to Mech Interp"
duration_min: 9
axes: [mechanistic_interpretability]
domain_tags: [attention pattern, induction head, previous token head, transformerlens]
arena_section: "1.2"
pedagogy: trace
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** Token sequence `A B C A B`, positions 0–4. Two heads'
patterns from `cache["pattern", 0]`, each `(5, 5)`, rows are
`query_pos`, columns are `key_pos`, rows sum to 1.

**Head P**

```
        k0    k1    k2    k3    k4
q0    1.00     .     .     .     .
q1    0.95  0.05     .     .     .
q2    0.03  0.95  0.02     .     .
q3    0.02  0.03  0.93  0.02     .
q4    0.01  0.02  0.03  0.92  0.02
```

**Head Q**

```
        k0    k1    k2    k3    k4
q0    1.00     .     .     .     .
q1    0.90  0.10     .     .     .
q2    0.88  0.07  0.05     .     .
q3    0.05  0.85  0.05  0.05     .
q4    0.04  0.05  0.86  0.03  0.02
```

**Question.** Name each head. Then explain why row 0 is uninformative
for both, and why rows 1 and 2 of Head Q look like nothing at all.

<details>
<summary>reveal</summary>

**Head P is a previous-token head.** All the mass sits on the
sub-diagonal: `q_i` attends to `k_{i-1}`, every row, regardless of what
the tokens are. Content-independent, position-only.

**Head Q is an induction head.** Read row 3: the current token is `A`,
which last appeared at position 0, and the head attends to position 1 —
the token *after* the earlier `A`. Row 4 does the same: current token
`B`, earlier `B` at position 1, attention on position 2. That is the
induction rule — "find the previous copy of me, then look one to the
right" — and it predicts the sequence will repeat.

**Why row 0 is uninformative:** the causal mask leaves `q0` exactly one
legal key, so `softmax` over a single entry is forced to `1.00`. It
carries no evidence about either head. Ignore row 0 always.

**Why Q's rows 1 and 2 look like nothing:** at positions 1 and 2, no
token has repeated yet, so there is no earlier copy to induct from.
The head dumps its mass on position 0 — the standard null behavior for
a head with nothing to do. Interpreted carelessly this looks like an
attend-to-first-token head, and that reading is wrong; it is the
absence of a match, not a preference.

**Why this matters:** the induction pattern needs a previous-token head
one layer earlier to have written "the token before me was `A`" into
position 1's residual stream. Head Q's QK circuit is reading that,
which is why induction is a two-layer circuit and never shows up in a
one-layer model.

</details>

**Key insight.** A previous-token head's pattern depends only on
position; an induction head's depends on token content, so you can only
tell them apart on a sequence with a repeat. Judge a pattern on the
rows where the behavior is *possible* — early rows and row 0 are
artifacts of the mask.
