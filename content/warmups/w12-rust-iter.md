---
slug: warmup-rust-iter
title: Rust — Vec iterators (map, filter, collect)
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: true
structural_tags: [warmup, rust_idiom]
domain_tags: []
competency_tags: [rust, iterators]
jd_signal_tags: [rust]
rust_crate_dir: warmup_rust_iter
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Given a slice of `i64`, return a `Vec<i64>` of the squares of the
positive values, in original order.

```
pub fn pos_squares(xs: &[i64]) -> Vec<i64>
```

Use iterator methods (`iter`, `filter`, `map`, `collect`). No
imperative loop.

## Starter (Rust)

```
pub fn pos_squares(xs: &[i64]) -> Vec<i64> {
    todo!()
}
```

## Solution (Rust)

```
pub fn pos_squares(xs: &[i64]) -> Vec<i64> {
    xs.iter().filter(|x| **x > 0).map(|x| x * x).collect()
}
```

## Tests

```
# Rust tests live in content/rust/warmup_rust_iter/tests/integration.rs.
print("OK")
```

## Key insight

Iterator chains in Rust are lazy and zero-cost; the chain doesn't
allocate until `collect`. The double-deref `**x` in the filter closure
is because `iter()` yields `&i64` and the closure parameter `x` is
`&&i64`.
