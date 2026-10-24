---
slug: warmup-rust-result
title: Rust — Result, ? operator, map_err
difficulty: easy
time_bucket: 10
problem_type: code_compose
is_warmup: true
structural_tags: [warmup, rust_idiom]
domain_tags: []
competency_tags: [rust, result]
jd_signal_tags: [rust]
rust_crate_dir: warmup_rust_result
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Parse two integers from a `&str` separated by a comma and return their
sum. On any parse failure, return `Err(String)` describing which side
failed.

```
pub fn parse_and_sum(s: &str) -> Result<i64, String>
```

For input `"3,4"` return `Ok(7)`. For `"x,4"` return `Err` containing
the substring `"left:"`. For `"3,y"` return `Err` containing `"right:"`.
For input with the wrong number of comma-separated parts, return
`Err("expected exactly one comma".to_string())`.

## Starter (Rust)

```
pub fn parse_and_sum(s: &str) -> Result<i64, String> {
    todo!()
}
```

## Solution (Rust)

```
pub fn parse_and_sum(s: &str) -> Result<i64, String> {
    let parts: Vec<&str> = s.split(',').collect();
    if parts.len() != 2 {
        return Err("expected exactly one comma".to_string());
    }
    let a: i64 = parts[0].trim().parse().map_err(|e| format!("left: {}", e))?;
    let b: i64 = parts[1].trim().parse().map_err(|e| format!("right: {}", e))?;
    Ok(a + b)
}
```

## Tests

```
# Rust tests live in content/rust/warmup_rust_result/tests/integration.rs.
print("OK")
```

## Key insight

`?` early-returns on `Err`. `map_err` is how you transform one error
type into another before the `?` propagates it — here, from
`ParseIntError` into a `String` with context.
