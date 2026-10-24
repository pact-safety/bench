"""The recitation grader (BEN-135 Part 2/3).

Compares the operator's spoken, from-memory explanation (a Whisper transcript)
against the source text and names — specifically — what he covered, what he
left out, and what he got wrong. It returns structured JSON; the caller feeds
``covered``/``missing`` into recitation_schedule so misses return sooner.

THE GRADING CONSTRAINT (this is the point of the feature, not a preference).
The operator disengages the moment he feels judged, so a discouraging grader is
worse than none. The rules below live in the system prompt AND are re-enforced
here by sanitising the model's output:

  - No score, percentage, grade, letter, or "N of M". Not even computed
    internally — this module never emits a numeric summary field.
  - No praise-as-verdict, no judgment of the person — only of specific claims.
  - A miss's only consequence is that it returns sooner (scheduling, not
    failure). That framing is the caller's; the grader just names the gap.
  - Honest and specific. Vague encouragement is a failure; so is softening a
    real gap. Same anti-sycophancy stance as review.py.

Graceful degradation mirrors review.py: no ANTHROPIC_API_KEY (or spend cap hit)
→ a "skipped" record with the same shape, so the UI shows a note.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

_DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

# Fields the grader is allowed to emit. Anything else the model returns — a
# score, a grade, a percentage — is dropped here so it can never reach the UI.
_ALLOWED = ("covered", "missing", "misstated", "open_question")

_SYSTEM = """You compare a learner's SPOKEN, from-memory explanation (a \
transcript — expect disfluencies and filler) against the SOURCE TEXT they were \
explaining, and report exactly what they covered, left out, and got wrong.

This learner disengages the moment he feels judged, and a grader that \
discourages him is worse than none. These rules are ABSOLUTE:

- NEVER output a score, percentage, grade, letter, or "N of M" count. Do not \
compute one, not even internally. There is no single number that summarises this.
- NEVER praise the person or render a verdict ("great job", "good effort", \
"you're improving"). Judge specific claims, never the learner.
- A missed concept is NOT a failure. Name what was missed and where; do not \
frame it as a shortcoming — its only consequence is that it returns sooner.
- Be honest and SPECIFIC. "You didn't mention that the attention mask is \
applied before the softmax" is exactly right. Vague encouragement is a \
failure, and so is softening a real gap. Name the exact thing, in the text's \
own terms.

Return ONLY a JSON object, no prose around it:
{"covered": ["short noun-phrase concepts he actually explained"],
 "missing": [{"concept": "short noun phrase", "where": "section/heading", \
"prompt": "a question that would have surfaced it"}],
 "misstated": [{"said": "what he claimed", "actually": "what the text says"}],
 "open_question": "one question that pushes past what the text states"}
The "covered" and "missing" concept strings are reused as schedule keys, so \
keep them short and consistent (noun phrases, not sentences)."""

_PRETEST_NOTE = """

PRETEST MODE: he is reciting this BEFORE reading it. Blanking is the EXPECTED, \
normal result and it still improves later retention. Populate "missing" with \
what the text covers so he knows what to attend to — this is a map of the \
territory, not a report card. "covered" will usually be short or empty; that \
is fine and must not be implied to be a shortcoming."""


def _skipped(reason: str) -> dict[str, Any]:
    return {
        "method": "skipped",
        "covered": [],
        "missing": [],
        "misstated": [],
        "open_question": None,
        "error_text": reason,
    }


def _sanitize(parsed: dict[str, Any]) -> dict[str, Any]:
    """Coerce the model's JSON into the allowed shape and DROP anything else
    (notably any score/grade/percentage the model tried to sneak in)."""
    covered = [str(c).strip() for c in (parsed.get("covered") or []) if str(c).strip()]
    missing = []
    for m in parsed.get("missing") or []:
        if isinstance(m, dict) and str(m.get("concept", "")).strip():
            missing.append({
                "concept": str(m["concept"]).strip(),
                "where": str(m.get("where", "")).strip(),
                "prompt": str(m.get("prompt", "")).strip(),
            })
    misstated = []
    for m in parsed.get("misstated") or []:
        if isinstance(m, dict) and str(m.get("said", "")).strip():
            misstated.append({
                "said": str(m["said"]).strip(),
                "actually": str(m.get("actually", "")).strip(),
            })
    oq = parsed.get("open_question")
    return {
        "method": "claude",
        "covered": covered,
        "missing": missing,
        "misstated": misstated,
        "open_question": str(oq).strip() if oq else None,
        "error_text": None,
    }


def grade(
    source_text: str,
    transcript: str,
    *,
    mode: str = "review",
    user_id: str | None = None,
) -> dict[str, Any]:
    """Grade one recitation. ``mode`` is "review" or "pretest". Returns the
    sanitised structured record (never contains a score field)."""
    from . import spend_cap

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _skipped("ANTHROPIC_API_KEY not set — grading skipped.")
    if user_id and spend_cap.over_cap_for(user_id, "review"):
        return _skipped("Daily Anthropic spend cap reached — grading skipped.")

    system = _SYSTEM + (_PRETEST_NOTE if mode == "pretest" else "")
    user_msg = (
        "SOURCE TEXT:\n" + (source_text or "").strip()
        + "\n\n---\n\nHIS SPOKEN EXPLANATION (transcript):\n"
        + (transcript or "").strip()
    )
    try:
        from . import llm_keys

        client = llm_keys.client_for(user_id)
        resp = client.messages.create(
            model=_DEFAULT_MODEL,
            max_tokens=1600,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        spend_cap.record_usage_for(user_id, resp, service="recitation")
        body = "".join(b.text for b in resp.content if hasattr(b, "text"))
        m = re.search(r"\{.*\}", body, re.DOTALL)
        if not m:
            raise ValueError("no JSON in grader response")
        return _sanitize(json.loads(m.group(0)))
    except Exception as e:  # never raise into the request
        return _skipped(f"grading failed: {e}")
