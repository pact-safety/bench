---
slug: e40-ioi-total-vs-direct-effect
kind: exercise
title: "IOI — predict what each patching experiment reports"
source: "prep for ARENA 1.4.1 Indirect Object Identification"
duration_min: 12
axes: [mechanistic_interpretability]
domain_tags: [ioi, logit diff, activation patching, path patching]
arena_section: "1.4.1"
pedagogy: trace
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** The IOI template, on GPT-2 small:

```text
"When Mary and John went to the store, John gave a drink to"
        IO           S                  S              -> " Mary"
```

The indirect object `IO` appears once, the subject `S` twice. The
metric is a logit difference at the final position:

```python
logit_diff = (logits[range(B), -1, io_tok]
              - logits[range(B), -1, s_tok]).mean()
```

The corrupted prompt is the ABC variant — all three names distinct:
`"When Alice and Bob went to the store, Charlie gave a drink to"` —
scored against the *same* `io_tok` and `s_tok`. Head 9.9 is a name
mover: direct logit attribution ranks it the single largest positive
contributor to the clean logit diff.

**Question.** Predict each number, at least in sign and relative
size, with the reasoning.

1. The clean `logit_diff`.
2. The corrupted `logit_diff`.
3. Run the clean prompt, replace 9.9's output with its corrupted
   value: how far does `logit_diff` fall?
4. Path-patch the same corrupted value along **only** the edge
   9.9 → logits, holding every other component's input at its clean
   value: more or less of a fall than (3)?

Commit to all four before revealing.

<details>
<summary>reveal</summary>

1. **Clearly positive** — this is the behaviour we are explaining.
   The model puts more probability on the name it saw once than the
   one it saw twice.
2. **Near zero.** With three distinct names there is no repeated
   subject and no IO structure, and neither `" Mary"` nor `" John"`
   is in the prompt at all. Both logits are low and there is no
   reason for one to beat the other. That is the point of the ABC
   control: it destroys the *task*, not the grammar.
3. **A partial fall — noticeably short of zero.** This is the result
   that confuses people, since (per DLA) 9.9 is the biggest single
   contributor. Patching one component measures its **total** effect:
   everything downstream re-runs on the changed activation. In GPT-2
   small the *backup* name mover heads in layers 10–11 raise their
   own contribution when a name mover is removed, restoring much of
   the logit diff. The measured drop is the direct effect *minus*
   that compensation.
4. **A larger fall than (3).** In path patching the backup heads
   receive their clean inputs, so they never learn anything changed
   and cannot compensate. What is left is the **direct** effect of
   9.9 on the logits — close to what DLA attributed to it.

</details>

**Key insight.** Activation patching answers "does the output depend
on this component" — a total effect, which self-repair can hide.
Path patching answers "does this specific edge carry the effect", so
it recovers a graph of connections rather than a list of important
nodes. When the two disagree, the gap between them *is* the
compensation, and that is a finding, not an error.
