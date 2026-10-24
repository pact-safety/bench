"""Weekly Hamming-mode reflection.

Pulls the last N days of the user's activity (attempts, content
completions + ratings + reflections, writings, hint-ladder usage,
feedback) and asks Claude to write a SHORT Hamming-style prompt set
the user replies to in writing.

The framing is the title essay's three core questions, adapted for
research-engineering practice:
- What are you avoiding?
- What's compounding (skill / lazy habit / blocked tooling)?
- What's the biggest problem in your stack right now — and are you
  working on it?

Claude returns 3-5 prompts tailored to the actual data, plus a
one-line summary. Anti-sycophancy: the prompt is explicit that
generic "keep up the great work" is the failure mode.

LLM-skipped fallback: a generic 3-question Hamming set so the page
still works offline.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..models import Attempt, ContentItem, Problem


# Default to Haiku 4.5 for Reflect. The task is templated generative work
# — pick 4-5 short prompts + write a one-line summary from a JSON week
# summary. Sonnet's reasoning isn't earning its 15-25s latency for the
# user-visible "Generate reflection" wait. Operator can override via
# ANTHROPIC_HAMMING_MODEL if a future change reintroduces Sonnet-shaped
# reasoning to the prompt (e.g., axes inference, calibration analysis).
_DEFAULT_MODEL = os.environ.get("ANTHROPIC_HAMMING_MODEL", os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"))


_FALLBACK_PROMPTS: list[dict[str, str]] = [
    {
        "label": "Avoiding",
        "prompt": (
            "What did you reach for the reference solution / hint on this "
            "week? What pattern shows up across those problems — and is it "
            "the actual blocker, or a proxy for something deeper?"
        ),
    },
    {
        "label": "Compounding",
        "prompt": (
            "Pick one skill axis where you moved this week (positive OR "
            "negative). What was the smallest action that produced the "
            "movement? Can you set up to do that action again next week?"
        ),
    },
    {
        "label": "Biggest problem",
        "prompt": (
            "If you had to point at the single biggest gap between you and "
            "passing a research-engineering interview at the bar you want, "
            "what would you name? Are you spending time on it this week?"
        ),
    },
    {
        # Calibration check. Imposter-syndrome sub-issue F (see
        # docs/architecture/imposter-syndrome.md and the Moore & Healy
        # (2008) work on prediction-vs-outcome recalibration). The
        # design doc explicitly notes this prompt STAYS in the rotation
        # even after the imposter signal decays — calibration is a
        # permanent skill, not a remediation.
        "label": "Calibration",
        "prompt": (
            "Pick one problem from this past week. Before the answer was "
            "revealed, what did you predict — would you solve it, and how "
            "long would it take? What actually happened? What's the gap "
            "between your prediction and the outcome?"
        ),
    },
]
_FALLBACK_SUMMARY = (
    "Fallback prompt set (Claude unavailable). Hamming's three plus a "
    "calibration check: what are you avoiding, what's compounding, "
    "what's the biggest problem you're not working on, and where's "
    "the gap between what you predicted and what actually happened?"
)


@dataclass
class WeekSummary:
    """Shape passed to Claude. Also useful in the page header so the
    user can see what data the prompts were generated against."""
    attempts: int
    attempts_passed: int
    attempts_with_hints: int
    attempts_with_lookup: int
    avg_confidence: float | None
    weakest_axes: list[tuple[str, float]]   # (axis, pass_rate)
    strongest_axes: list[tuple[str, float]]
    content_finished: int
    content_highly_rated: list[str]         # titles rated >=4
    content_low_rated: list[str]            # titles rated <=2
    hint_phases: Counter                    # phase -> count
    writings_drafted: int
    writings_published: int
    feedback_opened: int
    # External readings the user captured via /library/add this week.
    # Each entry is "Title — notes excerpt (max ~200 chars)". This is
    # the most reflection-fuel-dense signal we have, because the user
    # *chose* to capture these and wrote about them — gives Claude
    # something concrete to reference.
    external_readings: list[str] = field(default_factory=list)


def summarize_week(
    *,
    attempts: list[Attempt],
    problem_by_id: dict[int, Problem],
    content_progress: list[dict[str, Any]],
    writings_count_by_status: dict[str, int],
    feedback_opened_count: int,
    external_readings: list[str] | None = None,
) -> WeekSummary:
    passed = sum(1 for a in attempts if a.test_passed)
    with_hints = sum(1 for a in attempts if a.hints_used)
    with_lookup = sum(1 for a in attempts if a.looked_at_solution)

    confidences = [a.confidence_1_to_5 for a in attempts if a.confidence_1_to_5 is not None]
    avg_conf = (sum(confidences) / len(confidences)) if confidences else None

    # Axis pass rate from attempts (uses problem.domain_tags + structural).
    axis_pass: dict[str, list[bool]] = {}
    for a in attempts:
        p = problem_by_id.get(a.problem_id)
        if not p:
            continue
        for tag in (p.domain_tags or []) + (p.structural_tags or []):
            axis_pass.setdefault(tag, []).append(bool(a.test_passed))
    axis_rates = [
        (tag, sum(passes) / len(passes))
        for tag, passes in axis_pass.items()
        if len(passes) >= 1
    ]
    axis_rates.sort(key=lambda kv: kv[1])
    weakest = axis_rates[:3]
    strongest = list(reversed(axis_rates[-3:]))

    finished = [c for c in content_progress if c.get("status") == "completed"]
    high = [c["title"] for c in content_progress if (c.get("rating_1_to_5") or 0) >= 4]
    low = [c["title"] for c in content_progress if 1 <= (c.get("rating_1_to_5") or 0) <= 2]

    hint_phases: Counter = Counter()
    for a in attempts:
        if a.hints_used:
            for phase, count in a.hints_used.items():
                hint_phases[phase] += count

    return WeekSummary(
        attempts=len(attempts),
        attempts_passed=passed,
        attempts_with_hints=with_hints,
        attempts_with_lookup=with_lookup,
        avg_confidence=avg_conf,
        weakest_axes=weakest,
        strongest_axes=strongest,
        content_finished=len(finished),
        content_highly_rated=high[:5],
        content_low_rated=low[:5],
        hint_phases=hint_phases,
        writings_drafted=writings_count_by_status.get("draft", 0),
        writings_published=writings_count_by_status.get("published", 0),
        feedback_opened=feedback_opened_count,
        external_readings=list(external_readings or []),
    )


_SYSTEM_PROMPT = """You are a Hamming-style coach reviewing one week
of a research engineer's interview-prep practice. Your job is NOT to
cheerlead. Your job is to surface the question they aren't asking
themselves.

