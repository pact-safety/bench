---
slug: mechinterp
title: "Mechanistic Interpretability — first steps"
description: "catmcgee's 6-step open-source path from 'I've never trained a neural network' to 'I can read current mech interp papers.' Hands-on notebooks: superposition, grokking, induction heads, the IOI circuit, and sparse autoencoders. Pairs well with ARENA 3.0 — start here for a faster on-ramp, go to ARENA for depth."
source_url: "https://github.com/catmcgee/learn-mechanistic-interpretability"
chapters:
  - title: "6-step path"
    sections:
      - title: "0. MNIST template weights"
        url: "https://github.com/catmcgee/learn-mechanistic-interpretability/tree/main/00-mnist-templates"
        kind: external_exercise
        duration_min: 90
        domain_tags: [interpretability, mnist, weight visualization, neural networks]
        axes: [transformer_internals, mechanistic_interpretability]
      - title: "1. Toy models of superposition"
        url: "https://github.com/catmcgee/learn-mechanistic-interpretability/tree/main/01-toy-models-superposition"
        kind: external_exercise
        duration_min: 150
        domain_tags: [superposition, features, polysemanticity, toy models]
        axes: [mechanistic_interpretability]
        depends_on: [0]
      - title: "2. Grokking modular addition"
        url: "https://github.com/catmcgee/learn-mechanistic-interpretability/tree/main/02-grokking-modular-addition"
        kind: external_exercise
        duration_min: 150
        domain_tags: [grokking, generalization, modular arithmetic, training dynamics]
        axes: [mechanistic_interpretability, training_mechanics]
        depends_on: [1]
      - title: "3. Induction heads"
        url: "https://github.com/catmcgee/learn-mechanistic-interpretability/tree/main/03-induction-heads"
        kind: external_exercise
        duration_min: 150
        domain_tags: [induction heads, attention, in-context learning, circuits]
        axes: [transformer_internals, mechanistic_interpretability]
        depends_on: [2]
      - title: "4. IOI circuit in GPT-2 small"
        url: "https://github.com/catmcgee/learn-mechanistic-interpretability/tree/main/04-ioi-circuit"
        kind: external_exercise
        duration_min: 180
        domain_tags: [ioi, activation patching, causal tracing, circuits, gpt-2]
        axes: [mechanistic_interpretability]
        depends_on: [3]
      - title: "5. Sparse autoencoders"
        url: "https://github.com/catmcgee/learn-mechanistic-interpretability/tree/main/05-sparse-autoencoders"
        kind: external_exercise
        duration_min: 180
        domain_tags: [sparse autoencoders, dictionary learning, feature discovery, saes]
        axes: [mechanistic_interpretability]
        depends_on: [4]
---

# Mechanistic Interpretability — first steps

A short, hands-on on-ramp into mech interp by [catmcgee](https://github.com/catmcgee),
linked here as an external curriculum. Six notebooks take you from weight
visualization through superposition, grokking, induction heads, the IOI
circuit, and sparse autoencoders — the conceptual spine you need before
current interpretability papers stop reading like a foreign language.

Each step is a Jupyter notebook with a teaching README; open the source
links to run them (Colab-compatible). Mark a step complete here once you've
worked through its notebook.

**Where this fits:** this is the faster on-ramp. Once these six click,
[ARENA 3.0](https://github.com/callummcdougall/ARENA_3.0)'s transformer-
interpretability chapter goes much deeper on the same circuits — the bench
carries that as a separate track.

All content lives in the source repository and is the author's work; the
bench only indexes it as a learning path.
