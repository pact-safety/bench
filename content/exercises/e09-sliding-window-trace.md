---
slug: e09-sliding-window-trace
kind: exercise
title: "Predict the sliding window output"
source: "pairs with the two-pointer reading"
duration_min: 7
axes: [algorithmic]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

**Setup.** A variable-size sliding window that maintains the invariant
"at most 2 distinct characters." For each step, when the right pointer
extends and the invariant breaks, the left pointer shrinks until the
invariant holds again. Track the maximum window length seen.

Input: `"abcabbcbb"`

**Question.** What's the max length, and what's the final (left, right)
pointer pair when the maximum is reached?

<details>
<summary>reveal</summary>

| step | right | char | window | distinct | left | action |
|---:|---:|:--|:--|---:|---:|:--|
| 1 | 0 | a | "a" | 1 | 0 | extend |
| 2 | 1 | b | "ab" | 2 | 0 | extend |
| 3 | 2 | c | "abc" | 3 | — | breaks (3 distinct); shrink left |
| | | | "bc" | 2 | 1 | invariant holds at left=1 |
| 4 | 3 | a | "bca" | 3 | — | breaks; shrink |
| | | | "ca" | 2 | 2 | holds |
| 5 | 4 | b | "cab" | 3 | — | breaks; shrink |
| | | | "ab" | 2 | 3 | holds |
| 6 | 5 | b | "abb" | 2 | 3 | extend |
| 7 | 6 | c | "abbc" | 3 | — | breaks; shrink |
| | | | "bbc" | 2 | 4 | holds |
| 8 | 7 | b | "bbcb" | 2 | 4 | extend |
| 9 | 8 | b | "bbcbb" | 2 | 4 | extend |

**Max length: 5**, at `left=4, right=8`. The substring is `"bbcbb"`.

</details>

**Key insight.** Each pointer only moves forward, so even though the
loop looks doubly nested, the total work is O(n). The "shrink left
until invariant holds" inner loop is what makes the amortized
analysis work — every leftward step is balanced by an earlier
rightward step.
