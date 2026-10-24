---
slug: e22-sgd-momentum-ordering
kind: exercise
title: "Order the steps of SGD with momentum"
source: "prep for ARENA 0.3 Optimization"
duration_min: 10
axes: [training_mechanics]
domain_tags: [sgd, momentum, weight decay, optimizer]
arena_section: "0.3"
pedagogy: parsons
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** You are writing `SGD.step()` to match `torch.optim.SGD` with
`momentum=mu` and `weight_decay=wd`. State already exists:
`self.params` (a list), `self.bs` (one zero-filled buffer per param),
plus `self.lr`, `self.mu`, `self.wd`. The whole body runs under
`@t.inference_mode()`.

The six lines below are scrambled. One of the seven is a **distractor**
that must not appear at all.

```
A.  p -= self.lr * g
B.  g = p.grad
C.  g = g + self.wd * p
D.  self.bs[i] = self.mu * self.bs[i] + g
E.  g = self.bs[i]
F.  for i, p in enumerate(self.params):
G.  p = p - self.lr * g
```

**Question.** Give the order, and say which constraint forces each
adjacency. Name the distractor and why it fails.

Commit to a sequence before opening the reveal.

<details>
<summary>reveal</summary>

**Order: F → B → C → D → E → A.** `G` is the distractor.

The constraints, in the order they bind:

- **B before C.** You need a gradient before you can decay it.
- **C before D.** PyTorch applies weight decay to the *gradient*, then
  lets momentum accumulate the already-decayed gradient. Swap them and
  the decay term never enters the buffer — you get plain SGD with an
  L2 penalty applied once per step instead of a decay that compounds
  through the momentum trajectory. (Decoupling those two is exactly
  what AdamW is.)
- **D before E before A.** The buffer must be updated before you read
  the step out of it, and read before you apply it.

**Why the buffer holds gradients, not updates.** PyTorch's convention is
`b ← mu*b + g`, then `p ← p - lr*b` — `lr` stays *outside* the buffer.
So `self.bs[i]` is an exponentially-weighted running sum of recent
gradients, and changing `lr` mid-training rescales the next step
without rewriting history. The textbook Sutskever form
(`v ← mu*v - lr*g`, `p ← p + v`) bakes `lr` into the buffer and behaves
differently under a schedule. ARENA's tests check against PyTorch.

Zero-initialising `self.bs` is correct: on step 1, `mu*0 + g = g`,
which is what PyTorch does when it seeds `b_0 = g_0`.

**Distractor `G`.** `p = p - self.lr * g` rebinds the local name `p` to
a fresh tensor and leaves the actual parameter untouched. The loop runs
clean, the loss never moves. Optimiser writes must be in-place — `p -=`,
`p.add_(...)`, `p.copy_(...)` — which is also why the body needs
`inference_mode` to mutate leaf tensors at all.

</details>

**Key insight.** Every optimiser step is the same four beats: read the
gradient, transform the gradient (decay), fold it into state (momentum),
write the parameter in place. Ordering bugs live at the seam between
"transform" and "fold" — and the write is always in-place.
