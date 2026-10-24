---
slug: warmup-rust-borrow
title: Rust — &str vs String in a function signature
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: true
structural_tags: [warmup, rust_idiom]
domain_tags: []
competency_tags: [rust, ownership]
jd_signal_tags: [rust]
rust_crate_dir: warmup_rust_borrow
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Write a function `vowel_count` that counts the ASCII vowels in a
string, taking it as `&str` (not `String`). Vowels: `a e i o u`,
case-insensitive.

```
pub fn vowel_count(s: &str) -> usize
```

The integration test in the crate calls it with both a `String` and a
string literal — your `&str` signature must accept both.

## Starter (Rust)

```
pub fn vowel_count(s: &str) -> usize {
    todo!()
}
```

## Solution (Rust)

```
pub fn vowel_count(s: &str) -> usize {
    s.chars()
        .filter(|c| matches!(c.to_ascii_lowercase(), 'a' | 'e' | 'i' | 'o' | 'u'))
        .count()
}
```

## Tests

```
# Rust tests live in content/rust/warmup_rust_borrow/tests/integration.rs.
print("OK")
```

## Key insight

Taking `&str` lets callers pass both string literals (`&'static str`)
and owned `String` (which auto-derefs to `&str`). Taking `String`
forces the caller to give up ownership.
