---
slug: r04-karpathy-training-recipe
kind: reading
title: "A Recipe for Training Neural Networks"
source: "Andrej Karpathy, 2019"
url: "https://karpathy.github.io/2019/04/25/recipe/"
duration_min: 25
axes: [training_mechanics, debugging]
domain_tags: [debugging, gradient, loss, optimizer, training]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

The single most-referenced piece of writing on how to actually run a
training experiment without shooting yourself in the foot. Six years
old and still right.

**Why read.** Most ML coding problems on Li's Bench drill the
*mechanics* of training (loss functions, optimizers, gradient
accumulation). This essay drills the *hygiene* — the meta-process
that separates "I got a model to train" from "I shipped a system
that keeps working." Half of the debugging problems on the bench are
illustrations of failures the recipe explicitly warns you about.

**What to take from it.**

1. **The "neural net training is a leaky abstraction" framing.**
   Most production ML bugs are silent: code runs, loss looks plausible,
   the model just doesn't generalize. Reading the recipe builds the
   instinct to *distrust* loss as a sole signal.
2. **The "become one with the data" rule.** Look at the inputs before
   you train. Half of the JSONL-pipeline-style problems on the bench
   come from people not doing this — see
   [jsonl-pipeline](/problem/jsonl-pipeline).
3. **The "overfit a single batch" sanity check.** A working training
   loop should be able to memorize 2 examples in 5 minutes. If it
   can't, your loss is wrong, your gradients are blocked, or your
   labels are mislabeled. This single check would catch most bugs in
   [debug-causal-mask](/problem/debug-causal-mask),
   [debug-ce-axis](/problem/debug-ce-axis),
   [debug-softmax-before-ce](/problem/debug-softmax-before-ce).
4. **The patience argument.** Most "this model isn't working" reports
   are actually "I didn't wait long enough or sweep enough." The
   recipe is honest about how unglamorous the work is.

**Pair with** the debug section of the bench. The first time you
read it, the advice is abstract; after you've shipped 3-4 debug
problems, the advice has anchors.
