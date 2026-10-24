---
slug: e12-reduce-names-the-axis
kind: exercise
title: "Fill the blank in an einops reduce pattern"
source: "prep for ARENA 0.0 Prerequisites"
duration_min: 6
axes: [algorithmic, debugging]
domain_tags: [einops, reduce, shapes, axes]
arena_section: "0.0"
pedagogy: faded
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** `logits` is `Float[Tensor, "batch seq vocab"]` with shape
`(4, 128, 50257)`. You want the mean logit per vocab entry, averaged
over the sequence, keeping batch separate — target shape
`(4, 50257)`.

```python
out = einops.reduce(logits, "batch seq vocab -> ____", "mean")
```

**Question.** What goes in the blank, and what does the equivalent
`.mean(dim=...)` call fail to protect you from?

Answer both before revealing.

<details>
<summary>reveal</summary>

The blank is `batch vocab`.

```python
out = einops.reduce(logits, "batch seq vocab -> batch vocab", "mean")
```

In `reduce`, you don't name the axis you're collapsing — you name the
axes you're **keeping**, and whatever you left out gets reduced. `seq`
is absent from the right side, so `seq` is what the mean runs over.

The equivalent is `logits.mean(dim=1)`. It produces the same numbers
today. What it fails to protect you from: the left side of a reduce
pattern is a rank assertion. If some upstream change hands you a
4-D tensor — say `(4, 8, 128, 50257)` after adding a heads axis — the
pattern raises `EinopsError` because three names can't match four
axes. `logits.mean(dim=1)` happily averages over the heads axis
instead, returns a plausible shape, and you find out three plots
later.

</details>

**Key insight.** `reduce` names the axes that survive, and its left
side is a free rank check on every call — that check is the reason to
prefer it over `.sum(dim=)` / `.mean(dim=)`, not the readability.
