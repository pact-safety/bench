---
slug: judge-agreement-kappa
title: Chance-corrected agreement between two eval judges
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [eval, eval_design]
domain_tags: [eval, safety]
competency_tags: [inter_rater_reliability, cohens_kappa, eval_validity]
jd_signal_tags: [eval_design, safety]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-07-19
version: 1
---

## Prompt

Two judges (say, two LLM graders, or a model and a human) each label the
same `N` eval transcripts as pass (`1`) or fail (`0`). Raw agreement — the
fraction of labels they share — *overstates* reliability, because two
judges who both pass 95% of everything will agree ~90% of the time by
chance alone. Compute **Cohen's kappa**, which corrects for that chance
agreement.

```
def cohens_kappa(judge_a: list[int], judge_b: list[int]) -> float
```

`kappa = (p_o - p_e) / (1 - p_e)`, where `p_o` is the observed agreement
and `p_e` is the agreement expected if each judge labeled independently at
their own base rates. Assume the two lists are the same non-zero length.
If `p_e == 1` (a judge used only one label and both agree everywhere),
return `1.0`.

## Starter

```
def cohens_kappa(judge_a, judge_b):
    # TODO
    pass
```

## Solution

```
def cohens_kappa(judge_a, judge_b):
    n = len(judge_a)
    # Observed agreement.
    agree = sum(1 for a, b in zip(judge_a, judge_b) if a == b)
    p_o = agree / n
    # Expected agreement from each judge's marginal base rates.
    a1 = sum(judge_a) / n          # P(judge A says 1)
    b1 = sum(judge_b) / n          # P(judge B says 1)
    p_e = a1 * b1 + (1 - a1) * (1 - b1)
    if p_e == 1.0:
        # Degenerate: both judges used a single label. They agree
        # perfectly, so kappa is 1.0 (avoid 0/0).
        return 1.0
    return (p_o - p_e) / (1 - p_e)
```

## Tests

```
# Perfect agreement on a balanced split → kappa 1.0.
assert cohens_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0

# Total disagreement, balanced marginals: p_o=0, p_e=0.5 → kappa = -1.0.
assert cohens_kappa([1, 1, 0, 0], [0, 0, 1, 1]) == -1.0

# Chance-level agreement scores ~0 even though raw agreement is 50%.
# A=[1,1,0,0] (base rate .5), B=[1,0,1,0] (base rate .5): agree on
# positions 0 and 3 → p_o=0.5, p_e=0.5 → kappa 0.0.
assert cohens_kappa([1, 1, 0, 0], [1, 0, 1, 0]) == 0.0

# High base rate inflates raw agreement; kappa stays honest.
a = [1] * 9 + [0]
b = [1] * 8 + [0, 1]   # raw agreement 8/10 = 0.8...
k = cohens_kappa(a, b)
assert -1.0 <= k <= 1.0
assert k < 0.8   # ...but chance-corrected agreement is much lower

# Degenerate single-label judges.
assert cohens_kappa([1, 1, 1], [1, 1, 1]) == 1.0

print("OK")
```

## Key insight

Raw agreement answers "how often do they match?"; kappa answers "how much
do they match *beyond chance*?" When a benchmark's labels are skewed
(most items pass), the second question is the only honest one — a judge
you're validating can look 90% reliable and have near-zero real
agreement. The `1 - p_e` denominator rescales the leftover, above-chance
agreement onto a 0–1 (with negatives possible) scale.

## Pitfalls

- Reporting raw agreement (`p_o`) as "reliability." On skewed label
  distributions it is almost meaningless — that's the whole reason kappa
  exists.
- The `p_e == 1` degenerate case (a judge that always says pass) →
  division by zero. Guard it.
- Expecting kappa to be non-negative: below-chance agreement is real and
  yields negative kappa; don't clamp it to 0.
