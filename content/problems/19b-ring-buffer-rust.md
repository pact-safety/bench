---
slug: ring-buffer-rust
title: Fixed-capacity ring buffer for KV cache indexing (Rust write)
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [data_structures, control_flow]
domain_tags: [attention]
competency_tags: [rust, data_structures]
jd_signal_tags: [rust, inference, kv_cache]
rust_crate_dir: ring_buffer
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
references:
  - title: "Programming Rust 2nd Ed — Ch. 16: Collections (VecDeque)"
    book: "Blandy, Orendorff, Tindall (O'Reilly)"
    why: "Production answer is VecDeque; this exercise reinvents it for the indexing intuition"
    phase: explore
  - title: "The Rust Book — Ch. 19: Advanced Features (manual modular arithmetic, generics)"
    url: "https://doc.rust-lang.org/book/ch19-00-advanced-features.html"
    why: "Generics over Clone; manual index management"
    phase: plan
  - title: "vLLM PagedAttention — KV cache as memory pages"
    url: "https://arxiv.org/abs/2309.06180"
    why: "Production KV cache is paged, not a single ring — useful as a horizon for what real inference systems do"
    phase: verify
---

## Prompt

Implement a fixed-capacity ring buffer in Rust for sliding-window KV
cache indexing. When capacity is reached, pushing a new element
overwrites the oldest. Items remain ordered oldest → newest.

```
pub struct RingBuffer<T> { /* ... */ }
impl<T: Clone> RingBuffer<T> {
    pub fn with_capacity(cap: usize) -> Self;
    pub fn push(&mut self, item: T);
    pub fn len(&self) -> usize;
    pub fn capacity(&self) -> usize;
    pub fn to_vec(&self) -> Vec<T>;
}
```

`to_vec()` returns items in oldest-first order. `len()` is at most
`capacity()`. Capacity 0 is allowed and accepts no pushes (length stays 0).

## Starter (Rust)

```
pub struct RingBuffer<T> {
    buf: Vec<Option<T>>,
    head: usize,
    len: usize,
}

impl<T: Clone> RingBuffer<T> {
    pub fn with_capacity(cap: usize) -> Self {
        todo!()
    }
    pub fn push(&mut self, item: T) {
        todo!()
    }
    pub fn len(&self) -> usize {
        todo!()
    }
    pub fn capacity(&self) -> usize {
        todo!()
    }
    pub fn to_vec(&self) -> Vec<T> {
        todo!()
    }
}
```

## Solution (Rust)

```
pub struct RingBuffer<T> {
    buf: Vec<Option<T>>,
    head: usize,
    len: usize,
}

impl<T: Clone> RingBuffer<T> {
    pub fn with_capacity(cap: usize) -> Self {
        let mut buf = Vec::with_capacity(cap);
        for _ in 0..cap {
            buf.push(None);
        }
        Self { buf, head: 0, len: 0 }
    }

    pub fn push(&mut self, item: T) {
        let cap = self.buf.len();
        if cap == 0 {
            return;
        }
        if self.len < cap {
            let i = (self.head + self.len) % cap;
            self.buf[i] = Some(item);
            self.len += 1;
        } else {
            self.buf[self.head] = Some(item);
            self.head = (self.head + 1) % cap;
        }
    }

    pub fn len(&self) -> usize {
        self.len
    }

    pub fn capacity(&self) -> usize {
        self.buf.len()
    }

    pub fn to_vec(&self) -> Vec<T> {
        let cap = self.buf.len();
        let mut out = Vec::with_capacity(self.len);
        for i in 0..self.len {
            let idx = (self.head + i) % cap;
            if let Some(v) = &self.buf[idx] {
                out.push(v.clone());
            }
        }
        out
    }
}
```

## Tests

```
# Rust tests live in content/rust/ring_buffer/tests/integration.rs.
print("OK")
```

## Key insight

Wrap-around uses modular arithmetic on `head` and `(head + len) % cap`.
The buffer is full when `len == cap`; from that point on, each push
overwrites at `head` and advances `head`. Length never exceeds capacity.

## Pitfalls

- Capacity-0 has to be handled explicitly or `% 0` panics on first push.
- `len` and `head` are independent: `len` saturates at `cap`, `head` is
  always in `[0, cap)`. Confusing the two is the classic ring-buffer
  bug.
- Using `VecDeque` is the production answer; here the exercise is the
  manual indexing.
