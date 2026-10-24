---
slug: r06-programming-rust-references
kind: reading
title: "Programming Rust 2e — Ch. 5: References"
source: "Blandy, Orendorff, Tindall (O'Reilly, 2021)"
url: ""
book: "Chapter 5: References"
page: 109
duration_min: 45
axes: [rust_fluency]
domain_tags: [borrow, iterator, rust]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

The Rust Book ch.4 introduces references. Programming Rust ch.5 is
where you finish internalizing them. The chapter goes deeper on
lifetime inference, the rules that make `&self` methods chain
naturally, and the precise semantics of `&mut T` that make iterator
adapters work.

**Why read.** Most "fighting the borrow checker" episodes are
because you have the mental model from Rust Book ch.4 but not the
nuance from this chapter. Once you read it, the borrow checker
errors become *informative* — they tell you what the compiler
inferred, and you can fix the structure, not just the syntax.

**What to take from it.**

1. **References as fat pointers vs thin pointers.** `&T` is a thin
   pointer (one word); `&[T]` (a slice) and `&str` are fat pointers
   (two words — pointer + length). Knowing this answers "why does
   `&str` accept both `&String` and string literals?"
2. **Reference lifetimes are inferred from the function signature
   alone.** The compiler doesn't look at the function body — that's
   what makes lifetime inference fast and decidable. The corollary:
   if the compiler can't infer your intent, the signature needs
   annotation.
3. **The reborrow trick.** `&*x` lets you turn a reference into a
   different reference; `&mut *x` re-borrows mutably. Comes up
   constantly in iterator implementations.
4. **Sharing vs mutation, the central trade.** Rust's whole memory
   model is "many shared XOR one mutable." Once you stop fighting it
   and start *designing* around it (using interior mutability with
   `RefCell` only when you really need to), code gets cleaner.

**Pair with** the [ring-buffer-rust](/problem/ring-buffer-rust)
problem — implementing a mutable data structure that hands out both
shared and exclusive references is the exercise this chapter
prepares you for.
