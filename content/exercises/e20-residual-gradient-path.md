---
slug: e20-residual-gradient-path
kind: exercise
title: "Trace the gradient through a residual connection"
source: "prep for ARENA 0.2 CNNs & ResNets"
duration_min: 8
axes: [training_mechanics]
domain_tags: [resnet, residual, vanishing gradient, backprop]
arena_section: "0.2"
pedagogy: trace
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** Two 20-block networks built from the same block `f`. To keep
the arithmetic in your head, treat each block as scalar with local
derivative `f'(x) = 0.1` — a small number, which is what a
well-initialised branch gives you (ResNet-v2 even zero-inits the last
BatchNorm `gamma` so the branch starts at ~0).

```python
# plain
x = f_i(x)              # for i in range(20)

# residual
x = x + f_i(x)          # for i in range(20)
```

**Question.** For each network, what is `d(output)/d(input)`? Give the
expression and the number.

Write both down before opening the reveal.

<details>
<summary>reveal</summary>

**Plain.** Each block contributes a factor of `f'_i`, so the chain rule
gives a pure product:

```
d(out)/d(in) = prod(f'_i) = 0.1 ** 20 = 1e-20
```

The input layer receives essentially nothing. This is vanishing
gradients — not a numerical bug, just twenty multiplications by a
number less than one.

**Residual.** `y = x + f(x)` differentiates to `1 + f'(x)`, so:

```
d(out)/d(in) = prod(1 + f'_i) = 1.1 ** 20 ≈ 6.73
```

Expand that product and you get a sum over **every path** through the
network: one path that skips all 20 branches (coefficient exactly `1`),
20 paths through one branch, and so on. The identity path is what
survives — its contribution can't be scaled away by the branches
because the `+ x` never had a weight on it.

**The correction.** `1 + f'` also means gradients can now *grow*
multiplicatively, which is why ResNets pair residuals with
normalisation — the norm layers hold `f'` small so the product stays
near 1 from both sides.

</details>

**Key insight.** A residual connection turns a *product* of local
derivatives into a *sum over paths* that always includes an
unweighted identity path. Depth stops being something the gradient has
to survive; it becomes something the gradient can route around.
