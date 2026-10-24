---
slug: arena_3
title: "ARENA 4.0"
description: "Callum McDougall's ARENA curriculum — fundamentals through alignment science. Bench prep exercises run before each section; checkpoints are gated on problems you actually run green."
source_url: "https://github.com/callummcdougall/ARENA_3.0"
chapters:
  - title: "Chapter 0 — Fundamentals"
    sections:
      - title: "0.0 Prerequisites"
        url: "https://learn.arena.education/chapter0_fundamentals/00_prereqs/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [python, pytorch, einops, einsum, tensor manipulation]
        axes: [algorithmic]
        prep: [e11-rearrange-pattern-binding, e12-reduce-names-the-axis, e13-repeat-or-broadcast, e14-which-index-gets-summed]
        cold_checkpoint: [15-einsum-batched-matmul]
        checkpoint: "Rewrite a loop-based tensor computation as one einops/einsum call and state what each axis letter binds to."

      - title: "0.1 Ray Tracing"
        url: "https://learn.arena.education/chapter0_fundamentals/01_ray_tracing/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [ray tracing, linear algebra, batching]
        axes: [algorithmic, transformer_internals]
        depends_on: [0]
        prep: [e15-spot-the-indexing-bug, e16-de-loop-into-a-pair-grid, e17-ray-segment-as-linear-solve, e18-batch-the-intersection-check]
        checkpoint: "Turn a per-item Python loop into a single batched tensor op over a full pair grid, and say what each axis of the result means."

      - title: "0.2 CNNs & ResNets"
        url: "https://learn.arena.education/chapter0_fundamentals/02_cnns/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [cnn, resnet, batchnorm, computer vision]
        axes: [transformer_internals, training_mechanics]
        depends_on: [1]
        prep: [e19-conv2d-output-shape, e20-residual-gradient-path, e21-batchnorm-train-eval]
        checkpoint: "Predict a conv stack's output shape from first principles, and explain what a residual connection does to gradient flow."

      - title: "0.3 Optimization"
        url: "https://learn.arena.education/chapter0_fundamentals/03_optimization/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [optimizer, adam, momentum, learning rate]
        axes: [training_mechanics]
        depends_on: [1]
        prep: [e22-sgd-momentum-ordering, e23-adam-subgoals, e24-warmup-lr-lambda]
        cold_checkpoint: [12-minimal-training-loop, 11-teacher-forcing-grad-accum]
        checkpoint: "Write an optimizer step from scratch and say what each buffer holds and why bias correction exists."

      - title: "0.4 Backpropagation"
        url: "https://learn.arena.education/chapter0_fundamentals/04_backprop/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [backpropagation, autograd, gradient]
        axes: [training_mechanics, transformer_internals]
        depends_on: [3]
        prep: [e25-backward-pass-by-hand, e26-backprop-subgoals]
        cold_checkpoint: [22-debug-grad-accum-scale, 25-debug-detach-block]
        checkpoint: "Hand-execute a backward pass over a branching graph, and explain why .grad accumulates and zero_grad() exists."

      - title: "0.5 VAEs & GANs"
        url: "https://learn.arena.education/chapter0_fundamentals/05_vaes_gans/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [vae, gan, generative modeling]
        axes: [training_mechanics]
        depends_on: [4]
        checkpoint: "Explain the two-player training dynamic and name one concrete failure mode you would watch the loss curves for."

  - title: "Chapter 1 — Transformer Interpretability"
    sections:
      - title: "1.1 Transformers from Scratch"
        url: "https://learn.arena.education/chapter1_transformer_interp/01_transformers/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [transformer, attention, residual stream]
        axes: [transformer_internals]
        depends_on: [4]
        prep: [e27-residual-stream-round-trip, e28-split-into-heads]
        cold_checkpoint: [01-scaled-dot-product-attention, 02-multi-head-attention-reshape, 03-layernorm-from-scratch]
        checkpoint: "Implement multi-head attention from scratch and justify the head split and the 1/sqrt(d_head) scale."

      - title: "1.2 Intro to Mech Interp"
        url: "https://learn.arena.education/chapter1_transformer_interp/02_intro_mech_interp/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [transformerlens, hooks, activation patching]
        axes: [mechanistic_interpretability]
        depends_on: [6]
        prep: [e29-qk-circuit-vs-ov-circuit, e30-hook-z-index, e31-cache-keeps-the-batch-dim, e32-activation-patching-order, e33-logit-lens-subgoals, e34-read-the-attention-pattern]
        cold_checkpoint: [16-compare-attention-impls, 19-debug-causal-mask]
        checkpoint: "Run activation patching end to end: name the two runs, the site you patch, and the metric you read."

      - title: "1.3.1 Linear Probes"
        url: "https://learn.arena.education/chapter1_transformer_interp/11_probing/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [linear probes, representations]
        axes: [mechanistic_interpretability]
        depends_on: [7]
        prep: [e35-train-a-linear-probe, e36-probe-accuracy-is-not-use]
        cold_checkpoint: [32-linear-probe-split]
        checkpoint: "Train a probe with a leakage-free split and state what its accuracy does and does not license you to claim."

      - title: "1.3.2 Function Vectors & Model Steering"
        url: "https://learn.arena.education/chapter1_transformer_interp/12_function_vectors/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [function vectors, steering, interventions]
        axes: [mechanistic_interpretability]
        depends_on: [7]
        checkpoint: "Extract a steering vector and describe the control condition that separates steering from prompt effects."

      - title: "1.3.3 Interpretability with SAEs"
        url: "https://learn.arena.education/chapter1_transformer_interp/13_saes/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [sae, sparse autoencoder]
        axes: [mechanistic_interpretability]
        depends_on: [7]
        prep: [e39-what-makes-a-good-sae]
        cold_checkpoint: [31-sae-forward-and-loss]
        checkpoint: "Implement an SAE forward pass and loss, and say what raising the sparsity coefficient trades away."

      - title: "1.3.4 Activation Oracles"
        url: "https://learn.arena.education/chapter1_transformer_interp/14_activation_oracles/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [activation oracles, probing]
        axes: [mechanistic_interpretability]
        depends_on: [7]
        checkpoint: "Explain what an oracle can tell you that a probe cannot, and the assumption it buys that with."

      - title: "1.4.1 Indirect Object Identification"
        url: "https://learn.arena.education/chapter1_transformer_interp/21_ioi/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [ioi, circuits, logit diff]
        axes: [mechanistic_interpretability]
        depends_on: [7]
        prep: [e40-ioi-total-vs-direct-effect]
        checkpoint: "Describe the IOI task template and the logit-diff metric, and explain what path patching adds over activation patching."

      - title: "1.4.2 SAE Circuits"
        url: "https://learn.arena.education/chapter1_transformer_interp/22_sae_circuits/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [sae, circuits, feature tracing]
        axes: [mechanistic_interpretability]
        depends_on: [10, 12]
        checkpoint: "Trace one feature through a circuit and state the evidence that makes it a circuit claim rather than a correlation."

      - title: "1.5.1 Balanced Bracket Classifier"
        url: "https://learn.arena.education/chapter1_transformer_interp/31_brackets/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [toy models, algorithmic, circuits]
        axes: [mechanistic_interpretability, algorithmic]
        depends_on: [7]
        checkpoint: "State the algorithm the model implements and the evidence in the attention pattern that shows it."

      - title: "1.5.2 Grokking & Modular Arithmetic"
        url: "https://learn.arena.education/chapter1_transformer_interp/32_grokking/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [grokking, modular arithmetic]
        axes: [mechanistic_interpretability, algorithmic]
        depends_on: [7]
        checkpoint: "Explain what changes internally at the grokking transition, and what the loss curves alone would have missed."

      - title: "1.5.3 OthelloGPT"
        url: "https://learn.arena.education/chapter1_transformer_interp/33_othellogpt/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [world representations, toy models]
        axes: [mechanistic_interpretability]
        depends_on: [7]
        checkpoint: "Explain what a probe finding a board state does and does not establish about the model using it."

      - title: "1.5.4 Superposition & SAEs"
        url: "https://learn.arena.education/chapter1_transformer_interp/34_superposition/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [superposition, sae, toy models]
        axes: [mechanistic_interpretability]
        depends_on: [10]
        prep: [e37-why-superposition-happens, e38-sae-forward-and-loss]
        cold_checkpoint: [31-sae-forward-and-loss]
        checkpoint: "Explain why a model represents more features than it has dimensions, and what that does to neuron-level interpretation."

  - title: "Chapter 2 — Reinforcement Learning"
    sections:
      - title: "2.1 Intro to RL"
        url: "https://learn.arena.education/chapter2_rl/01_intro_rl/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [rl, bandits, exploration]
        axes: [training_mechanics, algorithmic]
        depends_on: [4]
        prep: [e41-rollout-buffer-shapes]
        checkpoint: "Map the RL loop to concrete shapes and explain why an exploration schedule exists."

      - title: "2.2 DQN & VPG"
        url: "https://learn.arena.education/chapter2_rl/02_dqn_vpg/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [dqn, policy gradient, target network]
        axes: [training_mechanics]
        depends_on: [18]
        prep: [e42-epsilon-decay-blank, e43-dqn-moving-target, e44-policy-gradient-subgoals]
        checkpoint: "Explain the target network's job and what the policy-gradient objective multiplies together."

      - title: "2.3 PPO"
        url: "https://learn.arena.education/chapter2_rl/03_ppo/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [ppo, clipping, advantage]
        axes: [training_mechanics]
        depends_on: [19]
        prep: [e45-ppo-clip-ordering]
        cold_checkpoint: [33-gae-advantages, 34-ppo-clipped-objective]
        checkpoint: "Implement GAE and the clipped surrogate, and get the loss sign right in both."

      - title: "2.4 RLHF"
        url: "https://learn.arena.education/chapter2_rl/04_rlhf/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [rlhf, kl penalty, reward model]
        axes: [training_mechanics, ai_safety_fundamentals]
        depends_on: [20]
        prep: [e46-rlhf-kl-penalty]
        checkpoint: "Explain what the KL penalty protects against and what happens to the policy as beta goes to zero."

      - title: "2.5 MCTS & AlphaZero"
        url: "https://learn.arena.education/chapter2_rl/05_mcts_alphazero/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [mcts, alphazero, search]
        axes: [algorithmic, training_mechanics]
        depends_on: [20]
        checkpoint: "Walk one MCTS iteration through select, expand, evaluate, backup, and say what the tree statistics hold."

  - title: "Chapter 3 — LLM Evaluations"
    sections:
      - title: "3.1 Intro to Evals"
        url: "https://learn.arena.education/chapter3_llm_evals/01_intro_evals/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [evals, threat model, measurement]
        axes: [eval_design, ai_safety_fundamentals]
        depends_on: [6]
        prep: [e47-threat-model-to-eval-claim, e48-discriminative-eval-item, e49-position-bias-gap]
        cold_checkpoint: [13-sycophancy-eval-scoring, 35-eval-item-discrimination]
        checkpoint: "Take a vague worry to an operationalized claim with a metric, a control, and a falsifier."

      - title: "3.2 Dataset Generation"
        url: "https://learn.arena.education/chapter3_llm_evals/02_dataset_gen/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [dataset generation, diversity, dedup]
        axes: [eval_design, data_pipeline]
        depends_on: [23]
        prep: [e50-diversity-collapse-generation]
        cold_checkpoint: [14-jsonl-pipeline]
        checkpoint: "Generate an eval set and show the measurement that proves it is not mode-collapsed."

      - title: "3.3 Running Evals with Inspect"
        url: "https://learn.arena.education/chapter3_llm_evals/03_running_evals/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [inspect, solver, scorer]
        axes: [eval_design]
        depends_on: [23]
        prep: [e51-assemble-inspect-task]
        cold_checkpoint: [e03-format-robustness-gap]
        checkpoint: "Assemble a Task from dataset, solver and scorer, and say what each piece owns."

      - title: "3.4 LLM Agents"
        url: "https://learn.arena.education/chapter3_llm_evals/04_llm_agents/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [agents, tool use, traces]
        axes: [eval_design, ai_safety_fundamentals]
        depends_on: [25]
        prep: [e52-score-the-agent-trace]
        cold_checkpoint: [e01-paired-eval-position-debias]
        checkpoint: "Score an agent from its trace rather than its final answer, and justify the rubric."

      - title: "3.5 AI Control"
        url: "https://learn.arena.education/chapter3_llm_evals/05_ai_control/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [ai control, red team, monitoring]
        axes: [ai_safety_fundamentals, eval_design]
        depends_on: [26]
        checkpoint: "State a control protocol's threat model and the red-team move it is designed to survive."

  - title: "Chapter 4 — Alignment Science"
    sections:
      - title: "4.1 Emergent Misalignment"
        url: "https://learn.arena.education/chapter4_alignment_science/1_emergent_misalignment/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [emergent misalignment, finetuning]
        axes: [ai_safety_fundamentals]
        depends_on: [23]
        checkpoint: "Describe the finetuning setup that produces the effect and the control that rules out the obvious alternative."

      - title: "4.2 Science of Misalignment"
        url: "https://learn.arena.education/chapter4_alignment_science/2_science_misalignment/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [misalignment, science]
        axes: [ai_safety_fundamentals]
        depends_on: [28]
        checkpoint: "State one hypothesis about a misalignment mechanism and the experiment that would falsify it."

      - title: "4.3 Interpreting Reasoning Models"
        url: "https://learn.arena.education/chapter4_alignment_science/3_reasoning_models/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [reasoning, chain of thought, faithfulness]
        axes: [mechanistic_interpretability, ai_safety_fundamentals]
        depends_on: [7]
        checkpoint: "Explain what CoT faithfulness means operationally and one way to measure it."

      - title: "4.4 LLM Psychology & Persona Vectors"
        url: "https://learn.arena.education/chapter4_alignment_science/4_persona_vectors/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [persona vectors, llm psychology]
        axes: [mechanistic_interpretability, ai_safety_fundamentals]
        depends_on: [28]
        checkpoint: "Extract a persona direction and state the control that distinguishes it from a prompt artifact."

      - title: "4.5 Investigator Agents"
        url: "https://learn.arena.education/chapter4_alignment_science/5_investigator_agents/"
        kind: external_exercise
        duration_min: 480
        domain_tags: [investigator agents, auditing]
        axes: [ai_safety_fundamentals, eval_design]
        depends_on: [26]
        checkpoint: "Describe what an investigator agent automates and where a human must still sign off."