You will receive a structured summary of last week's activity:
attempts (pass rate, hint use, axes touched), content consumed (with
their ratings), writings drafted, and feedback they left themselves.

Return JSON ONLY in this exact shape:

{
  "summary": "ONE sentence — what stands out about this week, in
              concrete terms. Cite specific axes or behaviors.
              Example: 'Hints leaned heavily on Implement (4) — and
              the data_pipeline pass rate dropped to 33%.'",
  "prompts": [
    {"label": "Avoiding",        "prompt": "..."},
    {"label": "Compounding",     "prompt": "..."},
    {"label": "Biggest problem", "prompt": "..."},
    {"label": "Calibration",     "prompt": "..."},
    ... (4 to 5 total; the four above are required if data supports
         them, but you can add 1 more if a specific pattern jumps
         out — e.g. 'Sycophancy detection' if the user's content
         engagement skewed strongly that way)
  ]
}

Hard rules:

1. SPECIFIC. Generic prompts like "what are you avoiding?" are bad.
   Use the data: if the user used 4 Implement hints but 0 Explore
   hints, the "Avoiding" prompt should be about whether they're
   skipping the up-front thinking phase.
2. Open-ended. No yes/no questions. The user should have to *write*.
3. No prefacing, no "Here are your prompts." JSON only.
4. If activity is sparse (≤2 attempts), use that as the prompt
   itself: ask why this week was light, what got in the way.
5. NEVER be sycophantic. If they didn't show up, name it.
6. If `external_readings_with_notes` is present, reference at least
   one specific piece by title in your prompts — the user *chose*
   to capture and write about it, so connect this week's practice
   to what they're consuming externally.
7. The "Calibration" prompt is a recurring fixture (Moore & Healy
   2008 prediction-vs-outcome recalibration). Ask the user to pick
   ONE specific problem or content item from this week, what they
   predicted about it BEFORE engaging (would they solve it, how
   long, what tier of solution), and what actually happened. Name
   the problem/item — not generic. The point is to build the habit
   of comparing forecast to outcome, narrowing the gap over time.
