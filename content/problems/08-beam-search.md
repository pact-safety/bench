---
slug: beam-search
title: Beam search decoder with length normalization
difficulty: hard
time_bucket: 60
problem_type: code_compose
is_warmup: false
structural_tags: [sampling, control_flow]
domain_tags: [eval]
competency_tags: [decoding]
jd_signal_tags: [decoding, sequence_models]
original: true
authored_by: claude_code_v1_build
authored_date: 2026-05-12
version: 1
---

## Prompt

Implement greedy beam search for an autoregressive sequence model. You're
given:

- `step_fn(prefix: list[int]) -> torch.Tensor` — returns logits of shape
  `(V,)` for the next token given a prefix of token ids.
- `start_token: int`, `end_token: int`
- `beam_size: int`, `max_len: int`, `length_alpha: float`

Return the highest-scoring completed beam as a `list[int]`, *excluding*
the start token. Score is sum of log-probabilities, length-normalized
by `1 / len ** length_alpha`. A beam is "completed" the step it emits
the end token; completed beams stop expanding but compete for the final
selection. If no beam emits the end token within `max_len` steps, return
the best partial beam at `max_len`.

```
def beam_search(step_fn, start_token, end_token, beam_size, max_len, length_alpha) -> list[int]
```

## Starter

```
import torch


def beam_search(step_fn, start_token, end_token, beam_size, max_len, length_alpha):
    # TODO
    pass
```

## Solution

```
import math
import torch
import torch.nn.functional as F


def beam_search(step_fn, start_token, end_token, beam_size, max_len, length_alpha):
    # Each entry: (logprob_sum, tokens_excluding_start, finished_bool)
    beams = [(0.0, [], False)]
    finished = []

    for _ in range(max_len):
        if not beams:
            break
        candidates = []
        for score, toks, done in beams:
            if done:
                candidates.append((score, toks, True))
                continue
            logits = step_fn([start_token] + toks)
            logp = F.log_softmax(logits, dim=-1)
            topk = torch.topk(logp, beam_size)
            for v, idx in zip(topk.values.tolist(), topk.indices.tolist()):
                candidates.append((score + v, toks + [idx], idx == end_token))
        # Keep top-K by length-normalized score, but only for ranking;
        # the raw sum is stored so further extensions are correct.
        def rank(c):
            s, t, _ = c
            return s / max(1, len(t)) ** length_alpha
        candidates.sort(key=rank, reverse=True)
        next_beams = []
        for c in candidates:
            if c[2]:
                finished.append(c)
            else:
                next_beams.append(c)
            if len(next_beams) >= beam_size:
                break
        beams = next_beams

    pool = finished if finished else beams
    pool.sort(key=lambda c: c[0] / max(1, len(c[1])) ** length_alpha, reverse=True)
    return pool[0][1] if pool else []
```

## Tests

```
import torch

# Deterministic toy model: at any prefix, the next token's logits are
# fixed by the last token. This makes beam search reduce to a graph
# search we can verify by hand.
V = 5
START, END = 0, 4
table = torch.full((V, V), -10.0)
# Path A: 0 -> 1 -> 2 -> 4 (score: -1 + -1 + -1 = -3, length 3)
table[0, 1] = -1.0
table[1, 2] = -1.0
table[2, 4] = -1.0
# Path B: 0 -> 3 -> 4 (score: -1.5 + -1.5 = -3.0, length 2)
table[0, 3] = -1.5
table[3, 4] = -1.5


def step_fn(prefix):
    return table[prefix[-1]]


# alpha = 0 (no length normalization): both paths tie at raw -3.
# Either is acceptable; just confirm we end on END and pick one of the two.
out = beam_search(step_fn, START, END, beam_size=2, max_len=10, length_alpha=0.0)
assert out[-1] == END
assert out in ([1, 2, 4], [3, 4])

# alpha = 1.0: Path A wins because -3/3^1 = -1.0 > -3/2^1 = -1.5.
# Length normalization with alpha=1 rewards longer sequences when raw
# scores are equal (the canonical NMT-style normalization).
out_a = beam_search(step_fn, START, END, beam_size=2, max_len=10, length_alpha=1.0)
assert out_a == [1, 2, 4], out_a

# beam_size=1 collapses to greedy. At [0] both 1 and 3 are tied at -1
# vs -1.5 — wait, 1 is -1 which beats 3 at -1.5. So greedy picks 1,
# then from [0, 1] picks 2 (-1), then from [0, 1, 2] picks 4 (-1).
out_g = beam_search(step_fn, START, END, beam_size=1, max_len=10, length_alpha=0.0)
assert out_g == [1, 2, 4], out_g

print("OK")
```

## Key insight

Length normalization affects *ranking*, not the score you accumulate. You
sum raw log-probs forward; only when you compare beams (and when you
return the final answer) do you divide by `len ** alpha`. Otherwise the
arithmetic is no longer additive across steps.

## Pitfalls

- Multiplying log-probs by `1/len**alpha` at each step makes the score
  non-additive and gives different results depending on how you fold it
  in. The standard implementation normalizes only at selection time.
- Finished beams must not expand further but should still compete for
  the final pick. Dropping them prematurely loses the answer; expanding
  them generates noise.
- With `beam_size = 1`, beam search must equal greedy decoding. Use this
  as a sanity check.
