"""Weighted scheduler. NOT SM-2.

SM-2 is calibrated for flashcard-grain review: seconds per card, dozens of
reviews per day. v1 problems are 30-60 minutes each at 1-3 per day. The
weighted scheduler below computes a `due_score` for every core problem
each time the daily session is built, and surfaces the top-N subject to
two constraints: at most one 60-min problem, and the surfaced set spans
at least two of {ml_coding, debug, algo} when feasible.

Components — all summed linearly with explicit, configurable weights in
config.toml. The names below match the config keys.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from ..config import SchedulerWeights
from ..models import Attempt, Problem, ReviewState


# Bucket each problem into one of three category labels used for the
# "span at least 2 categories" constraint. Algo gets its own bucket because
# the user explicitly carved it out as 15% of the mix. Debug is its own
# bucket. Everything else is ml_coding.
def category_of(p: Problem) -> str:
    if p.problem_type == "code_debug":
        return "debug"
    if "algo" in p.structural_tags or "algorithmic" in p.structural_tags:
        return "algo"
    return "ml_coding"


# Mapping from problem tags + problem_type to the 10 assessment axes.
# Used by the content-alignment scorer component to find problems whose
# subject matter overlaps with content the user has recently completed.
_TAG_TO_AXES: dict[str, set[str]] = {
    # Direct axis-name matches
    "transformer_internals": {"transformer_internals"},
    "training_internals":    {"training_mechanics"},
    "training_mechanics":    {"training_mechanics"},
    "sampling_decoding":     {"sampling_decoding"},
    "eval_design":           {"eval_design"},
    "numerical_stability":   {"numerical_stability"},
    "tokenization":          {"tokenization"},
    "data_pipeline":         {"data_pipeline"},
    "algorithmic":           {"algorithmic"},
    "rust_fluency":          {"rust_fluency"},
    "debugging":             {"debugging"},
    # Common synonyms used in the existing problem corpus
    "attention":             {"transformer_internals"},
    "training":              {"training_mechanics"},
    "eval":                  {"eval_design"},
    "sampling":              {"sampling_decoding"},
    "decoding":              {"sampling_decoding"},
    "rust":                  {"rust_fluency"},
    "algo":                  {"algorithmic"},
}


def problem_axes(p: Problem) -> set[str]:
    """Best-effort mapping from a Problem to the set of skill axes it
    exercises. Walks all tag fields, plus the problem_type for debug."""
    axes: set[str] = set()
    for tag in (p.domain_tags or []) + (p.structural_tags or []) + (p.competency_tags or []):
        axes |= _TAG_TO_AXES.get(tag, set())
    if p.problem_type == "code_debug":
        axes.add("debugging")
    return axes


@dataclass
class Scored:
    problem: Problem
    score: float
    components: dict[str, float]


class Scorer:
    def __init__(self, weights: SchedulerWeights, now: datetime) -> None:
        self.w = weights
        self.now = now

    def score(
        self,
        problem: Problem,
        last_attempt: Attempt | None,
        state: ReviewState | None,
        topic_last_seen: dict[str, datetime],
        recent_content_axes: set[str] | None = None,
        jd_axis_weights: dict[str, float] | None = None,
        jd_signal_tags: set[str] | None = None,
        easy_first_bias: float = 0.0,
    ) -> Scored:
        c: dict[str, float] = {}

        # When the user has no assessment data yet, prefer easier
        # problems so onboarding-skip lands them at the simplest
        # problems first and the scheduler escalates as they
        # accumulate signal. Caller passes 0 once an assessment lands.
        if easy_first_bias > 0:
            d = (problem.difficulty or "").lower()
            mult = {"easy": 1.0, "medium": 0.5, "hard": 0.0}.get(d, 0.5)
            if mult > 0:
                c["easy_first_bias"] = easy_first_bias * mult

        if last_attempt is None:
            c["never_attempted"] = self.w.never_attempted
        else:
            days = max(0.0, (self.now - last_attempt.started_at).total_seconds() / 86400.0)
            # log-scaled so day 1 -> ~0.3, day 7 -> ~2.0, day 30 -> ~3.4
            c["days_since"] = self.w.days_since * math.log1p(days)

            conf = last_attempt.confidence_1_to_5 or 3
            # confidence 1 -> 1.0 * w; confidence 5 -> 0
            c["low_confidence"] = self.w.low_confidence * max(0.0, (5 - conf) / 4.0)

            if (
                last_attempt.time_to_first_edit_seconds is not None
                and last_attempt.ended_at is not None
            ):
                duration = (last_attempt.ended_at - last_attempt.started_at).total_seconds()
                target = problem.time_bucket * 60
                if target > 0:
                    over = max(0.0, (duration - target) / target)
                    c["over_time"] = self.w.over_time * min(over, 1.5)

            if last_attempt.looked_at_solution:
                c["used_reference"] = self.w.used_reference

            # Hint-ladder penalty. Mirrors used_reference. We score by
            # the *highest tier reached* on any phase rather than total
            # count, so requesting two tier-1 nudges on different
            # phases doesn't double-penalize. Tier 1 = 1/3 weight,
            # tier 2 = 2/3, tier 3 = full.
            if last_attempt.hints_used:
                max_tier = max(int(v) for v in last_attempt.hints_used.values())
                # Clamp at 3 (the ladder caps there).
                max_tier = min(max_tier, 3)
                if max_tier > 0:
                    c["used_hints"] = self.w.used_hints * (max_tier / 3.0)

        # Topic gap: for each tag on this problem, if no problem with that tag
        # was attempted in 14 days, that contributes one weight unit.
        gap_count = 0
        threshold = self.now - timedelta(days=14)
        for tag in problem.domain_tags + problem.structural_tags:
            last = topic_last_seen.get(tag)
            if last is None or last < threshold:
                gap_count += 1
        if gap_count > 0:
            c["topic_gap"] = self.w.topic_gap * gap_count

        # Content alignment: boost problems whose axes overlap content the
        # user finished recently. Cap at 3 overlapping axes — beyond that
        # the boost saturates so a single topic can't dominate the daily mix.
        if recent_content_axes:
            overlap = len(problem_axes(problem) & recent_content_axes)
            if overlap > 0:
                c["content_aligned"] = self.w.content_aligned * min(overlap, 3) / 3.0

        # JD alignment: blend two signals from the active JD.
        # (a) axis_weights × problem's axes — does the JD emphasize the
        #     axes this problem exercises?
        # (b) signal_tags ∩ problem.jd_signal_tags — token-level overlap.
        # Combined and capped at the configured weight.
        if (jd_axis_weights or jd_signal_tags) and self.w.jd_aligned > 0:
            axis_component = 0.0
            tag_component = 0.0
            if jd_axis_weights:
                axes = problem_axes(problem)
                if axes:
                    axis_component = sum(jd_axis_weights.get(a, 0.0) for a in axes) / len(axes)
            if jd_signal_tags:
                pj = set(problem.jd_signal_tags or [])
                if pj:
                    tag_component = len(pj & jd_signal_tags) / len(pj)
            # 60/40 blend; saturates at 1.0.
            blended = min(1.0, 0.6 * axis_component + 0.4 * tag_component)
            if blended > 0:
                c["jd_aligned"] = self.w.jd_aligned * blended

        total = sum(c.values())
        return Scored(problem=problem, score=total, components=c)


class SessionStrategy(ABC):
    @abstractmethod
    def build(
        self,
        problems: Sequence[Problem],
        attempts_by_problem: dict[int, Attempt],
        states_by_problem: dict[int, ReviewState],
        size: int,
        recent_content_axes: set[str] | None = None,
        jd_axis_weights: dict[str, float] | None = None,
        jd_signal_tags: set[str] | None = None,
    ) -> list[Scored]: ...


class ReviewStrategy(SessionStrategy):
    """v1 strategy: top-N by due_score with category-span and 60-min constraints."""

    def __init__(self, weights: SchedulerWeights, now: datetime | None = None) -> None:
        self.weights = weights
        self.now = now or datetime.utcnow()

    def _topic_last_seen(
        self,
        problems: Sequence[Problem],
        attempts_by_problem: dict[int, Attempt],
    ) -> dict[str, datetime]:
        seen: dict[str, datetime] = {}
        for p in problems:
            a = attempts_by_problem.get(p.id)
            if a is None:
                continue
            for tag in p.domain_tags + p.structural_tags:
                if tag not in seen or a.started_at > seen[tag]:
                    seen[tag] = a.started_at
        return seen

    def build(
        self,
        problems: Sequence[Problem],
        attempts_by_problem: dict[int, Attempt],
        states_by_problem: dict[int, ReviewState],
        size: int,
        recent_content_axes: set[str] | None = None,
        jd_axis_weights: dict[str, float] | None = None,
        jd_signal_tags: set[str] | None = None,
        easy_first_bias: float = 0.0,
        remix_rng=None,
        include_warmups: bool = False,
    ) -> list[Scored]:
        # Onboarding deliberately mixes warmups into its pool; ordinary
        # review sessions keep the defensive exclusion unless opted in.
        candidates = [p for p in problems if include_warmups or not p.is_warmup]
        topic = self._topic_last_seen(candidates, attempts_by_problem)
        scorer = Scorer(self.weights, self.now)
        scored = [
            scorer.score(
                p,
                attempts_by_problem.get(p.id),
                states_by_problem.get(p.id),
                topic,
                recent_content_axes=recent_content_axes,
                jd_axis_weights=jd_axis_weights,
                jd_signal_tags=jd_signal_tags,
                easy_first_bias=easy_first_bias,
            )
            for p in candidates
        ]
        scored.sort(key=lambda s: s.score, reverse=True)

        # Daily-mode "remix": shuffle the ranked list so review sessions
        # resurface material in a random order instead of the scheduler's
        # deterministic progression ("path" mode = no rng, the default).
        # Shuffling AFTER scoring keeps the "why surfaced" breakdown
        # truthful per-problem; only the ordering is randomized. The
        # greedy constraint walk below still enforces category span and
        # the 60-minute cap either way.
        if remix_rng is not None:
            remix_rng.shuffle(scored)

        # Apply constraints greedily. Walk the sorted list; pick the
        # highest-scoring problem that does not violate constraints, repeat.
        chosen: list[Scored] = []
        categories_present: set[str] = set()
        sixty_count = 0
        remaining = list(scored)

        while remaining and len(chosen) < size:
            for i, cand in enumerate(remaining):
                if cand.problem.time_bucket == 60 and sixty_count >= self.weights.max_60min_per_session:
                    continue
                # Category-span enforcement only kicks in on the *last* slot:
                # if filling it would leave us with a single category and a
                # different category is still available, prefer the different one.
                if (
                    self.weights.require_category_span
                    and len(chosen) == size - 1
                    and len(categories_present) == 1
                    and category_of(cand.problem) in categories_present
                ):
                    alternative_exists = any(
                        category_of(c.problem) not in categories_present
                        and not (c.problem.time_bucket == 60 and sixty_count >= self.weights.max_60min_per_session)
                        for c in remaining[i + 1 :]
                    )
                    if alternative_exists:
                        continue
                chosen.append(cand)
                if cand.problem.time_bucket == 60:
                    sixty_count += 1
                categories_present.add(category_of(cand.problem))
                remaining.pop(i)
                break
            else:
                break

        return chosen


def pick_warmup(
    warmups: Sequence[Problem],
    last_attempt_by_problem: dict[int, Attempt],
    recency_floor_days: int,
    now: datetime,
) -> Problem | None:
    """Pick a warmup the user hasn't attempted in `recency_floor_days`.
    If all are inside that window, pick the least-recently attempted.
    """
    if not warmups:
        return None
    threshold = now - timedelta(days=recency_floor_days)
    eligible = [
        p for p in warmups
        if last_attempt_by_problem.get(p.id) is None
        or last_attempt_by_problem[p.id].started_at < threshold
    ]
    pool = eligible if eligible else list(warmups)

    def key(p: Problem) -> datetime:
        a = last_attempt_by_problem.get(p.id)
        return a.started_at if a else datetime.min

    pool.sort(key=key)
    return pool[0]
