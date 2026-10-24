---
slug: greedy-tokenizer-rust
title: Greedy longest-match tokenizer (Rust write)
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [tokenization, control_flow]
domain_tags: [tokenization]
competency_tags: [rust, tokenization]
jd_signal_tags: [tokenization, rust]
rust_crate_dir: greedy_tokenizer
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
references:
  - title: "The Rust Book — Ch. 4: Understanding Ownership (slices, &str)"
    url: "https://doc.rust-lang.org/book/ch04-00-understanding-ownership.html"
    book: "Klabnik & Nichols"
    why: "Why we take &str + &[&str] rather than owned types"
    phase: explore
  - title: "Programming Rust 2nd Ed — Ch. 3 Fundamental Types, Ch. 5 References"
    book: "Blandy, Orendorff, Tindall (O'Reilly)"
    why: "Byte-sequence iteration, slice indexing, lifetime intuition"
    phase: plan
  - title: "The Rust Book — Ch. 9: Error Handling (Result, ? operator)"
    url: "https://doc.rust-lang.org/book/ch09-00-error-handling.html"
    why: "Returning Err(position) on unmatched input vs panicking"
    phase: implement
  - title: "tokenizers — HuggingFace Rust implementation (reference reading)"
    url: "https://github.com/huggingface/tokenizers"
    why: "Production tokenization uses tries/DAFSA; useful as a horizon"
    phase: verify
---

## Prompt

Implement greedy longest-match tokenization in Rust. Given a vocabulary
(a list of token strings, each non-empty) and an input string, return
the sequence of vocabulary indices that result from repeatedly biting
off the longest vocabulary prefix from the start of the remaining
string. If no vocabulary item matches at some position, return an
`Err(usize)` whose value is that byte offset.

Treat the input and vocabulary as byte sequences (you can use
`&[u8]`). Empty vocabulary entries are not allowed.

```
pub fn tokenize(vocab: &[&str], input: &str) -> Result<Vec<usize>, usize>
```

## Starter (Rust)

```
pub fn tokenize(vocab: &[&str], input: &str) -> Result<Vec<usize>, usize> {
    // TODO
    todo!()
}
```

## Solution (Rust)

```
pub fn tokenize(vocab: &[&str], input: &str) -> Result<Vec<usize>, usize> {
    let bytes = input.as_bytes();
    let mut out: Vec<usize> = Vec::new();
    let mut i = 0usize;
    while i < bytes.len() {
        let remaining = &bytes[i..];
        let mut best: Option<(usize, usize)> = None;
        for (idx, tok) in vocab.iter().enumerate() {
            let tb = tok.as_bytes();
            if tb.is_empty() {
                continue;
            }
            if remaining.starts_with(tb) {
                let l = tb.len();
                if best.map_or(true, |(_, bl)| l > bl) {
                    best = Some((idx, l));
                }
            }
        }
        match best {
            Some((idx, l)) => {
                out.push(idx);
                i += l;
            }
            None => return Err(i),
        }
    }
    Ok(out)
}
```

## Tests

```
# Python-side smoke test only. Rust tests live in the crate at
# content/rust/greedy_tokenizer/tests/integration.rs and run via
# `cargo test` when the user submits in Rust.
print("OK")
```

## Key insight

Greedy longest-match is `O(N * V)` if you scan all vocab every step.
Production tokenizers use a trie or DAFSA for `O(N)`. For an interview
the linear scan is fine; the point is correctness of "longest at each
position" and the error path on unmatched bytes.

## Pitfalls

- Iterating over `&str` byte-by-byte is correct here only because we're
  matching whole-token byte sequences. For Unicode-aware tokenization
  you'd work at the `char` boundary, which is a different problem.
- Returning `Err(i)` instead of `Err(())` keeps the caller's debug story
  alive — they get to know *where* the input went unmatched.
- Empty vocabulary entries cause infinite loops if you accept them. The
  test does not include this case, but a defensive skip is good practice.
