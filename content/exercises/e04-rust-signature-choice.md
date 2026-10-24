---
slug: e04-rust-signature-choice
kind: exercise
title: "Rust — pick the idiomatic signature"
source: "pairs with The Rust Book ch. 4"
duration_min: 8
axes: [rust_fluency]
domain_tags: [ownership, rust]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

**Setup.** You're writing `count_vowels`, a function that reads a
string and returns a count. You want callers to be able to pass
*either* a string literal (`"hello"`) *or* an owned `String`
without cloning.

**Question.** Which signature do you choose?

```rust
// (a)
fn count_vowels(s: String) -> usize

// (b)
fn count_vowels(s: &String) -> usize

// (c)
fn count_vowels(s: &str) -> usize
```

<details>
<summary>reveal</summary>

**(c) is the right choice.** `&str` accepts:
- string literals directly (they're already `&'static str`),
- `&String` (via Rust's deref coercion: `String` derefs to `str`),
- slices of larger strings (`&owned[..5]`).

**(a)** forces the caller to give up ownership — wasteful for a
read-only operation, and string literals can't be passed at all
without a `.to_string()` call.

**(b)** seems reasonable but is strictly less useful than (c):
`&String` accepts only borrowed `String` values, not literals.
The deref coercion goes one way; you'd be voluntarily narrowing
your API.

</details>

**Key insight.** Default to `&str` for read-only string parameters.
Take `String` only when you actually need to take ownership.