"""


def claude_reflection(week: WeekSummary, days: int, user_id: str | None = None) -> dict[str, Any]:
    """Call Sonnet. Raises on any error — caller wraps in try/except.

    `user_id`, when set, feeds the spend-cap shim: a RuntimeError is
    raised if the user is over their daily Anthropic budget, which the
    caller treats the same as any other LLM failure → canned fallback."""
    from . import llm_keys, spend_cap

    if spend_cap.over_cap_for(user_id, "reflect_generate"):
        raise RuntimeError("daily Anthropic cap reached — falling back to canned prompts")
    client = llm_keys.client_for(user_id)
    payload = {
        "window_days": days,
        "attempts": week.attempts,
        "attempts_passed": week.attempts_passed,
        "pass_rate": (week.attempts_passed / week.attempts) if week.attempts else None,
        "attempts_with_hints": week.attempts_with_hints,
        "attempts_with_lookup": week.attempts_with_lookup,
        "avg_confidence_1_to_5": week.avg_confidence,
        "weakest_axes_by_pass_rate": week.weakest_axes,
        "strongest_axes_by_pass_rate": week.strongest_axes,
        "hint_use_by_phase": dict(week.hint_phases),
        "content_finished_count": week.content_finished,
        "content_highly_rated_titles": week.content_highly_rated,
        "content_low_rated_titles": week.content_low_rated,
        "writings_drafted": week.writings_drafted,
        "writings_published": week.writings_published,
        "self_feedback_items_opened": week.feedback_opened,
        # External readings the user captured + wrote notes about. The
        # highest-signal context we have — the user volunteered this.
        # Each entry is "Title — notes excerpt". If absent, key is just
        # omitted to keep the payload tight.
        **({"external_readings_with_notes": week.external_readings} if week.external_readings else {}),
    }
    # Prompt caching: the system prompt is static across every call
    # (~2.4kB). Marking it cacheable cuts TTFT on warm hits and reduces
    # input-token cost. The 5-minute TTL is fine — Reflect generations
    # cluster on Saturday mornings and end-of-day check-ins.
    #
    # max_tokens trimmed from 900 to 500: the output is a small JSON
    # (one-line summary + 4-5 short prompt strings, ~250-350 tokens in
    # practice). 900 was headroom that bought nothing for the median
    # case and only mattered for runaway responses.
    resp = client.messages.create(
        model=_DEFAULT_MODEL,
        max_tokens=500,
        system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "WEEK SUMMARY:\n\n" + json.dumps(payload, indent=2)}],
    )
    spend_cap.record_usage_for(user_id, resp, service="reflect_generate")
    body = "".join(b.text for b in resp.content if hasattr(b, "text"))
    m = re.search(r"\{.*\}", body, re.DOTALL)
    if not m:
        raise ValueError("no JSON in Claude reflection response")
    parsed = json.loads(m.group(0))
    summary = str(parsed.get("summary", "")).strip() or None
    prompts_raw = parsed.get("prompts", [])
    if not isinstance(prompts_raw, list) or not prompts_raw:
        raise ValueError("no prompts in Claude reflection response")
    prompts: list[dict[str, str]] = []
    for entry in prompts_raw[:6]:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "")).strip()[:60]
        prompt = str(entry.get("prompt", "")).strip()
        if not label or not prompt:
            continue
        prompts.append({"label": label, "prompt": prompt})
    if not prompts:
        raise ValueError("no usable prompts in Claude response")
    return {
        "summary": summary,
        "prompts": prompts,
        "method": "claude",
        "model_used": _DEFAULT_MODEL,
    }


def generate(week: WeekSummary, *, days: int = 7, user_id: str | None = None) -> dict[str, Any]:
    """Public entry. Returns the shape persisted to `reflections`.
    Falls back to the canned prompt set on any LLM error (including
    spend-cap hits, surfaced as RuntimeError from `claude_reflection`)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return claude_reflection(week, days, user_id=user_id)
        except Exception:
            pass
    return {
        "summary": _FALLBACK_SUMMARY,
        "prompts": list(_FALLBACK_PROMPTS),
        "method": "fallback",
        "model_used": None,
    }
