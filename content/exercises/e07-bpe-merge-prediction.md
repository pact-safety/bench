---
slug: e07-bpe-merge-prediction
kind: exercise
title: "Predict the first two BPE merges"
source: "pairs with Sennrich §3 / Karpathy tokenizer"
duration_min: 8
axes: [tokenization]
domain_tags: [bpe]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

**Setup.** A tiny corpus (pretokenized character-by-character, with
the per-word counts shown):

```
("l", "o", "w")            count: 5
("l", "o", "w", "e", "r")  count: 2
("n", "e", "w", "e", "s", "t")  count: 6
("w", "i", "d", "e", "s", "t")  count: 3
```

The base vocab is the 10 distinct characters. We run BPE training
with the standard merge loop.

**Question.** What are the first **two** merges? Break ties
lexicographically on `(a, b)`.

<details>
<summary>reveal</summary>

**First merge: `(e, s)`.**

Count of every adjacent pair across the corpus, weighted by word count:

| pair | count |
|---|---|
| (l, o) | 5 + 2 = 7 |
| (o, w) | 5 + 2 = 7 |
| (w, e) | 2 + 6 = 8 |
| (e, r) | 2 |
| (n, e) | 6 |
| (e, s) | 6 + 3 = **9** |
| (s, t) | 6 + 3 = **9** |
| (w, i) | 3 |
| (i, d) | 3 |
| (d, e) | 3 |

`(e, s)` and `(s, t)` tie at 9. Lexicographic tiebreak chooses
`(e, s)`. Vocab gains the symbol `es`.

**Second merge: `(es, t)`.**

After merging `es`, the corpus is:

```
("l", "o", "w")               x5
("l", "o", "w", "e", "r")     x2
("n", "e", "w", "es", "t")    x6
("w", "i", "d", "es", "t")    x3
```

Now `(es, t)` appears 6 + 3 = 9 times — the new most frequent pair.
The original `(s, t)` is gone because `s` no longer exists as a
standalone token in any word that contained `es`.

</details>

**Key insight.** The pair frequencies change after every merge — you
can't precompute the schedule. Each merge rewrites adjacencies, so a
fresh count is the only way to be correct. This is why
[bpe-merges](/problem/bpe-merges) recounts the corpus on each
iteration rather than using a precomputed pair table.
