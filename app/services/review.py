"""LLM-graded review of a single attempt.

Reads the user's Engineering Method phase notes + final code +
reference solution + test result and returns a structured per-phase
critique. The model is asked for a *specific* strength, a *specific*
gap, and an *open* question for each phase the user engaged with.

Sycophancy is the design enemy here. The system prompt says so
explicitly, and the user's capstone is on sycophancy detection — they
will notice quickly if reviews are vague or congratulatory.

If ANTHROPIC_API_KEY isn't set, returns a "skipped" record so the UI
can render a small note instead of a review.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from ..models import EM_PHASES, Attempt, Problem


_DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")


_SYSTEM_PROMPT_PRACTICE = """You are a senior research engineering
interviewer reviewing a candidate's *practice* attempt at a problem.
The candidate works through problems using a five-phase Engineering
Method: Explore, Brainstorm, Plan, Implement (the code), Verify. They
captured notes in each visible phase.

Your output must be JSON ONLY in this exact shape:

{
  "summary": "2-3 sentence overall read of the attempt",
  "per_phase": {
    "<phase>": {
      "strength": "one specific thing they did well",
      "gap": "one specific thing one level up",
      "question": "an open question for them to sit with"
    },
    ...
  },
  "overall_score": <float 0..1 — your confidence they would pass a
    similar problem in an interview setting>
}

Rules:

1. Include a phase ONLY if the candidate engaged with it (has notes,
   OR is Implement and submitted code).
2. Be SPECIFIC. Cite their actual content. "Good Plan" is not a
   strength; "you named the invariant about axis discipline before
   writing code" is.
3. Do not be sycophantic. If notes are thin, say so directly. If the
   code is buggy, name the specific bug, not "could be improved."
4. Questions should be open-ended — they deepen understanding, they
   are not graded.
5. Calibrate overall_score against the bar for the role they're
   targeting (research engineering at frontier labs / safety orgs /
   fellowships). 1.0 means "I would pass them." 0.5 means "borderline
   in a real interview." Below 0.3 means clear gaps.
"""


_SYSTEM_PROMPT_INTERVIEW = """You are evaluating a candidate's
*mock interview* performance on a research-engineering problem. They
worked the problem under timed conditions with no aids — no
reference solution, no pitfalls panel, no docs links. They captured
notes in the same five-phase Engineering Method (Explore, Brainstorm,
Plan, Implement, Verify).

Beyond per-phase critique, you grade against the Algo Interviews
rubric. The signals interviewers actually score on:

1. assumption_clarification — did the candidate restate the problem
   and confirm I/O contract? (Explore.)
2. multiple_approaches — did they consider 2-3 candidates with
   trade-offs before committing? (Brainstorm.)
3. complexity_stated — did they state time/space complexity for
   their chosen approach? (Brainstorm or Plan.)
4. plan_before_code — did they outline the algorithm before writing
   code? (Plan.)
5. code_quality — clean naming, no premature cleverness, readable.
6. verification — did they probe edge cases beyond the provided
   tests? (Verify.)

Your output must be JSON ONLY in this exact shape:

{
  "summary": "2-3 sentence overall read",
  "per_phase": {
    "<phase>": {
      "strength": "one specific thing they did well",
      "gap": "one specific thing one level up",
      "question": "an open question for them to sit with"
    },
    ...
  },
  "overall_score": <float 0..1 — your confidence they would pass this
    problem in a real interview at the target bar>,
  "rubric_signals": {
    "assumption_clarification": "yes" | "partial" | "no",
    "multiple_approaches":      "yes" | "partial" | "no",
    "complexity_stated":        "yes" | "partial" | "no",
    "plan_before_code":         "yes" | "partial" | "no",
    "code_quality":             "strong" | "ok" | "weak",
    "verification":             "yes" | "partial" | "no"
  }
}

Rules:

1. Be SPECIFIC. Cite their actual content.
2. Do not be sycophantic. If notes are thin, say so. If code is
   buggy, name the bug.
3. Interview mode is stricter than practice — be harder on
   "would I pass them" calibration. Missing assumption checks and
   absent complexity statements are real costs.
4. The "question" is for their own reflection — open-ended, not
   graded.
