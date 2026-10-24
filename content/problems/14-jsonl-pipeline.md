---
slug: jsonl-pipeline
title: Malformed JSONL → training tuples
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [data_pipeline, control_flow]
domain_tags: [training]
competency_tags: [data_engineering]
jd_signal_tags: [data_pipeline, robustness]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

You're given a JSONL file of conversation pairs from a noisy source.
Each line should be a JSON object with keys `prompt: str` and
`response: str`, but the data is dirty:

- Some lines fail to parse as JSON.
- Some are valid JSON but missing one of the keys.
- Some have the keys with empty-string values.
- Some have leading/trailing whitespace in the strings.
- Duplicate `(prompt, response)` pairs after stripping must be dropped.

Implement:

```
def load_pairs(path: str) -> tuple[list[tuple[str, str]], dict]
```

Return `(pairs, stats)`. `stats` is a dict with:

- `total_lines`: count of non-empty lines read
- `parse_errors`: count of JSON parse failures
- `missing_field`: count of valid JSON missing one of the required keys
- `empty_value`: count of valid JSON with at least one empty string value
- `duplicates`: count of valid pairs that were dropped as duplicates

`pairs` preserves first-occurrence order.

## Starter

```
import json


def load_pairs(path):
    # TODO
    pass
```

## Solution

```
import json


def load_pairs(path):
    stats = {"total_lines": 0, "parse_errors": 0, "missing_field": 0, "empty_value": 0, "duplicates": 0}
    pairs = []
    seen = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            stats["total_lines"] += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                stats["parse_errors"] += 1
                continue
            if not isinstance(obj, dict) or "prompt" not in obj or "response" not in obj:
                stats["missing_field"] += 1
                continue
            p = obj["prompt"].strip() if isinstance(obj["prompt"], str) else ""
            r = obj["response"].strip() if isinstance(obj["response"], str) else ""
            if not p or not r:
                stats["empty_value"] += 1
                continue
            key = (p, r)
            if key in seen:
                stats["duplicates"] += 1
                continue
            seen.add(key)
            pairs.append(key)
    return pairs, stats
```

## Tests

```
import os
import tempfile
import textwrap

raw = textwrap.dedent('''\
    {"prompt": "hi", "response": "hello"}
    {"prompt": "hi", "response": "hello"}
    {"prompt": " what's up ", "response": "all good"}
    not json at all
    {"prompt": "x"}
    {"prompt": "y", "response": ""}
    {"prompt": "z", "response": "z reply"}
    
    {"prompt": "what's up", "response": "all good"}
''')

with tempfile.NamedTemporaryFile("w", delete=False, suffix=".jsonl") as f:
    f.write(raw)
    path = f.name
try:
    pairs, stats = load_pairs(path)
    assert pairs == [("hi", "hello"), ("what's up", "all good"), ("z", "z reply")], pairs
    assert stats["total_lines"] == 8, stats
    assert stats["parse_errors"] == 1, stats
    assert stats["missing_field"] == 1, stats
    assert stats["empty_value"] == 1, stats
    assert stats["duplicates"] == 2, stats  # the exact dup + the post-strip dup
finally:
    os.unlink(path)

print("OK")
```

## Key insight

Order matters: parse → field check → value check → dedupe. A pair that
fails parsing never enters the dedupe set; a pair that survives but is
post-strip equal to an earlier survivor is the second-most-common case.

## Pitfalls

- Iterating over the file with `f.readlines()` reads everything into
  memory. For real-sized JSONL files (millions of lines), iterate the
  file object directly. The test corpus is small either way.
- `json.JSONDecodeError` is the right exception to catch; bare
  `except Exception` swallows real bugs and is the pattern that lets
  unicode errors look like parse errors.
- Don't `assert "prompt" in obj` — that throws AssertionError, which the
  caller might catch generically; explicit branch and stats increment.
