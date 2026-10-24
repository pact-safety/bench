---
slug: 35-eval-item-discrimination
title: Flag non-discriminative eval items against a weak baseline
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [aggregation, edge_cases, numpy_only]
domain_tags: [evaluation, benchmarks]
competency_tags: [eval_design, ai_safety_fundamentals]
jd_signal_tags: [eval_design, evals, ai_safety]
original: true
authored_by: claude_code_arena_prep
authored_date: 2026-08-19
version: 1
---

## Prompt

An eval is only measuring capability on the items where a capable model
and a deliberately weak baseline actually *differ*. Items both pass are
measuring nothing — they inflate the headline number and dilute every
comparison you make with it. Items both fail are measuring nothing
either. And an item the weak baseline passes but the capable model fails
is worse than useless: it is evidence your scorer is broken, or that the
item rewards a shortcut.

Implement the per-item screen:

```python
def item_discrimination(capable_scores, baseline_scores, min_gap=0.5):
    # capable_scores:  (n_items,) per-item score for the model under test
    # baseline_scores: (n_items,) per-item score for a weak/cheap policy
    #                  (constant answer, first-choice, retrieval-free, ...)
    # returns a dict, see below
```

The discrimination index for an item is `capable - baseline`. Flag an
item as non-discriminative when that index falls **below** `min_gap`.
With binary 0/1 scores and the default `min_gap=0.5`, that single rule
catches all three failure modes: both pass (index 0), both fail
(index 0), and baseline-beats-capable (index -1).

Return a dict with:

- `'discrimination'` — `(n_items,)` float array of per-item indices
- `'flagged'` — `(n_items,)` bool array, `True` for non-discriminative
- `'n_flagged'` — Python `int`
- `'flagged_fraction'` — Python `float`

Raise `ValueError` if the two score vectors have different lengths.
Handle the empty item set without dividing by zero — return empty arrays
of the right dtype and a `flagged_fraction` of `0.0`.

numpy only — no torch.

## Starter

```python
import numpy as np


def item_discrimination(capable_scores, baseline_scores, min_gap=0.5):
    """Screen eval items for discriminative power against a weak baseline.

    Args:
        capable_scores:  (n_items,) per-item scores for the model under
                         test, typically 0/1 but any real score works.
        baseline_scores: (n_items,) per-item scores for a deliberately
                         weak or cheap baseline policy.
        min_gap:         minimum capable-minus-baseline gap for an item to
                         count as discriminative.

    Returns:
        dict with keys:
          'discrimination'   (n_items,) float array of capable - baseline
          'flagged'          (n_items,) bool array, True = non-discriminative
          'n_flagged'        int
          'flagged_fraction' float, 0.0 for an empty item set

    Raises:
        ValueError: if the two score vectors have different lengths.
    """
    # 1. Coerce the inputs to arrays and check they line up.
    ...
    # 2. Handle the empty item set before anything divides by the count.
    ...
    # 3. Compute the per-item discrimination index.
    ...
    # 4. Flag the items that fall below the minimum useful gap.
    ...
    # 5. Summarize the flagged set and return the documented dict.
    raise NotImplementedError()
```

## Solution

```python
import numpy as np


def item_discrimination(capable_scores, baseline_scores, min_gap=0.5):
    capable = np.asarray(capable_scores, dtype=float).reshape(-1)
    baseline = np.asarray(baseline_scores, dtype=float).reshape(-1)
    if capable.shape != baseline.shape:
        raise ValueError("score vectors must have the same length")

    # Guard the empty set explicitly: flagged.mean() on a size-0 array is a
    # nan plus a RuntimeWarning, which would silently poison a report.
    if capable.size == 0:
        return {
            "discrimination": np.zeros(0, dtype=float),
            "flagged": np.zeros(0, dtype=bool),
            "n_flagged": 0,
            "flagged_fraction": 0.0,
        }

    discrimination = capable - baseline

    # One threshold covers all three failure modes because they all produce
    # a small or negative index: both-pass and both-fail sit at 0, and
    # baseline-beats-capable goes negative.
    flagged = discrimination < min_gap

    return {
        "discrimination": discrimination,
        "flagged": flagged,
        "n_flagged": int(flagged.sum()),
        "flagged_fraction": float(flagged.mean()),
    }
```

## Tests

```python
import numpy as np


def test_item_both_models_pass_is_flagged():
    out = item_discrimination([1.0, 1.0], [1.0, 0.0])
    assert bool(out["flagged"][0]) is True
    assert np.allclose(out["discrimination"][0], 0.0)


def test_item_only_capable_model_passes_is_not_flagged():
    out = item_discrimination([1.0, 1.0], [1.0, 0.0])
    assert bool(out["flagged"][1]) is False
    assert np.allclose(out["discrimination"][1], 1.0)


def test_too_hard_and_reversed_items_are_flagged():
    out = item_discrimination([0.0, 0.0], [0.0, 1.0])
    assert out["flagged"].tolist() == [True, True]
    assert np.allclose(out["discrimination"], [0.0, -1.0])
    assert out["n_flagged"] == 2
    assert np.allclose(out["flagged_fraction"], 1.0)


def test_min_gap_controls_the_threshold():
    strict = item_discrimination([0.9], [0.5], min_gap=0.5)
    loose = item_discrimination([0.9], [0.5], min_gap=0.3)
    assert bool(strict["flagged"][0]) is True
    assert bool(loose["flagged"][0]) is False


def test_empty_input_is_handled():
    out = item_discrimination([], [])
    assert out["discrimination"].shape == (0,)
    assert out["flagged"].shape == (0,)
    assert out["flagged"].dtype == bool
    assert out["n_flagged"] == 0
    assert np.allclose(out["flagged_fraction"], 0.0)
```

## Key insight

Running a deliberately weak baseline through your own eval is the
cheapest validity check that exists, and skipping it is how benchmarks
end up reporting 80% when a constant-answer policy scores 75%. The
baseline is not there to be beaten — it is there to tell you which items
carry signal.

The screen also doubles as a scorer smoke test. A negative
discrimination index means a cheap policy outscored a capable model on
that item, which almost never means the weak policy was smart; it means
the item is mis-keyed, the parser is fragile, or the item rewards a
format the capable model does not happen to emit. Sort by index ascending
and read the worst ten by hand — that is usually a productive afternoon.

Note the deliberate choice to flag both-fail items too. They are not
evidence of a broken eval the way reversed items are, but they contribute
nothing to a comparison between models, and separating "too hard" from
"too easy" is a job for the raw scores, not the flag.

## Pitfalls

- `flagged.mean()` on an empty array returns `nan` and emits a
  `RuntimeWarning` rather than raising. A `nan` fraction propagates
  silently into a summary table, so the empty case needs the early
  return.
- Using `<=` instead of `<` against `min_gap`. With binary scores nothing
  lands exactly on 0.5 so it makes no difference, but with graded scores
  it silently changes which items survive the screen.
- Flagging on `capable < baseline` alone. That catches only the reversed
  items and lets every both-pass item through — which is the failure mode
  that actually inflates the headline number.
- Choosing a baseline that is weak in the same way the eval is easy. A
  "first multiple-choice option" baseline tells you nothing about an eval
  whose answers are uniformly distributed; the useful baselines exploit
  the shortcuts you are worried about.
- Deleting the flagged items and re-reporting the mean without saying so.
  The screen is a diagnostic about item quality; silently dropping items
  makes the number incomparable to every prior run.
