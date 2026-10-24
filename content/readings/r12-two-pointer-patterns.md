---
slug: r12-two-pointer-patterns
kind: reading
title: "Two pointers / sliding window patterns"
source: "Errichto's competitive-programming notes + CP-Algorithms reference"
url: "https://cp-algorithms.com/data_structures/sparse-table.html"
duration_min: 20
axes: [algorithmic]
domain_tags: [algorithm]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

The single most-used algorithmic pattern in research-engineering
phone screens. Two-pointer / sliding window shows up *everywhere* —
batch streaming, eval windowing, log analysis, attention masking
implementations — far more than the textbook problems suggest.

**Why read.** The bench problem
[algo-validation-window](/problem/algo-validation-window) is a
deliberately less-canonical sliding-window problem (two failure
modes — hard and soft). To make that exercise feel mechanical
rather than novel, you want the *base pattern* fully internalized.

**What to take from it.**

1. **The invariant framing.** A sliding window has a property that
   must hold from left to right of the window. The right pointer
   tries to extend; when the invariant breaks, the left pointer
   shrinks. State you track inside the window is the "extra
   bookkeeping."
2. **Variable-size vs fixed-size.** Variable-size: shrink left
   until the invariant holds again. Fixed-size: left moves in
   lockstep with right (single offset). The two flavors collapse
   into nearly the same code; the variable case is the harder
   habit.
3. **Why it beats nested loops.** The two pointers each traverse
   the input once (O(n)), even though they appear to be nested
   inside each other. Amortization argument — left can only move
   forward — is the proof shape interviewers want to hear.

**What to skip.** The "two pointers on sorted array" subpattern
(two-sum-style) is well-trodden; skim it. The harder one is
"sliding window with state" — that's what shows up in
interpretability tooling (sliding context over an activation
sequence) and eval pipelines (rolling window over scores).

**Pair with** the bench's [algo-validation-window](/problem/algo-validation-window)
problem. After reading, the problem should feel like a
straightforward application of the variable-size-with-state
pattern.
