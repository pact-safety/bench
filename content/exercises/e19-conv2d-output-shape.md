---
slug: e19-conv2d-output-shape
kind: exercise
title: "Predict the output shape of a conv stack"
source: "prep for ARENA 0.2 CNNs & ResNets"
duration_min: 8
axes: [algorithmic, debugging]
domain_tags: [conv2d, stride, padding, shape arithmetic]
arena_section: "0.2"
pedagogy: trace
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** A three-layer stem, fed a batch of CIFAR-shaped images.

```python
x: Float[Tensor, "batch=4 channels=3 height=32 width=32"]

conv1 = nn.Conv2d(3, 16, kernel_size=5, stride=2, padding=1)
conv2 = nn.Conv2d(16, 16, kernel_size=3, stride=1, padding=1)
pool  = nn.MaxPool2d(kernel_size=2, stride=2, padding=0)
```

**Question.** Predict the shape after each of `conv1(x)`, `conv2(...)`,
`pool(...)`. The formula for one spatial dimension is

```
out = floor((in + 2*padding - kernel) / stride) + 1
```

Commit to three shapes before opening the reveal.

<details>
<summary>reveal</summary>

1. `conv1(x)` → `(4, 16, 15, 15)`.
   `floor((32 + 2 - 5) / 2) + 1 = floor(29/2) + 1 = 14 + 1 = 15`.
   The channel axis becomes `out_channels=16` — it has nothing to do
   with the input's 3; a conv replaces the channel dim, it doesn't
   transform it elementwise.
2. `conv2(...)` → `(4, 16, 15, 15)`.
   `floor((15 + 2 - 3) / 1) + 1 = 14 + 1 = 15`. This is the
   "same padding" case: `stride=1` with `padding=(kernel-1)/2` for odd
   kernels leaves the spatial dims untouched. That's why `k=3, s=1, p=1`
   is everywhere in ResNets.
3. `pool(...)` → `(4, 16, 7, 7)`.
   `floor((15 + 0 - 2) / 2) + 1 = floor(6.5) + 1 = 6 + 1 = 7`.
   The floor is doing real work here: the last column and row of the
   15×15 map don't fit a full 2×2 window and are silently dropped.

The full-generality formula includes dilation:
`out = floor((in + 2p - d*(k-1) - 1) / s) + 1`, which reduces to the
above at `d=1`. ARENA's exercises use `d=1` throughout, but the
`d*(k-1)+1` term is the "effective kernel size" and is worth carrying
in your head.

</details>

**Key insight.** Stride is the only thing that divides; padding and
kernel only shift the numerator. So read a conv config as "does this
shrink (`s>1`), preserve (`s=1, 2p=k-1`), or trim the edges
(`s=1, p=0`)?" — and when a `RuntimeError: shapes cannot be multiplied`
fires at the first `nn.Linear`, it is almost always a floor you didn't
account for, not a channel count.
