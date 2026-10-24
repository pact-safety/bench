---
slug: r05-rust-book-ch10-generics
kind: reading
title: "The Rust Book — Ch. 10: Generic Types, Traits, and Lifetimes"
source: "Klabnik & Nichols"
url: "https://doc.rust-lang.org/book/ch10-00-generics.html"
duration_min: 50
axes: [rust_fluency]
domain_tags: [borrow, generics, iterator, lifetimes, rust, trait]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

If chapter 4 was the foundation of Rust, chapter 10 is where the
language gets *productive*. Traits are how Rust does polymorphism
without a runtime overhead; generic functions are how you write APIs
that don't lock callers into one concrete type. Lifetimes are the
last big borrow-checker concept to internalize.

**Why read.** The Rust-write problems on Li's Bench (greedy
tokenizer, ring buffer) can be done with concrete types throughout —
but reading idiomatic Rust requires fluency with `impl Trait`,
`where T: Iterator<Item = i64>`, and explicit lifetime annotations.
The candle / tokenizers / vLLM-Rust codebases you'd touch in a
research-engineering role are heavily generic.

**What to take from it.**

1. **§10.1 Generic Data Types** — the cost model. Generics in Rust
   are monomorphized at compile time, not boxed at runtime. Every
   type instantiation produces a new compiled implementation. Trade:
   binary size grows; runtime stays fast.
2. **§10.2 Traits** — the most-skipped concept by Python programmers
   learning Rust. A trait is *not* an interface in the Java sense —
   you implement traits *for* types you don't own (orphan rule
   notwithstanding). The "default methods on a trait" pattern is
   what makes `Iterator` and `Result` ergonomic.
3. **§10.3 Lifetimes** — by the end of the chapter, the rule "a
   reference cannot outlive what it points to" should feel concrete
   rather than mysterious. The `'static` lifetime is the special
   case where the reference points to compile-time data.

**Pair with** the [warmup-rust-iter](/problem/warmup-rust-iter)
warmup — once you grok `Iterator` as a trait with default methods,
the chain of `.filter().map().collect()` becomes "you're composing
three trait calls on three different types."