---

ARENA is a coding-first curriculum in modern ML systems and interpretability.
The bench does not copy it — it links to the canonical material and adds the
layer ARENA deliberately leaves out: what to do *before* you open the notebook,
and how to know you actually got it.

Source: https://github.com/callummcdougall/ARENA_3.0 · exercises live at
https://learn.arena.education

## How to run this track

**Prep before practical.** Each section lists `prep` — short bench exercises
you work first, without a GPU and usually in under ten minutes each. They are
not a summary of the ARENA material. They are the shape traces, the subgoal
decompositions, and the ordering puzzles that make the ARENA function body
possible to start. The failure this fixes is specific and common: strong people
open a section, meet a typed signature over a `raise NotImplementedError()`,
and stall — not because the concept is beyond them, but because nothing in the
docstring says what the *pieces* are.

**Checkpoints are gated on running code.** A section with a
`cold_checkpoint` will not mark complete until those bench problems pass their
tests, from a cold start, with no notebook open. Sections without one keep the
older understanding check and say so. The distinction is deliberate: a
self-assessment after a Colab session is exactly the thing that tabbing through
someone else's solution lets you fake.

**Timebox like ARENA tells you to.** Their own guidance: if you are
significantly over the suggested time, read the solution and move on. Getting
stuck on one exercise blocks the whole section. The prep exercises exist to
make that happen less often, not to add another thing to get stuck on.

