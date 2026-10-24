---
slug: paired-eval-position-debias
title: Debiasing a paired-comparison eval for position bias
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [eval, eval_design]
domain_tags: [eval, safety]
competency_tags: [paired_comparison, position_bias, eval_validity]
jd_signal_tags: [eval_design, safety]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-07-19
version: 1
---

## Prompt

You're running a preference eval: a judge model is shown two responses,
A and B, and picks the better one. Judges have a **position bias** — they
favor whichever response is shown *first*, independent of quality. To
control for it, every item was run **twice**: once with A shown first,
once with the order swapped.

Each item gives you the judge's pick in both orderings. Count a response
as the winner only when the judge prefers it **consistently in both
orderings**; if the two orderings disagree, the item is a *tie* (the
preference was position-driven, not quality-driven).

```
def debiased_winrate(items: list[tuple[str, str]]) -> dict
```

Each item is `(pick_when_A_first, pick_when_B_first)`, where each element
is `"A"` or `"B"`. Return
`{"a_wins": int, "b_wins": int, "ties": int, "a_winrate": float}`, where
`a_winrate` counts only decisive (non-tie) items: `a_wins / (a_wins +
b_wins)`, or `0.0` when there are no decisive items.

## Starter

```
def debiased_winrate(items):
    # TODO
    pass
```

## Solution

```
def debiased_winrate(items):
    a_wins = b_wins = ties = 0
    for first_order, second_order in items:
        if first_order == "A" and second_order == "A":
            a_wins += 1
        elif first_order == "B" and second_order == "B":
            b_wins += 1
        else:
            # Orderings disagree → the pick tracked position, not quality.
            ties += 1
    decisive = a_wins + b_wins
    a_winrate = a_wins / decisive if decisive else 0.0
    return {"a_wins": a_wins, "b_wins": b_wins, "ties": ties, "a_winrate": a_winrate}
```

## Tests

```
# Consistent preferences survive; the flipped item becomes a tie.
items = [("A", "A"), ("A", "A"), ("B", "B"), ("A", "B")]
out = debiased_winrate(items)
assert out == {"a_wins": 2, "b_wins": 1, "ties": 1, "a_winrate": 2/3}, out

# Pure position bias: the judge always picks whoever is first, so every
# item flips → all ties, and the naive "A won 100%" signal vanishes.
items = [("A", "B")] * 5
out = debiased_winrate(items)
assert out == {"a_wins": 0, "b_wins": 0, "ties": 5, "a_winrate": 0.0}, out

# No items.
assert debiased_winrate([]) == {"a_wins": 0, "b_wins": 0, "ties": 0, "a_winrate": 0.0}

print("OK")
```

## Key insight

The swap-and-require-consistency trick turns a position-confounded signal
into a quality signal. A single-order eval that reports "A wins 100%" can
be *entirely* position bias — running both orders and demanding agreement
is what separates "A is better" from "A was on top." The tie bucket is not
noise to discard; its size is a direct read on how position-driven the
judge is.

## Pitfalls

- Computing `a_winrate` over *all* items instead of decisive ones dilutes
  the rate with ties and understates a real preference. Divide by
  `a_wins + b_wins`.
- Treating a disagreeing item as a half-win for each side: that
  relaunders position bias back into the score. A disagreement carries no
  quality signal — it's a tie.
- Forgetting the empty / all-tie guard → `ZeroDivisionError`.
