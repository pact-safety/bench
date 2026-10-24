---
slug: e37-why-superposition-happens
kind: exercise
title: "Trace the arithmetic that makes superposition worth it"
source: "prep for ARENA 1.5.4 Superposition & SAEs"
duration_min: 9
axes: [mechanistic_interpretability]
domain_tags: [superposition, polysemanticity, sparsity, interference]
arena_section: "1.5.4"
pedagogy: trace
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** A residual stream of `d_model = 512`. You suspect the
model tracks roughly 10,000 distinct features. Each feature `i` is
written along a unit direction `f_i` and read back by dotting with
`f_i`. Features are sparse: on any given token about 5 of the 10,000
are active.

**Question.** Predict each quantity, with the reasoning.

1. How many *exactly* orthogonal directions fit in 512 dimensions?
2. Two directions drawn at random on the unit sphere in 512
   dimensions — what is the typical size of `f_i · f_j`?
3. Reading feature `i` while feature `j` is also active: how large
   is the interference, relative to feature `i`'s own signal?
4. What does storing 10,000 directions in 512 dimensions force to be
   true about the 512 neuron-basis directions?

Answer all four before revealing.

<details>
<summary>reveal</summary>

1. **512.** Exact orthogonality caps out at the dimension. If the
   model needed 10,000 non-interfering features it would need 10,000
   dimensions, and it does not have them.

2. **Mean 0, typical magnitude ≈ 0.044.** By symmetry the expected
   dot product is zero; the expected *square* is `1/d`, so the RMS is
   `1/sqrt(512) ≈ 0.044`. Random high-dimensional directions are
   nearly orthogonal, and get more so as `d` grows. This is why
   "almost orthogonal" is cheap and "orthogonal" is not.

3. **About 4% of the interfering feature's activation** — small
   compared to the ~1.0 you read for a feature that is actually
   present. And it is *rare*: with 5 of 10,000 features active, any
   specific pair of features almost never co-occurs. Sparsity is what
   converts a small per-pair error into a negligible expected error.
   Push sparsity down — many features active at once — and the
   interference terms add up and the model stops doing this.

4. **The feature directions cannot line up with the neuron basis.**
   There are only 512 basis directions for 10,000 features, so
   feature directions sit at generic angles to them. Each neuron gets
   nonzero projection from many unrelated features (polysemantic),
   and each feature is spread across many neurons.

</details>

**Key insight.** Superposition is a trade the model takes because
sparsity makes interference rare and high dimension makes it small.
The bill it pays is that the neuron basis stops being the feature
basis — which is exactly the problem an SAE is built to undo.
