---
slug: e03-rust-move-semantics
kind: exercise
title: "Rust move semantics — will it compile?"
source: "pairs with The Rust Book ch. 4"
duration_min: 10
axes: [rust_fluency]
domain_tags: [borrow, ownership, rust]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

**Setup.** Two short Rust snippets.

```rust
// (A)
fn main() {
    let s1 = String::from("hello");
    let s2 = s1;
    println!("{}", s1);
}
```

```rust
// (B)
fn main() {
    let x = 5;
    let y = x;
    println!("{} {}", x, y);
}
```

**Question.** Which compiles? For the one that doesn't, what's the
compiler's error?

<details>
<summary>reveal</summary>

**(A) does NOT compile.** `String` is heap-allocated; `let s2 = s1;`
*moves* ownership to `s2`, leaving `s1` invalid. The `println!`
fails with:

```
error[E0382]: borrow of moved value: `s1`
```

**(B) compiles.** `i32` implements `Copy` (it's stack-allocated and
trivially copyable), so `let y = x;` duplicates the value rather
than moving it. Both `x` and `y` remain valid.

</details>

**Key insight.** Heap-owning types (`String`, `Vec`, `Box`) *move*
on assignment. Trivially-copyable stack types (`i32`, `f64`, `bool`,
`char`, fixed-size arrays of `Copy` types) *copy* — same syntax,
different semantics. When in doubt, check whether the type
implements `Copy`.
