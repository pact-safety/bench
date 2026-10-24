"""Imposter-signal detection — does the user's self-assessment
under-call their actual data?

Pure-functional. No DB, no HTTP, no LLM. Inputs come from the quiz
answers + assessment + (optional) credentials analysis. Output is
a small dataclass the rest of the system reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Iterable, Literal


# Thresholds. Pulled from config.toml at the wiring layer; defaults
# here are the calibrated first-pass values from the design doc.
DEFAULT_NOT_SURE_MILD = 0.50
DEFAULT_NOT_SURE_STRONG = 0.75
DEFAULT_GAP_MILD = 0.20
DEFAULT_GAP_STRONG = 0.35

# Per-axis threshold for flagging an axis as "triggering" the gap.
DEFAULT_PER_AXIS_GAP = 0.20

# Mastery-decay defaults from docs/architecture/imposter-syndrome.md.
DEFAULT_MASTERY_ATTEMPTS = 5
DEFAULT_MASTERY_CONFIDENCE = 4


ImposterState = Literal["none", "mild", "strong"]

_STATE_ORDER: dict[ImposterState, int] = {"none": 0, "mild": 1, "strong": 2}
_NOT_SURE_VARIANTS = {"not_sure", "notsure", "unsure"}


@dataclass
class ImposterSignal:
    state: ImposterState
    not_sure_rate: float
    credential_gap: float | None
    triggering_axes: list[str] = field(default_factory=list)
    detected_at: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "not_sure_rate": round(self.not_sure_rate, 3),
            "credential_gap": (
                round(self.credential_gap, 3) if self.credential_gap is not None else None
            ),
            "triggering_axes": list(self.triggering_axes),
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
        }


def _normalize_answer(answer: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(answer).strip().lower()).strip("_")
    return normalized


def _state_ladder(value: float, mild: float, strong: float) -> ImposterState:
    if value >= strong:
        return "strong"
    if value >= mild:
        return "mild"
    return "none"


def detect(
    *,
    quiz_answers: Iterable[str],
    assessment_scores: dict[str, float],
    credential_scores: dict[str, float] | None,
    now: datetime | None = None,
    # Threshold overrides (for testing / runtime tuning):
    not_sure_mild: float = DEFAULT_NOT_SURE_MILD,
    not_sure_strong: float = DEFAULT_NOT_SURE_STRONG,
    gap_mild: float = DEFAULT_GAP_MILD,
    gap_strong: float = DEFAULT_GAP_STRONG,
    per_axis_gap: float = DEFAULT_PER_AXIS_GAP,
) -> ImposterSignal:
    """Compute the signal from the available inputs.

    Either signal alone can trigger. Both together strengthens the
    output but doesn't multiply (no double-counting).

    `quiz_answers` are strings; we count "not_sure" / "not-sure" /
    "unsure" / etc. — defensive normalization.

    `credential_scores` may be None if no credentials have been
    uploaded yet. In that case, only the not-sure signal contributes.
    """

    answers = [str(answer) for answer in quiz_answers]
    total_answers = len(answers)
    not_sure_count = sum(
        1 for answer in answers if _normalize_answer(answer) in _NOT_SURE_VARIANTS
    )
    not_sure_rate = (not_sure_count / total_answers) if total_answers else 0.0
    not_sure_state = _state_ladder(not_sure_rate, mild=not_sure_mild, strong=not_sure_strong)

    credential_gap: float | None = None
    triggering_axes: list[str] = []

    if credential_scores is not None:
        gap_by_axis: dict[str, float] = {}
        for axis, assessment in assessment_scores.items():
            if axis not in credential_scores:
                continue
            gap_by_axis[axis] = float(credential_scores[axis]) - float(assessment)

        if gap_by_axis:
            credential_gap = sum(gap_by_axis.values()) / len(gap_by_axis)
            sorted_gaps = sorted(gap_by_axis.items(), key=lambda item: (-item[1], item[0]))
            triggering_axes = [axis for axis, gap in sorted_gaps if gap >= per_axis_gap]

    gap_state: ImposterState = "none"
    if credential_gap is not None and credential_gap >= 0.0:
        gap_state = _state_ladder(credential_gap, mild=gap_mild, strong=gap_strong)

    state = max((not_sure_state, gap_state), key=lambda value: _STATE_ORDER[value])

    return ImposterSignal(
        state=state,
        not_sure_rate=not_sure_rate,
        credential_gap=credential_gap,
        triggering_axes=triggering_axes,
        detected_at=now if state != "none" else None,
    )


def _attempt_hits_mastery(
    attempt: object,
    *,
    mastery_confidence_min: int,
) -> bool:
    """Return True when an attempt satisfies the mastery criterion.

    The helper only depends on the two fields we care about so callers
    can pass real Attempt rows or lightweight test doubles.
    """
    solved_without_lookup = bool(getattr(attempt, "solved_without_lookup", False))
    confidence = getattr(attempt, "confidence_1_to_5", None)
    if not solved_without_lookup or confidence is None:
        return False
    try:
        confidence_value = int(confidence)
    except (TypeError, ValueError):
        return False
    return confidence_value >= mastery_confidence_min


def maybe_decay(
    settings: dict,
    attempts: Iterable[object],
    *,
    mastery_attempts_required: int = DEFAULT_MASTERY_ATTEMPTS,
    mastery_confidence_min: int = DEFAULT_MASTERY_CONFIDENCE,
    now: datetime | None = None,
) -> bool:
    """Decay an active imposter signal when mastery evidence is strong.

    Mutates `settings` in place and returns whether a mutation happened.
    Persistence is owned by the caller (typically `_save_user_settings`).
    """
    signal = settings.get("imposter_signal")
    if not isinstance(signal, dict):
        return False

    state = str(signal.get("state") or "none")
    if state == "none":
        return False

    mastery_hits = sum(
        1
        for attempt in attempts
        if _attempt_hits_mastery(
            attempt,
            mastery_confidence_min=mastery_confidence_min,
        )
    )
    if mastery_hits < mastery_attempts_required:
        return False

    next_signal = dict(signal)
    next_signal["state"] = "none"
    decay_time = now or datetime.utcnow()
    next_signal["decayed_at"] = decay_time.isoformat()
    settings["imposter_signal"] = next_signal
    return True