"""


_RUBRIC_KEYS = {
    "assumption_clarification",
    "multiple_approaches",
    "complexity_stated",
    "plan_before_code",
    "code_quality",
    "verification",
}


def _build_user_message(problem: Problem, attempt: Attempt, reference_solution: str | None) -> str:
    parts = []
    parts.append(f"# Problem: {problem.title}")
    parts.append(f"Type: {problem.problem_type} · Difficulty: {problem.difficulty} · Time bucket: {problem.time_bucket} min")
    if problem.content_md:
        parts.append("\n## Prompt\n" + problem.content_md)
    if reference_solution:
        parts.append("\n## Reference solution (for your reference, do not show to candidate)\n```\n" + reference_solution + "\n```")

    parts.append("\n## Candidate's phase notes\n")
    for phase, content in (
        ("explore", attempt.explore_notes),
        ("brainstorm", attempt.brainstorm_notes),
        ("plan", attempt.plan_notes),
        ("verify", attempt.verify_notes),
    ):
        if content and content.strip():
            parts.append(f"### {phase}\n{content.strip()}\n")
        else:
            parts.append(f"### {phase}\n_(empty)_\n")

    if attempt.final_code:
        parts.append("\n## Candidate's submitted code\n```\n" + attempt.final_code + "\n```")

    parts.append(f"\n## Test result\n{'PASS' if attempt.test_passed else 'FAIL'}")
    if attempt.test_output:
        parts.append("```\n" + attempt.test_output[-2000:] + "\n```")
    if attempt.looked_at_solution:
        parts.append("\nNote: the candidate looked at the reference solution before submitting.")
    if attempt.confidence_1_to_5 is not None:
        parts.append(f"\nCandidate's self-reported post-attempt confidence: {attempt.confidence_1_to_5}/5")

    return "\n".join(parts)


def review_attempt(
    problem: Problem,
    attempt: Attempt,
    *,
    voice_key: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Return a structured review dict. Keys:
        method:        "claude" | "skipped"
        model_used:    str | None
        summary_md:    str | None
        per_phase:     dict[phase -> {strength, gap, question}]
        overall_score: float | None
        error_text:    str | None
        rubric_signals: dict[str, str] | None  -- populated for interview-mode
        voice_key:     str  -- which voice was used (default if unspecified)

    The `voice_key` parameter selects a named-thinker persona from
    app/services/voices.py to prepend to the system prompt. The default
    voice contributes nothing — existing behavior is preserved when
    callers don't pass voice_key.

    `user_id` feeds the spend-cap gate: if the user is over their daily
    Anthropic budget, return the skipped shape (same as no-API-key) so
    the UI handles it transparently.
    """
    from . import spend_cap

    skipped = {
        "method": "skipped",
        "model_used": None,
        "summary_md": None,
        "per_phase": {},
        "overall_score": None,
        "error_text": None,
        "rubric_signals": None,
        "voice_key": "default",
    }
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {**skipped, "error_text": "ANTHROPIC_API_KEY not set — review skipped."}
    if spend_cap.over_cap_for(user_id, "review"):
        return {**skipped, "error_text": "Daily Anthropic spend cap reached — review skipped."}

    from . import voices as voices_service
    voice = voices_service.get(voice_key)
    base_system = _SYSTEM_PROMPT_INTERVIEW if attempt.interview_mode else _SYSTEM_PROMPT_PRACTICE
    system = voices_service.apply_persona(base_system, voice)

    try:
        from . import llm_keys
        client = llm_keys.client_for(user_id)
        user_msg = _build_user_message(problem, attempt, problem.reference_solution_python)
        if attempt.interview_mode:
            user_msg = "INTERVIEW MODE — timed, no aids.\n\n" + user_msg
        resp = client.messages.create(
            model=_DEFAULT_MODEL,
            max_tokens=2200,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        spend_cap.record_usage_for(user_id, resp, service="review")
        body = "".join(b.text for b in resp.content if hasattr(b, "text"))
        m = re.search(r"\{.*\}", body, re.DOTALL)
        if not m:
            raise ValueError("no JSON in Claude response")
        parsed = json.loads(m.group(0))

        # Sanitize per_phase
        per_phase_raw = parsed.get("per_phase", {})
        per_phase: dict[str, dict[str, str]] = {}
        for ph in EM_PHASES:
            entry = per_phase_raw.get(ph)
            if isinstance(entry, dict) and entry.get("strength") and entry.get("gap"):
                per_phase[ph] = {
                    "strength": str(entry.get("strength", "")).strip(),
                    "gap": str(entry.get("gap", "")).strip(),
                    "question": str(entry.get("question", "")).strip(),
                }

        # Sanitize rubric_signals (interview-mode only)
        rubric_signals: dict[str, str] | None = None
        if attempt.interview_mode:
            rs_raw = parsed.get("rubric_signals") or {}
            if isinstance(rs_raw, dict):
                rubric_signals = {
                    k: str(rs_raw[k]).strip().lower()
                    for k in _RUBRIC_KEYS
                    if k in rs_raw and isinstance(rs_raw[k], str)
                }

        return {
            "method": "claude",
            "model_used": _DEFAULT_MODEL,
            "summary_md": str(parsed.get("summary", "")).strip() or None,
            "per_phase": per_phase,
            "overall_score": float(parsed.get("overall_score")) if parsed.get("overall_score") is not None else None,
            "error_text": None,
            "rubric_signals": rubric_signals,
            "voice_key": voice.key,
        }
    except Exception as e:
        return {**skipped, "error_text": f"review failed: {e}", "voice_key": voice.key}
