---
slug: 32-linear-probe-split
title: Linear probe with a leak-free train/test split
difficulty: medium
time_bucket: 30
problem_type: code_compose
is_warmup: false
structural_tags: [data_splitting, linear_algebra, numpy_only]
domain_tags: [probing, interpretability, evaluation]
competency_tags: [mechanistic_interpretability, eval_design]
jd_signal_tags: [interpretability, mechanistic_interp, eval_design]
original: true
authored_by: claude_code_arena_prep
authored_date: 2026-08-19
version: 1
---

## Prompt

Train a linear probe on per-token activations and report held-out
accuracy. The probe itself is the easy part — closed-form ridge
regression on `{-1, +1}` targets, then predict by sign. The part that
actually matters is the split.

Activations come in shaped `(n_seq, seq_len, d_model)`: `n_seq`
sequences, each with `seq_len` token positions. Labels are
`(n_seq, seq_len)` and binary. The obvious move is to flatten everything
into `n_seq * seq_len` independent rows and split those rows at random.
That is a leak: tokens from the same sequence are highly correlated, so
the training set tells you the answer for the test set and your reported
accuracy measures memorization, not a linear feature.

Implement both modes so the difference is visible:

```python
def probe_accuracy(acts, labels, split="sequence", test_frac=0.5,
                   ridge=1e-3, seed=0) -> float:
    # acts:   (n_seq, seq_len, d_model)
    # labels: (n_seq, seq_len), values in {0, 1}
    # split:  "sequence" (correct) or "token" (leaky)
    # returns: test accuracy as a float in [0, 1]
```

- `split="sequence"` holds out whole sequences: a sequence is entirely in
  train or entirely in test.
- `split="token"` holds out individual token rows, ignoring which
  sequence they came from. This is the leaky baseline, and it exists in
  the API so you can measure the gap.

Fit with a bias term. Solve `(X^T X + ridge * I) w = X^T y` — do not
iterate to convergence, the closed form is exact and faster. Raise
`ValueError` if `acts` is not 3-D or if `labels` does not match
`acts.shape[:2]`.

numpy only — no torch, no sklearn.

## Starter

```python
import numpy as np


def probe_accuracy(acts, labels, split="sequence", test_frac=0.5,
                   ridge=1e-3, seed=0):
    """Fit a linear probe on per-token activations and score it held-out.

    Args:
        acts:      (n_seq, seq_len, d_model) float array of activations.
        labels:    (n_seq, seq_len) array of binary labels.
        split:     "sequence" to hold out whole sequences (leak-free),
                   "token" to hold out individual token rows (leaky).
        test_frac: fraction of the split unit held out for test.
        ridge:     L2 regularization added to the Gram matrix diagonal.
        seed:      seed for the split permutation, so runs are reproducible.

    Returns:
        Test accuracy as a Python float in [0, 1].

    Raises:
        ValueError: if acts is not 3-D, if labels does not match
            acts.shape[:2], or if split is not one of the two modes.
    """
    # 1. Validate the input shapes before touching the data.
    ...
    # 2. Flatten to one row per token, keeping each row's group identity.
    ...
    # 3. Choose the unit being held out, and derive the train/test masks.
    ...
    # 4. Fit the linear model in closed form on the training rows only.
    ...
    # 5. Predict on the held-out rows.
    ...
    # 6. Score against the held-out labels and return.
    raise NotImplementedError()
```

## Solution

```python
import numpy as np


def probe_accuracy(acts, labels, split="sequence", test_frac=0.5,
                   ridge=1e-3, seed=0):
    acts = np.asarray(acts, dtype=float)
    labels = np.asarray(labels)
    if acts.ndim != 3:
        raise ValueError("acts must be (n_seq, seq_len, d_model)")
    if labels.shape != acts.shape[:2]:
        raise ValueError("labels must be (n_seq, seq_len)")
    n_seq, seq_len, d_model = acts.shape

    X = acts.reshape(n_seq * seq_len, d_model)
    y = np.where(labels.reshape(-1) > 0, 1.0, -1.0)
    # The group identity is what the leak-free split needs and the leaky
    # split throws away. Keeping it is the whole trick.
    seq_of_token = np.repeat(np.arange(n_seq), seq_len)

    rng = np.random.default_rng(seed)
    if split == "sequence":
        order = rng.permutation(n_seq)
        n_test = max(1, int(round(n_seq * test_frac)))
        is_test_seq = np.zeros(n_seq, dtype=bool)
        is_test_seq[order[:n_test]] = True
        test_mask = is_test_seq[seq_of_token]
    elif split == "token":
        n_tokens = X.shape[0]
        order = rng.permutation(n_tokens)
        n_test = max(1, int(round(n_tokens * test_frac)))
        test_mask = np.zeros(n_tokens, dtype=bool)
        test_mask[order[:n_test]] = True
    else:
        raise ValueError("split must be 'sequence' or 'token'")

    Xb = np.concatenate([X, np.ones((X.shape[0], 1))], axis=1)
    X_train, y_train = Xb[~test_mask], y[~test_mask]

    # Ridge, not a bare lstsq: with d_model near or above the number of
    # training rows the Gram matrix is singular, and the diagonal term is
    # what keeps np.linalg.solve well-posed.
    gram = X_train.T @ X_train + ridge * np.eye(Xb.shape[1])
    w = np.linalg.solve(gram, X_train.T @ y_train)

    pred = np.where(Xb[test_mask] @ w >= 0.0, 1.0, -1.0)
    return float(np.mean(pred == y[test_mask]))
```

