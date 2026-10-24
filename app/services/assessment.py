"""Adaptive initial assessment.

15 multiple-choice questions covering 10 skill axes. Each answer scores
0-3 per axis it touches; one "I'm not sure" option per question is
worth 0 across the board (incentivize honesty over guessing).

Selection is deterministic: after each answer, pick the next question
that maximizes information gain about under-touched axes. The first
question is fixed (broad calibration). Stop at 5-10 questions, or
sooner if every axis has been touched at least once after the minimum.

Score interpretation:
- 0  -> reported no familiarity
- 1  -> aware, vague
- 2  -> solid working knowledge
- 3  -> expert / can teach it
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable


# Skill axes. Names match what the rest of the app uses for tag-based
# routing.
AXES: tuple[str, ...] = (
    "transformer_internals",
    "training_mechanics",
    "sampling_decoding",
    "eval_design",
    "numerical_stability",
    "debugging",
    "tokenization",
    "data_pipeline",
    "algorithmic",
    "rust_fluency",
    # AI-safety axes. Added in response to feedback #33: BlueDot's
    # AGI Strategy course (and any "alignment fundamentals" reading)
    # had nowhere appropriate to land on the original 10 axes — all
    # of which are ML-engineering technical. The user's target roles
    # (Anthropic Interpretability, METR, Apollo, etc.) explicitly want
    # safety/alignment fluency on top of engineering skill, so this
    # is also a JD-relevance fix.
    #
    # The assessment quiz doesn't yet have questions for these three;
    # they retain 0 in stored `final_scores` for compatibility. Consumers
    # must use measured_scores so these placeholders are not weaknesses.
    "ai_safety_fundamentals",
    "mechanistic_interpretability",
    "ai_governance_strategy",
)

AXIS_LABELS: dict[str, str] = {
    "transformer_internals": "Transformer internals",
    "training_mechanics": "Training loop mechanics",
    "sampling_decoding": "Sampling & decoding",
    "eval_design": "Eval design",
    "numerical_stability": "Numerical stability",
    "debugging": "Debugging real ML code",
    "tokenization": "Tokenization",
    "data_pipeline": "Data pipelines",
    "algorithmic": "Algorithmic patterns",
    "rust_fluency": "Rust fluency",
    "ai_safety_fundamentals": "AI safety fundamentals",
    "mechanistic_interpretability": "Mechanistic interpretability",
    "ai_governance_strategy": "AGI strategy & governance",
}

MIN_QUESTIONS = 5
MAX_QUESTIONS = 10


@dataclass(frozen=True)
class Option:
    text: str
    scores: dict[str, int]  # axis -> 0..3


@dataclass(frozen=True)
class Question:
    id: str
    prompt: str
    options: tuple[Option, ...]
    axes: tuple[str, ...]


# ---- Question pool ----------------------------------------------------------

# Calibration: always asked first. Touches three of the most central axes
# so it produces useful signal regardless of where the user is strongest.
Q_CALIBRATION = Question(
    id="q01-calibration",
    prompt=(
        "How would you describe your day-to-day, hands-on production "
        "experience with transformer-based ML systems?"
    ),
    axes=("transformer_internals", "training_mechanics", "debugging"),
    options=(
        Option(
            "Years of it. I've trained, debugged, and shipped these models.",
            {"transformer_internals": 3, "training_mechanics": 3, "debugging": 3},
        ),
        Option(
            "Some — I've trained smaller models and run inference at scale.",
            {"transformer_internals": 2, "training_mechanics": 2, "debugging": 2},
        ),
        Option(
            "I've read papers and used APIs, but haven't owned a training loop.",
            {"transformer_internals": 1, "training_mechanics": 0, "debugging": 1},
        ),
        Option(
            "I'm not sure how to characterize it.",
            {"transformer_internals": 0, "training_mechanics": 0, "debugging": 0},
        ),
    ),
)

Q_POOL: tuple[Question, ...] = (
    Q_CALIBRATION,
    Question(
        id="q02-attention-shape",
        prompt=(
            "You're implementing multi-head attention. Your projection "
            "produces `q` of shape `(B, S, D)`. To split into `H` heads, "
            "you should:"
        ),
        axes=("transformer_internals",),
        options=(
            Option(
                "view to (B, S, H, d_head), then transpose to (B, H, S, d_head).",
                {"transformer_internals": 3},
            ),
            Option(
                "view to (B, S, d_head, H), then transpose. Same outcome, different axis order.",
                {"transformer_internals": 1},
            ),
            Option(
                "Use F.scaled_dot_product_attention; it handles head splitting internally.",
                {"transformer_internals": 0},
            ),
            Option("I'm not sure.", {"transformer_internals": 0}),
        ),
    ),
    Question(
        id="q03-kv-cache",
        prompt=(
            "During incremental decoding with a KV cache, the query at "
            "step t attends over:"
        ),
        axes=("transformer_internals", "sampling_decoding"),
        options=(
            Option(
                "The full prefix (cached K/V plus this step's new K/V). No causal mask needed because the query is length 1.",
                {"transformer_internals": 3, "sampling_decoding": 2},
            ),
            Option(
                "The full prefix, with a causal mask applied for safety.",
                {"transformer_internals": 1, "sampling_decoding": 1},
            ),
            Option(
                "Only the new token's K/V; the cache is read-only state.",
                {"transformer_internals": 0, "sampling_decoding": 0},
            ),
            Option("I'm not sure.", {"transformer_internals": 0, "sampling_decoding": 0}),
        ),
    ),
    Question(
        id="q04-grad-accumulation",
        prompt=(
            "You migrate from a single big batch to gradient accumulation "
            "over N micro-batches, using F.cross_entropy with the default "
            "reduction. To preserve the original learning rate behavior:"
        ),
        axes=("training_mechanics", "numerical_stability"),
        options=(
            Option(
                "Divide each micro-batch loss by N before backward(); call optimizer.step() once after the N micro-batches.",
                {"training_mechanics": 3, "numerical_stability": 1},
            ),
            Option(
                "Multiply the learning rate by 1/N to compensate.",
                {"training_mechanics": 1, "numerical_stability": 0},
            ),
            Option(
                "No change needed — F.cross_entropy already averages.",
                {"training_mechanics": 0, "numerical_stability": 0},
            ),
            Option("I'm not sure.", {"training_mechanics": 0, "numerical_stability": 0}),
        ),
    ),
    Question(
        id="q05-eval-mode",
        prompt=(
            "Your eval harness reports slightly different accuracy on "
            "repeated runs over the same data. The most likely cause:"
        ),
        axes=("training_mechanics", "debugging"),
        options=(
            Option(
                "Forgetting model.eval() — dropout/batchnorm are still in training behavior.",
                {"training_mechanics": 3, "debugging": 3},
            ),
            Option(
                "Forgetting torch.no_grad() — autograd noise is leaking into the forward pass.",
                {"training_mechanics": 1, "debugging": 1},
            ),
            Option(
                "Floating-point nondeterminism; nothing to do about it.",
                {"training_mechanics": 0, "debugging": 0},
            ),
            Option("I'm not sure.", {"training_mechanics": 0, "debugging": 0}),
        ),
    ),
    Question(
        id="q06-cross-entropy",
        prompt=(
            "You want a numerically-stable cross-entropy from raw logits. "
            "The right move when some logits are large in magnitude:"
        ),
        axes=("numerical_stability",),
        options=(
            Option(
                "Subtract the per-row max before exp; log(sum(exp(x_i))) = m + log(sum(exp(x_i - m))).",
                {"numerical_stability": 3},
            ),
            Option(
                "Clamp logits to a maximum value (e.g., 50) before computing softmax.",
                {"numerical_stability": 1},
            ),
            Option(
                "Apply softmax first, then take log — PyTorch handles the rest.",
                {"numerical_stability": 0},
            ),
            Option("I'm not sure.", {"numerical_stability": 0}),
        ),
    ),
    Question(
        id="q07-top-p",
        prompt=(
            "Top-p (nucleus) sampling with p = 0.5 on a distribution where "
            "the most-likely token has mass 0.7 should:"
        ),
        axes=("sampling_decoding",),
        options=(
            Option(
                "Keep only that token; the smallest set whose cumulative mass ≥ p includes the token that crosses the threshold.",
                {"sampling_decoding": 3},
            ),
            Option(
                "Keep no tokens — none alone reaches p; renormalize over the original distribution.",
                {"sampling_decoding": 0},
            ),
            Option(
                "Sample proportionally only from tokens with individual mass ≥ p.",
                {"sampling_decoding": 0},
            ),
            Option("I'm not sure.", {"sampling_decoding": 0}),
        ),
    ),
    Question(
        id="q08-temperature",
        prompt=(
            "What happens to a softmax distribution as the temperature T → 0+?"
        ),
        axes=("sampling_decoding", "numerical_stability"),
        options=(
            Option(
                "It approaches a one-hot on the argmax; logits/T grows, softmax saturates.",
                {"sampling_decoding": 3, "numerical_stability": 2},
            ),
            Option(
                "It approaches uniform; small T means small differences after scaling.",
                {"sampling_decoding": 0, "numerical_stability": 0},
            ),
            Option(
                "It approaches the original distribution; temperature applies only at T > 1.",
                {"sampling_decoding": 0, "numerical_stability": 0},
            ),
            Option("I'm not sure.", {"sampling_decoding": 0, "numerical_stability": 0}),
        ),
    ),
    Question(
        id="q09-sycophancy-denominator",
        prompt=(
            "You're computing a sycophancy rate from a paired-comparison "
            "eval. The denominator should be:"
        ),
        axes=("eval_design",),
        options=(
            Option(
                "Items where the neutral-prompt answer was correct — only then is a 'flip on the biased prompt' attributable to sycophancy vs. plain incompetence.",
                {"eval_design": 3},
            ),
            Option(
                "All items — averaging produces a stable headline number across eval runs.",
                {"eval_design": 0},
            ),
            Option(
                "Items where the biased-prompt answer was wrong, regardless of the neutral case.",
                {"eval_design": 1},
            ),
            Option("I'm not sure.", {"eval_design": 0}),
        ),
    ),
    Question(
        id="q10-paired-comparison",
        prompt=(
            "Compared to a single-prompt accuracy metric, paired-comparison "
            "evals (same question, two conditions) are most useful for:"
        ),
        axes=("eval_design",),
        options=(
            Option(
                "Isolating the effect of a single intervention while controlling for the model's baseline competence on the item.",
                {"eval_design": 3},
            ),
            Option(
                "Increasing statistical power by doubling the number of data points.",
                {"eval_design": 1},
            ),
            Option(
                "They're roughly equivalent; either works fine for most use cases.",
                {"eval_design": 0},
            ),
            Option("I'm not sure.", {"eval_design": 0}),
        ),
    ),
    Question(
        id="q11-debug-softmax-ce",
        prompt=(
            "A junior engineer writes `loss = F.cross_entropy(F.softmax(logits, "
            "dim=-1), targets)`. The most precise critique:"
        ),
        axes=("debugging", "training_mechanics"),
        options=(
            Option(
                "F.cross_entropy expects raw logits; applying softmax first creates a 'double softmax' that gives near-correct loss values but flattened gradients.",
                {"debugging": 3, "training_mechanics": 3},
            ),
            Option(
                "Use F.nll_loss instead of F.cross_entropy when working with probabilities.",
                {"debugging": 2, "training_mechanics": 2},
            ),
            Option(
                "It's fine — F.cross_entropy is robust to either input form.",
                {"debugging": 0, "training_mechanics": 0},
            ),
            Option("I'm not sure.", {"debugging": 0, "training_mechanics": 0}),
        ),
    ),
    Question(
        id="q12-bpe",
        prompt=(
            "In BPE training, why must the corpus be re-walked after each "
            "merge rather than using a precomputed pair-frequency table?"
        ),
        axes=("tokenization",),
        options=(
            Option(
                "Each merge rewrites pairs in the corpus; new adjacencies appear (the merged symbol plus its neighbor) that didn't exist before.",
                {"tokenization": 3},
            ),
            Option(
                "Floating-point accumulation error in the precomputed counts.",
                {"tokenization": 0},
            ),
            Option(
                "Memory pressure; the count table for a large vocab won't fit.",
                {"tokenization": 1},
            ),
            Option("I'm not sure.", {"tokenization": 0}),
        ),
    ),
    Question(
        id="q13-jsonl",
        prompt=(
            "You receive a JSONL training file with unknown amounts of "
            "malformed lines, missing fields, and duplicates. Your first "
            "pass should:"
        ),
        axes=("data_pipeline",),
        options=(
            Option(
                "Stream the file line-by-line, count each failure category separately (parse, missing field, empty value, duplicate) so the upstream owner gets a real bug report.",
                {"data_pipeline": 3},
            ),
            Option(
                "Wrap the whole load in a try/except and log how many lines were skipped.",
                {"data_pipeline": 1},
            ),
            Option(
                "Load with pandas.read_json and drop NA rows; pandas handles the cleanup.",
                {"data_pipeline": 0},
            ),
            Option("I'm not sure.", {"data_pipeline": 0}),
        ),
    ),
    Question(
        id="q14-algo-pattern",
        prompt=(
            "You need the longest run of items in a sequence satisfying a "
            "predicate, with at most k local violations allowed inside the "
            "run. The right algorithmic shape:"
        ),
        axes=("algorithmic",),
        options=(
            Option(
                "Sliding window with two pointers: extend right; shrink left when the violation count exceeds k.",
                {"algorithmic": 3},
            ),
            Option(
                "Dynamic programming over (index, violations-so-far).",
                {"algorithmic": 1},
            ),
            Option(
                "Sort the items by their predicate values and scan.",
                {"algorithmic": 0},
            ),
            Option("I'm not sure.", {"algorithmic": 0}),
        ),
    ),
    Question(
        id="q15-rust-borrow",
        prompt=(
            "A Rust function takes a string argument that it only needs to "
            "read. To accept both string literals and owned `String`s "
            "without forcing the caller to clone:"
        ),
        axes=("rust_fluency",),
        options=(
            Option(
                "Take `s: &str`. Owned `String` auto-derefs; string literals are already `&'static str`.",
                {"rust_fluency": 3},
            ),
            Option(
                "Take `s: String`. Callers can wrap literals with `.to_string()`.",
                {"rust_fluency": 1},
            ),
            Option(
                "Take `s: impl AsRef<str>` to maximize generality.",
                {"rust_fluency": 2},
            ),
            Option("I'm not sure.", {"rust_fluency": 0}),
        ),
    ),
    Question(
        id="q16-eval-position-bias",
        prompt=(
            "In a paired A/B preference eval, a judge model prefers "
            "response A 80% of the time. Before trusting that, you should "
            "first:"
        ),
        axes=("eval_design",),
        options=(
            Option(
                "Re-run each pair with the order swapped and keep only "
                "preferences that hold in both orders — judges have a "
                "position bias that can manufacture an 80% on its own.",
                {"eval_design": 3},
            ),
            Option(
                "Increase the sample size — 80% could be noise.",
                {"eval_design": 1},
            ),
            Option(
                "Trust it; 80% is a large, clear margin.",
                {"eval_design": 0},
            ),
            Option("I'm not sure.", {"eval_design": 0}),
        ),
    ),
    Question(
        id="q17-judge-reliability",
        prompt=(
            "Two grader models agree on 92% of pass/fail labels for a "
            "benchmark where ~90% of items pass. As a reliability claim, "
            "that 92% is:"
        ),
        axes=("eval_design",),
        options=(
            Option(
                "Weak — with a 90% pass rate, two independent graders "
                "agree ~82% by chance; use a chance-corrected measure "
                "(Cohen's kappa) instead.",
                {"eval_design": 3},
            ),
            Option(
                "Strong — 92% agreement is high inter-rater reliability.",
                {"eval_design": 0},
            ),
            Option(
                "Fine once you confirm both graders used the same prompt.",
                {"eval_design": 1},
            ),
            Option("I'm not sure.", {"eval_design": 0}),
        ),
    ),
    Question(
        id="q18-format-sensitivity",
        prompt=(
            "A model's score on a benchmark shifts by 15 points when you "
            "only reword the prompt template (same questions). The most "
            "defensible conclusion is:"
        ),
        axes=("eval_design",),
        options=(
            Option(
                "The benchmark is partly measuring format-sensitivity, "
                "not just the capability — report robustness across "
                "formats, not a single-format headline number.",
                {"eval_design": 3},
            ),
            Option(
                "Pick the format that gives the highest score and report "
                "that as the model's true capability.",
                {"eval_design": 0},
            ),
            Option(
                "Average the two formats and report the mean as the score.",
                {"eval_design": 1},
            ),
            Option("I'm not sure.", {"eval_design": 0}),
        ),
    ),
)


_BY_ID: dict[str, Question] = {q.id: q for q in Q_POOL}


def get_question(qid: str) -> Question | None:
    return _BY_ID.get(qid)


# ---- Adaptive picker --------------------------------------------------------


def pick_next(answered_ids: list[str]) -> Question | None:
    """Return the next question, or None if the run should stop."""
    # Older runs can contain repeated answers; count each known question once.
    answered_ids = list(dict.fromkeys(qid for qid in answered_ids if qid in _BY_ID))
    if not answered_ids:
        return Q_CALIBRATION

    if len(answered_ids) >= MAX_QUESTIONS:
        return None

    touched: Counter[str] = Counter()
    for qid in answered_ids:
        q = _BY_ID.get(qid)
        if q is None:
            continue
        for ax in q.axes:
            touched[ax] += 1

    if len(answered_ids) >= MIN_QUESTIONS:
        every_axis_touched = all(touched[a] > 0 for a in AXES)
        if every_axis_touched:
            return None

    asked = set(answered_ids)
    best: Question | None = None
    best_score = -1.0
    for q in Q_POOL:
        if q.id in asked:
            continue
        # Information-gain heuristic: prefer questions whose axes have
        # been touched the least.
        score = sum(1.0 / (1 + touched[a]) for a in q.axes)
        if score > best_score:
            best_score = score
            best = q
    return best


# ---- Scoring ----------------------------------------------------------------


def measured_axes(responses: Iterable) -> tuple[str, ...]:
    """Return axes with saved answer evidence, including measured zeroes."""
    axes: set[str] = set()
    seen: set[str] = set()
    for response in responses:
        if response.question_id in seen:
            continue
        seen.add(response.question_id)
        # Saved evidence survives changes to the question pool; inferring
        # coverage from today's questions would rewrite historical results.
        axes.update(response.axis_scores)
    return tuple(axis for axis in AXES if axis in axes)


def measured_scores(scores: dict[str, float], responses: Iterable) -> dict[str, float]:
    """Filter saved scores by response coverage without rescoring the run."""
    return {axis: scores[axis] for axis in measured_axes(responses) if axis in scores}


def aggregate_scores(responses: Iterable) -> dict[str, float]:
    """Sum per-axis scores across responses, dividing by max-possible to
    normalize to [0, 1] per axis."""
    totals: dict[str, float] = {a: 0.0 for a in AXES}
    maxes: dict[str, float] = {a: 0.0 for a in AXES}
    seen: set[str] = set()
    for r in responses:
        if r.question_id in seen:
            continue
        seen.add(r.question_id)
        q = _BY_ID.get(r.question_id)
        if q is None:
            continue
        for ax in q.axes:
            best_for_q = max(opt.scores.get(ax, 0) for opt in q.options)
            maxes[ax] += best_for_q
        for ax, val in r.axis_scores.items():
            if ax in totals:
                totals[ax] += val
    return {a: (totals[a] / maxes[a]) if maxes[a] > 0 else 0.0 for a in AXES}


# ---- Suggested first problem -----------------------------------------------

# Map each axis to a list of slugs (problems most relevant). Prefer the
# easiest entry first; the suggester picks the easiest unattempted one.
_AXIS_TO_SLUGS: dict[str, list[str]] = {
    "transformer_internals": [
        "layernorm-from-scratch",
        "scaled-dot-product-attention",
        "multi-head-attention-reshape",
        "kv-cache",
    ],
    "training_mechanics": [
        "minimal-training-loop",
        "teacher-forcing-grad-accum",
        "debug-train-eval-mode",
    ],
    "sampling_decoding": [
        "softmax-temperature",
        "top-k-sampling",
        "top-p-sampling",
        "beam-search",
    ],
    "eval_design": [
        "sycophancy-eval-scoring",
        "paired-eval-position-debias",
        "judge-agreement-kappa",
        "format-robustness-gap",
    ],
    "numerical_stability": [
        "cross-entropy-stable",
        "layernorm-vs-rmsnorm",
        "debug-bessel-layernorm",
    ],
    "debugging": [
        "debug-softmax-before-ce",
        "debug-bessel-layernorm",
        "debug-causal-mask",
        "debug-ce-axis",
    ],
    "tokenization": [
        "bpe-merges",
        "greedy-tokenizer-rust",
    ],
    "data_pipeline": [
        "jsonl-pipeline",
    ],
    "algorithmic": [
        # Fundamentals on-ramp first (easiest → hardest). A learner weak on
        # the algorithmic axis should meet the gentle DS&A warm-ups before
        # the ML-flavored algo problems below.
        "warmest-reading",
        "most-frequent-reading",
        "pair-sum",
        "nested-sum",
        "reverse-linked-list",
        "depth-first-values",
        "climbing-ways",
        "connected-components",
        # ML-context algo problems.
        "algo-validation-window",
        "algo-eval-aggregation",
        "algo-config-deps",
        "algo-token-lcs",
    ],
    "rust_fluency": [
        "ring-buffer-rust",
        "greedy-tokenizer-rust",
    ],
}


def weakest_axis(scores: dict[str, float]) -> str | None:
    """Return the weakest measured axis with exercise recommendations."""
    candidates = (axis for axis in AXES if axis in scores and _AXIS_TO_SLUGS.get(axis))
    return min(candidates, key=scores.__getitem__, default=None)


def suggested_slugs_for_axis(axis: str) -> list[str]:
    return _AXIS_TO_SLUGS.get(axis, [])


def recommended_daily_mode(scores: dict[str, float]) -> str:
    """Which daily mode the assessment argues for.

    "path" — steady progression: the scheduler's deterministic order,
    which naturally re-queues unfinished work. Right while *learning*:
    a learner with weak axes needs sequenced building blocks.

    "remix" — shuffled review: same scoring, randomized order. Right
    for *review*: someone already strong across the axes benefits from
    interleaving (retrieval practice) more than from a fixed sequence.

    Threshold: mean normalized measured-axis score >= 2/3 (equivalent
    to 2 of 3 on the answer rubric) recommends remix; anything weaker,
    path. Pass measured_scores to exclude unknown axes. Empty scores → path.
    """
    values = [scores[axis] for axis in AXES if axis in scores]
    if not values:
        return "path"
    mean = sum(values) / len(values)
    return "remix" if mean >= 2 / 3 else "path"
