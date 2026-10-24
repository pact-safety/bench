---
slug: r02-rust-book-ch4-ownership
kind: reading
title: "The Rust Book — Ch. 4: Understanding Ownership"
source: "Klabnik & Nichols"
url: "https://doc.rust-lang.org/book/ch04-00-understanding-ownership.html"
duration_min: 35
axes: [rust_fluency]
domain_tags: [borrow, ownership, rust]
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

The foundational chapter of Rust. If the borrow checker is making
half-sense to you, this is the chapter that turns it into common
sense.

**Why read it.** The two Rust-write problems on Li's Bench (the greedy
tokenizer and the ring buffer) both lean on the &str-vs-String,
borrow, and lifetime intuitions taught here. The Rust warmups
exercise the same muscles in 5-10 minute slices.

**What to take from it.**

1. **§4.1 What is Ownership?** — the three rules: each value has one
   owner, only one owner at a time, the value is dropped when the
   owner goes out of scope.
2. **§4.2 References and Borrowing** — `&T` is shared and read-only;
   `&mut T` is exclusive. The compiler enforces "one mutable XOR many
   immutable" at any given time. This is the rule the
   [warmup-rust-borrow](/problem/warmup-rust-borrow) exercises.
3. **§4.3 The Slice Type** — `&str` as a view into someone else's
   `String`. The reason production Rust code takes `&str` rather than
   `String` in function signatures: callers don't have to give up
   ownership, and string literals are accepted for free.

**After you read it,** the four Rust warmups should feel mechanical;
the ring-buffer problem becomes "how do I structure ownership over a
Vec" rather than "how does Rust work?"
