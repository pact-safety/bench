---
slug: bpe-merges
title: BPE merge loop
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [tokenization, data_pipeline]
domain_tags: [tokenization]
competency_tags: [tokenization]
jd_signal_tags: [tokenization, data_pipeline]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Given a pretokenized corpus — a list of `(word, count)` pairs where each
word is a tuple of single-character symbols — run byte-pair encoding
until the vocabulary reaches a target size or no more merges are
possible. Return the ordered list of merge rules.

```
def bpe_merges(corpus: list[tuple[tuple[str, ...], int]], target_vocab_size: int) -> list[tuple[str, str]]
```

- The base vocabulary is the set of distinct symbols already present in
  the corpus.
- One merge step: find the most frequent adjacent symbol pair across the
  corpus (weighted by word count), record it as a merge rule, and
  rewrite every word to use the merged symbol.
- Stop when `len(vocab) == target_vocab_size` or no pair appears more
  than once.
- Ties broken by lexicographic order of `(a, b)`.

## Starter

```
from collections import defaultdict


def bpe_merges(corpus, target_vocab_size):
    # TODO
    pass
```

## Solution

```
from collections import defaultdict


def bpe_merges(corpus, target_vocab_size):
    words = [(list(w), c) for w, c in corpus]
    vocab = set()
    for w, _ in words:
        vocab.update(w)
    merges = []

    while len(vocab) < target_vocab_size:
        pair_counts = defaultdict(int)
        for syms, c in words:
            for i in range(len(syms) - 1):
                pair_counts[(syms[i], syms[i + 1])] += c
        if not pair_counts:
            break
        best_count = max(pair_counts.values())
        if best_count < 2:
            break
        best = min((p for p, c in pair_counts.items() if c == best_count))
        merges.append(best)
        merged = best[0] + best[1]
        vocab.add(merged)

        new_words = []
        for syms, c in words:
            i = 0
            out = []
            while i < len(syms):
                if i + 1 < len(syms) and (syms[i], syms[i + 1]) == best:
                    out.append(merged)
                    i += 2
                else:
                    out.append(syms[i])
                    i += 1
            new_words.append((out, c))
        words = new_words

    return merges
```

## Tests

```
corpus = [
    (("l", "o", "w"), 5),
    (("l", "o", "w", "e", "r"), 2),
    (("n", "e", "w", "e", "s", "t"), 6),
    (("w", "i", "d", "e", "s", "t"), 3),
]

# Base vocab size = 10. Target 12 means two merges.
out = bpe_merges(corpus, target_vocab_size=12)
assert len(out) == 2, out
# Most frequent pair on first pass: (e, s) appears 6 + 3 = 9; (s, t) also
# 6 + 3 = 9; tie broken lexicographically -> (e, s).
assert out[0] == ("e", "s"), out[0]
# After merging "es", the most frequent pair is (es, t) at 9.
assert out[1] == ("es", "t"), out[1]

# Target 100 stops naturally when no pair appears >= 2 times.
out_big = bpe_merges(corpus, target_vocab_size=100)
assert len(out_big) >= 2

print("OK")
```

## Key insight

A merge rewrites the corpus, which changes the next round's pair counts.
You can't precompute a static priority queue and call it done.
Production BPE uses an incremental data structure that only updates
counts near the merged positions; for an interview implementation, the
recount-every-pass version is correct and obviously so.

## Pitfalls

- Iterating with indices and modifying `syms` in place during the rewrite
  is error-prone. Build a fresh `out` list.
- Tie-breaking must be deterministic. `max(pair_counts, key=...)` picks
  some arbitrary winner among ties; the test relies on lexicographic.
- `defaultdict(int)` is the natural choice. A plain `dict.get(p, 0) + 1`
  is fine; using `Counter` works too. Don't reach for one of the more
  exotic stdlib structures unless you're benchmarking.