## The six-week shape

ARENA's own planner allocates one section per day at ~8 hours, and derives
`weeks = 4 + (1 if you include Chapter 0)`. Six weeks with Chapter 0 is the
uncompressed plan, with room at the end:

| Week | Content |
|---|---|
| 1 | Chapter 0 — Fundamentals |
| 2 | Chapter 1 — Transformer interpretability |
| 3 | Chapter 2 — RL |
| 4 | Chapter 3 — Evals |
| 5 | Chapter 4 — Alignment science |
| 6 | Capstone |

Two things worth knowing about that plan. Weeks 3 and 4 end on a bonus day
rather than 2.5 and 3.5, so **MCTS/AlphaZero and AI Control are optional** in
the standard track. And when ARENA compresses to four weeks it dissolves
Chapter 4 into picks inside the other weeks — which tells you that **4.1–4.5 is
the material ARENA itself treats as droppable first** if you fall behind.

Chapter 1's dependency edges here are deliberately loose: 1.3.x, 1.4.x and
1.5.x all unlock off 1.2, matching ARENA's structure where the middle of week 2
is a choice rather than a march.

## Prerequisites

ARENA expects roughly a year of university applied maths, real coding
experience, and Python fluency. Section 0.0 *is* their published prep — the
einops/einsum/tensor-manipulation Colab they send accepted participants, worth
1–2 days. If you are coming from BASE and want one place to start, start there,
and work the bench prep exercises for 0.0 first.

## Where the gates are thin

Chapters 2 and 4 are largely ungated: the bench has RL and alignment-science
*prep* exercises but not yet cold-checkpoint problems with runnable tests for
most of those sections. Those checkpoints fall back to the understanding check
and are marked as such in the UI. Chapters 0, 1 and 3 are the strongly gated
ones, which is also where a six-week cohort spends its first three weeks.

ARENA © Callum McDougall, MIT-licensed. The bench links to the canonical
material; we do not copy or fork it.