## Tests

```python
import numpy as np


def test_token_split_leaks_and_sequence_split_does_not():
    # Label is a property of the SEQUENCE, and every token carries that
    # sequence's identity vector. Splitting by token puts near-duplicate
    # tokens on both sides of the split, so the probe can memorize.
    rng = np.random.default_rng(0)
    n_seq, seq_len, d_model = 40, 8, 64
    signatures = rng.normal(size=(n_seq, d_model))
    seq_labels = rng.integers(0, 2, size=n_seq)
    acts = signatures[:, None, :] + 0.01 * rng.normal(size=(n_seq, seq_len, d_model))
    labels = np.repeat(seq_labels[:, None], seq_len, axis=1)

    leaky = probe_accuracy(acts, labels, split="token")
    honest = probe_accuracy(acts, labels, split="sequence")
    assert leaky > 0.9
    assert honest < 0.75
    assert leaky - honest > 0.2


def test_leak_gap_is_not_an_artifact_of_one_split_seed():
    rng = np.random.default_rng(0)
    n_seq, seq_len, d_model = 40, 8, 64
    signatures = rng.normal(size=(n_seq, d_model))
    seq_labels = rng.integers(0, 2, size=n_seq)
    acts = signatures[:, None, :] + 0.01 * rng.normal(size=(n_seq, seq_len, d_model))
    labels = np.repeat(seq_labels[:, None], seq_len, axis=1)

    for seed in range(5):
        leaky = probe_accuracy(acts, labels, split="token", seed=seed)
        honest = probe_accuracy(acts, labels, split="sequence", seed=seed)
        assert leaky > 0.9, (seed, leaky)
        assert honest < 0.75, (seed, honest)


def test_genuine_feature_generalizes_across_sequences():
    rng = np.random.default_rng(3)
    n_seq, seq_len, d_model = 30, 6, 8
    labels = rng.integers(0, 2, size=(n_seq, seq_len))
    acts = rng.normal(size=(n_seq, seq_len, d_model)) * 0.1
    acts[:, :, 0] += np.where(labels > 0, 2.0, -2.0)
    acc = probe_accuracy(acts, labels, split="sequence")
    assert isinstance(acc, float)
    assert 0.0 <= acc <= 1.0
    assert acc > 0.95


def test_rejects_mismatched_label_shape():
    rng = np.random.default_rng(1)
    acts = rng.normal(size=(6, 4, 8))
    labels = rng.integers(0, 2, size=(6, 4))
    try:
        probe_accuracy(acts, labels[:, :2])
    except ValueError:
        pass
    else:
        assert False, "expected ValueError on mismatched label shape"
```

## Key insight

A probe's accuracy is only a claim about the model if the split respects
the unit of correlation in the data. Tokens are not independent samples —
they share a sequence, a prompt, a topic, often a template. Split by
token and you are asking "can the probe recognize sequences it has
already seen?", which it can, trivially, at 100%.

The first test is the diagnostic worth internalizing: the *same* probe
on the *same* data reports 1.00 under the leaky split and chance under
the honest one. Any time a probe result looks too good, the split is the
first thing to check — before the architecture, before the layer choice.

The general rule transfers past probing: split by whatever unit your
correlated observations are grouped by. Sequence for tokens, subject for
trials, document for chunks, user for sessions.

## Pitfalls

- Fitting the probe on all rows and then evaluating on a subset. The
  fit must see only `~test_mask`; touching test rows during `X^T X`
  leaks even under the sequence split.
- Standardizing or PCA-ing the features using statistics computed over
  the *full* dataset. That is the same leak wearing a different hat — any
  preprocessing fit on test data contaminates the estimate.
- Using `np.linalg.lstsq` or an un-regularized inverse when
  `d_model` is comparable to the training row count. The system is
  singular and you get either an exception or a garbage min-norm
  solution that scores near chance for the wrong reason.
- Splitting sequences contiguously (first half train, second half test)
  when the data has any ordering — by class, by collection date, by
  length. Permute first.
- Reporting accuracy on a class-imbalanced item set without a baseline.
  60% accuracy on a 60/40 split is exactly zero evidence of a feature.
