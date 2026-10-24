---
slug: e31-cache-keeps-the-batch-dim
kind: exercise
title: "The cache index that crashes on batch 1"
source: "prep for ARENA 1.2 Intro to Mech Interp"
duration_min: 7
axes: [mechanistic_interpretability, debugging]
domain_tags: [transformerlens, run_with_cache, hook_pattern, indexing]
arena_section: "1.2"
pedagogy: debug
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Symptom.** You tokenized a single prompt, ran it, and tried to plot
head 5's attention pattern. You get:

```
IndexError: index 5 is out of bounds for dimension 0 with size 1
```

You change `5` to `0` and the error goes away — but `head_5` comes out
`(12, 7, 7)`, which is three-dimensional and not a head pattern at
all. `0` is also the only index that does not raise.

```python
tokens = model.to_tokens("The cat sat on the mat")   # (1, 7)
logits, cache = model.run_with_cache(tokens)

pattern = cache["pattern", 0]     # layer 0
head_5  = pattern[5]
imshow(head_5)
```

**Question.** Name the bug, the fix, and what the symptom told you.

<details>
<summary>reveal</summary>

**Bug.** `cache["pattern", 0]` is `(batch, n_heads, query_pos,
key_pos)` = `(1, 12, 7, 7)`. `pattern[5]` indexes the **batch** axis,
not the head axis.

**Fix.** `head_5 = pattern[0, 5]`, giving `(7, 7)`.

**What the symptom told you.** The error text named the axis for you:
"dimension 0 with size 1" is a batch of one. Any time a TransformerLens
index blows up with `size 1`, you have landed on the batch dim. The
follow-up symptom confirmed it: one index consumed a 4-D tensor and
left 3 dims, so you had spent your index on an axis you did not mean
to spend it on.

Two things worth internalizing about the cache:

- `run_with_cache` returns an `ActivationCache` keyed by full hook
  names, so `cache["blocks.0.attn.hook_pattern"]` and
  `cache["pattern", 0]` are the same tensor. The tuple form is
  shorthand for `utils.get_act_name`, not a different lookup.
- **Every cached tensor keeps its batch dim**, including when you ran
  one prompt. The cache stores exactly what flowed through the hook;
  it does not squeeze anything for your convenience.

</details>

**Key insight.** `run_with_cache` caches activations verbatim, batch
axis included — so the first index into any cache entry is almost
always `0`, and an `IndexError` mentioning `size 1` means you forgot it.
