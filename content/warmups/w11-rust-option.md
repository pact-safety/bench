---
slug: warmup-rust-option
title: Rust — Option methods (unwrap_or, map, and_then)
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: true
structural_tags: [warmup, rust_idiom]
domain_tags: []
competency_tags: [rust, option]
jd_signal_tags: [rust]
rust_crate_dir: warmup_rust_option
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Implement two functions on `Option`:

```
pub fn second_char_or_dash(s: &str) -> char
// Returns the second char of s, or '-' if s has fewer than 2 chars.

pub fn second_to_uppercase(s: &str) -> Option<char>
// Returns the second char uppercased, or None if there isn't one.
```

Use `Option::nth`, `map`, `unwrap_or`. No manual indexing or match
expressions.

## Starter (Rust)

```
pub fn second_char_or_dash(s: &str) -> char {
    todo!()
}

pub fn second_to_uppercase(s: &str) -> Option<char> {
    todo!()
}
```

## Solution (Rust)

```
pub fn second_char_or_dash(s: &str) -> char {
    s.chars().nth(1).unwrap_or('-')
}

pub fn second_to_uppercase(s: &str) -> Option<char> {
    s.chars().nth(1).and_then(|c| c.to_uppercase().next())
}
```

## Tests

```
# Rust tests live in content/rust/warmup_rust_option/tests/integration.rs.
print("OK")
```

## Key insight

`Option::map` transforms inside the Some; `and_then` flattens a
function returning Option (avoids `Option<Option<T>>`). `unwrap_or`
provides a default when None. The four-method combo covers most
Option flows.
