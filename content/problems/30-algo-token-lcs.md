---
slug: algo-token-lcs
title: Longest common subsequence of token IDs (alignment scoring)
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [algo, dp]
domain_tags: [eval]
competency_tags: [dp]
jd_signal_tags: [eval, alignment]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

To score a model's output against a reference, you want the longest
common subsequence (LCS) of the two token-ID sequences and the
"alignment indices" — for each token in the LCS, the position in `a`
and the position in `b` where it was matched.

```
def token_lcs(a: list[int], b: list[int]) -> tuple[list[int], list[tuple[int, int]]]
```

Return `(lcs_tokens, alignment)`. `alignment[i]` is `(idx_in_a,
idx_in_b)` of the i-th LCS token. Order: increasing in both indices,
which is what "subsequence" means. Both lists are the same length. For
the tie-break across multiple equal-length LCSes, prefer the one whose
*last match in `a`* is earliest.

## Starter

```
def token_lcs(a, b):
    pass
```

## Solution

```
def token_lcs(a, b):
    n, m = len(a), len(b)
    # dp[i][j] = LCS length of a[:i] and b[:j].
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(m):
            if a[i] == b[j]:
                dp[i + 1][j + 1] = dp[i][j] + 1
            else:
                # Tie-break: prefer the path that *doesn't* advance in a.
                # When we backtrack, this makes "last match in a" earlier.
                dp[i + 1][j + 1] = max(dp[i][j + 1], dp[i + 1][j])

    tokens = []
    align = []
    i, j = n, m
    while i > 0 and j > 0:
        if a[i - 1] == b[j - 1]:
            tokens.append(a[i - 1])
            align.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif dp[i][j - 1] >= dp[i - 1][j]:
            j -= 1
        else:
            i -= 1
    tokens.reverse()
    align.reverse()
    return tokens, align
```

## Tests

```
# Simple case
toks, al = token_lcs([1, 2, 3, 4], [2, 3, 5, 4])
assert toks == [2, 3, 4], toks
assert al == [(1, 0), (2, 1), (3, 3)], al

# All-equal
toks, al = token_lcs([7, 7, 7], [7, 7, 7])
assert toks == [7, 7, 7]
assert al == [(0, 0), (1, 1), (2, 2)]

# Disjoint
assert token_lcs([1, 2, 3], [4, 5, 6]) == ([], [])

# Empty
assert token_lcs([], [1, 2]) == ([], [])

# Subsequence property on a randomized case
import random
random.seed(0)
a = [random.randint(0, 4) for _ in range(20)]
b = [random.randint(0, 4) for _ in range(20)]
toks, al = token_lcs(a, b)
# Indices strictly increasing in both axes
for i in range(1, len(al)):
    assert al[i][0] > al[i - 1][0]
    assert al[i][1] > al[i - 1][1]
# Tokens match
for tok, (i, j) in zip(toks, al):
    assert a[i] == tok and b[j] == tok

print("OK")
```

## Key insight

Standard `O(nm)` LCS DP. The backtrack is where the "alignment indices"
fall out — you reverse the path you took when matching. Tie-break
choice during backtrack (`>=` vs `>`) controls which equal-length LCS
you return; the test pins down one consistent choice.

## Pitfalls

- DP table is `(n+1) x (m+1)` so the base row/column of zeros is free.
  Off-by-one on the indexing is the classic mistake.
- The alignment tuples are `(idx_in_a, idx_in_b)`, both 0-indexed,
  matching the position in the *original* lists, not the DP table.
- `O(nm)` memory is fine for token sequences in the low thousands. For
  longer comparisons, switch to a streaming algorithm (e.g., Hirschberg
  for `O(min(n, m))` memory).
