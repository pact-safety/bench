---
slug: e35-train-a-linear-probe
kind: exercise
title: "Order the probe-training pipeline"
source: "prep for ARENA 1.3.1 Linear Probes"
duration_min: 10
axes: [mechanistic_interpretability, eval_design]
domain_tags: [linear probe, activations, leakage, train test split]
arena_section: "1.3.1"
pedagogy: parsons
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** 2,000 review sequences, each exactly 64 tokens, each
carrying one binary sentiment label. You want a linear probe that
reads the label off the layer-6 residual stream at a *single token
position*. So every one of the 2000 × 64 = 128,000 positions is one
training example, and all 64 tokens of a sequence inherit that
sequence's label.

**Question.** Put these into the order that trains an honest probe.
Exactly one line must not be used at all — name it and say why.

```python
A   X_train = acts[tr].reshape(-1, d_model)
    X_test  = acts[te].reshape(-1, d_model)
B   probe = LogisticRegression(max_iter=1000).fit(X_train, y_train)
C   _, cache = model.run_with_cache(tokens)      # tokens: (2000, 64)
D   y_train = labels[tr].repeat_interleave(64)
    y_test  = labels[te].repeat_interleave(64)
E   tr, te = split(arange(2000), frac=0.8)       # ids of sequences
F   acts = cache["resid_post", 6]                # (2000, 64, d_model)
G   X_all = acts.reshape(-1, d_model)
    y_all = labels.repeat_interleave(64)
    X_train, X_test, y_train, y_test = train_test_split(X_all, y_all)
H   print("test acc:", probe.score(X_test, y_test))
```

Commit to an order before revealing.

<details>
<summary>reveal</summary>

**C, F, E, A, D, B, H.** **G is the line you must not use.**

The constraints that force this order:

- **C before F** — the cache has to exist before you index it.
- **E before A and D** — this is the whole exercise. The split
  happens over *sequence ids*, while the design matrix is still
  `(2000, 64, d_model)`. Once you flatten, the sequence boundary is
  gone and you can no longer split along it.
- **A and D must use the same index set and agree on row order.**
  `reshape(-1, d_model)` lays rows out sequence-major
  (seq 0's 64 tokens, then seq 1's), and `repeat_interleave(64)`
  produces labels in exactly that order. Use `repeat` instead of
  `repeat_interleave` and every label is attached to the wrong row.
- **B before H** — nothing to score until the probe is fit.

**Why G leaks.** It shuffles at the *token* level, so nearly all
2,000 sequences land tokens in both splits. Two positions from one
sequence share a prefix, so their residual streams are strongly
correlated — a test token is close to its own training neighbours in
activation space. The probe can score well by matching those
neighbours rather than by learning the feature. Test accuracy rises
and stops measuring generalization.

One more thing worth doing on real data: drop position 0 (BOS) and
any padding positions before flattening. Their activations are not
about the sequence content and they dilute the probe.

</details>

**Key insight.** Split on the unit that *generated* the correlation
— here the sequence — not on the row of the design matrix. If two
rows could not have been produced independently of each other, they
must never straddle the train/test boundary.
