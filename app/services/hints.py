"""Phase-aware hint ladder.

When the user is stuck on a phase, they request a nudge. The hint
service receives the problem prompt, the user's current phase notes
(and code if Implement), and the count of hints already shown this
phase, then returns ONE short non-revealing hint at the appropriate
tier:

    tier 1 (nudge):       a question that redirects attention
    tier 2 (direction):   names the technique or invariant
    tier 3 (scaffolding): close to a code skeleton — final tier

Tier escalates with hint_count_so_far. After tier 3, further requests
return a "you're at the end of the ladder" sentinel so the UI can
suggest looking at the reference solution.

LLM (Haiku) is preferred when ANTHROPIC_API_KEY is set; otherwise a
deterministic per-phase fallback fires. The fallback is intentionally
generic — it nudges process, not problem-specifics, since we don't
have authored hints yet (see ROADMAP v2 §1 for the authored-content
plan).

Anti-sycophancy / anti-spoiler design rules baked into the prompt:
- Don't reveal the answer; nudge toward thinking.
- Don't name the specific technique unless we're at tier 2+.
- Never write code, at any tier. Tier 3 names the algorithmic
  *shape* verbally (e.g. "mask before normalizing") — the candidate
  translates shape into syntax themselves. When literal code is
  needed, the reference-solution disclosure is the escape hatch,
  not the hint ladder.
- One sentence preferred. Two acceptable. Never a paragraph.

Feedback-driven retunes (operator review):
- 2026-05-28 (#17): tier-3 hints were leaking full one-liner code
  despite the "no function names / values / axes" rules. Tightened
  the tier-3 spec to lead with an explicit "no code, no syntax,
  no pseudocode" rule, reworded the escalation rule's "code-shaped
  scaffold" to "verbal scaffold" since the former was being read
  as "produce code that shows the shape."
"""

from __future__ import annotations

import os
import re
from typing import Any

from ..models import EM_PHASES, Problem


_DEFAULT_MODEL = os.environ.get("ANTHROPIC_HINT_MODEL", "claude-haiku-4-5-20251001")

# Tier label, indexed by hint_count_so_far (0 → first hint = tier 1).
_TIERS = ("nudge", "direction", "scaffolding")
MAX_TIER = len(_TIERS)


def tier_for(count_so_far: int) -> int:
    """0-indexed count → 1-indexed tier (1=nudge, 2=direction, 3=scaffolding).
    Capped at MAX_TIER."""
    return min(count_so_far + 1, MAX_TIER)


def is_exhausted(count_so_far: int) -> bool:
    return count_so_far >= MAX_TIER


# Per-phase deterministic fallback hints. These are *process* nudges —
# they don't know anything about the specific problem, so they're
# unhelpful at the scaffolding tier. The fallback only ships tier-1
# style guidance; tier-2/3 require Claude.
_FALLBACK_NUDGES: dict[str, str] = {
    "explore": "Write down the I/O contract in your notes — exact shapes, dtypes, what's invariant. Edge cases too: empty input, single element, max size.",
    "brainstorm": "List 2-3 candidate approaches, even bad ones. Cost each in time/space. The act of comparing usually surfaces which one fits the constraints.",
    "plan": "Before the editor: what's the invariant that holds at every loop iteration? Name it in one sentence. If you can't, your plan isn't ready.",
    "implement": "Stop typing. Reread your Plan section. Are you implementing what it says, or did you drift?",
    "verify": "What's the smallest test that would distinguish your solution from a wrong-looking one? Edge cases: empty, single element, all-same, off-by-one boundary.",
}


def fallback_hint(phase: str, count_so_far: int) -> dict[str, Any]:
    """Returns the shape used by the live endpoint when no API key is
    set. Generic, process-focused; doesn't reveal anything."""
    phase = phase.lower()
    if is_exhausted(count_so_far):
        return {
            "tier": MAX_TIER,
            "tier_label": _TIERS[MAX_TIER - 1],
            "hint": (
                "You're at the end of the hint ladder. Time to look at "
                "the reference solution and trace through *why* it's "
                "shaped the way it is — that's a learning move, not a "
                "shortcut."
            ),
            "method": "fallback",
            "exhausted": True,
        }
    return {
        "tier": tier_for(count_so_far),
        "tier_label": _TIERS[tier_for(count_so_far) - 1],
        "hint": _FALLBACK_NUDGES.get(
            phase,
            "Reread the problem statement. Note one assumption you've been making implicitly — is it actually true?",
        ),
        "method": "fallback",
        "exhausted": False,
    }


_SYSTEM_PROMPT = """You are a senior research-engineering coach giving a
candidate a *non-revealing* hint while they work an interview-style
problem. The candidate follows a five-phase Engineering Method:
Explore, Brainstorm, Plan, Implement, Verify. You are hinting on ONE
phase.

Return JSON ONLY in this exact shape:

{
  "hint": "<one or two sentences, non-revealing per the tier>",
  "tier": <1, 2, or 3>
}

You will receive a `requested_tier` and a `prior_hints` array of
hint strings already shown for this phase. Your job:

1. Set `tier` to match `requested_tier`.
2. Produce a hint that is **strictly more informative** than every
   prior hint AND substantively different in content (not a
   rephrase).
3. Match the tier semantics exactly:

  1 (nudge):       Ask a question OR name a concept to consider.
                   Do NOT name the technique. Do NOT write code.
                   Example: "What's invariant when you transpose?"

  2 (direction):   Name the technique or invariant explicitly. You
                   may say WHAT to do but not HOW to write it.
                   No code. Example: "Mask before softmax, not after."

  3 (scaffolding): NO CODE. NO PSEUDOCODE. NO SYNTAX. Name the
                   HIGH-LEVEL ALGORITHMIC SHAPE in 1-3 short verbal
                   phrases — plain English, the kind of sentence a
                   senior engineer says out loud at a whiteboard
                   before reaching for the marker. The candidate
                   must still translate your verbal shape into
                   syntax themselves; choosing the specific functions,
                   arguments, and axes is THEIR job.

                   Do not produce ANY of the following at this tier:
                   * function names (no "softmax", "matmul", "norm",
                     "log", "exp" — not even as bare words)
                   * special values (no "-inf", "0", "1e-9", "inf")
                   * tensor axes (no "dim=-1", "axis=0", "last dim")
                   * method-call shapes (no "x.method(args)",
                     no "tensor[mask] = …", no fragment that could
                     be pasted into an editor and roughly compile)
                   * keyword syntax (no "softmax(..., dim=-1)")

                   DO name the conceptual operation in plain English.
                   If the candidate needs the literal call signature,
                   refer them to the reference-solution disclosure
                   (gated and tracked as a lookup) — that is the
                   syntax-level escape hatch; the hint ladder is not.

                   Good example: "Mask the blocked positions in the
                   score tensor before normalizing — the candidate
                   still needs to pick the masking method and the
                   normalization axis."

                   Good example: "Run a single forward pass
                   accumulating gradients into the parameters, then
                   step the optimizer — you choose the loss form
                   and reduction."

                   Counter-example (TOO REVEALING — DO NOT do this):
                   "Apply the mask before softmax — fill blocked
                   positions with -inf in the score tensor, then
                   softmax along the last dim." Three giveaways in
                   one sentence: function name (softmax), special
                   value (-inf), and axis (last dim). The candidate
                   is just transcribing words to code; you've
                   skipped the hard part of their work.

                   Counter-example (also too revealing): "Use
                   F.softmax(scores.masked_fill(mask, float('-inf')),
                   dim=-1)." This is a code one-liner — even
                   formatted as a "hint" it crosses into the
                   reference-solution surface.

Hard rules:
- ONE or TWO sentences total. Never a paragraph.
- Never paste the reference solution.
- Never reveal *the* answer — point toward how to think.
- Tier 3 in particular: SHAPE language only, not OPERATION names.
  The candidate's job at tier 3 is to translate "mask before
  normalizing" into specific syntax themselves. The reference-
  solution disclosure is the escape hatch when they need the
  literal code; tier 3 is for someone who needs the algorithmic
  *shape*, not the syntax.
- ESCALATION IS MANDATORY. A tier-2 hint MUST go beyond a tier-1
  hint by naming a concrete technique. A tier-3 hint MUST go beyond
  tier-2 by giving a VERBAL scaffold — the algorithmic shape stated
  in plain English, no code, no syntax, no function names. "Code-
  shaped" or "pseudocode-shaped" is the WRONG framing; the candidate
  should be able to hear the tier-3 hint and still have to think for
  several minutes before they have a working line. Echoing a prior
  hint at a higher tier label is a failure.
- If the candidate's current phase notes are clearly heading in the
  right direction, *confirm* the direction at the named tier instead
  of redirecting. Don't be sycophantic ("great instinct!"); be
  factual ("yes, that invariant is the right one — now think about
  what breaks when n is 1").
- If the candidate's notes show a misconception, gently flag it at
  the named tier without solving.
"""


def claude_hint(
    problem: Problem,
    phase: str,
    current_notes: str,
    code: str | None,
    count_so_far: int,
    prior_hints: list[str] | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """LLM hint path. Raises on any failure; the caller wraps in
    try/except and falls back.

    `prior_hints` is the list of hint texts already shown for this
    phase in this attempt. Passed to Claude so it can escalate
    without repeating itself.

    `user_id`, when set, is passed to the spend-cap hook so the user's
    daily token counter (settings_json.anthropic_today) gets bumped
    after the response lands. None → bookkeeping no-op (tests, jobs)."""
    from . import llm_keys, spend_cap

    requested_tier = tier_for(count_so_far)
    client = llm_keys.client_for(user_id)
    # Trim prior hints defensively — we never want a single hint
    # turn to balloon the context.
    prior = [(h or "").strip()[:600] for h in (prior_hints or []) if h]
    payload = {
        "phase": phase,
        "requested_tier": requested_tier,
        "tier_label": _TIERS[requested_tier - 1],
        "problem_title": problem.title,
        "problem_prompt": (problem.content_md or "")[:4000],
        "problem_type": problem.problem_type,
        "user_phase_notes": (current_notes or "")[:2000],
        # Code only matters if we're hinting on Implement (or Verify).
        "user_code_snippet": (code or "")[:2500] if phase in ("implement", "verify") else None,
        "prior_hints": prior,
        "hints_already_shown_this_phase": count_so_far,
    }
    import json
    resp = client.messages.create(
        model=_DEFAULT_MODEL,
        max_tokens=300,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "HINT REQUEST:\n\n" + json.dumps(payload, indent=2)}],
    )
    spend_cap.record_usage_for(user_id, resp, service="hint")
    body = "".join(b.text for b in resp.content if hasattr(b, "text"))
    m = re.search(r"\{.*\}", body, re.DOTALL)
    if not m:
        raise ValueError("no JSON in Claude hint response")
    parsed = json.loads(m.group(0))
    hint_text = str(parsed.get("hint", "")).strip()
    if not hint_text:
        raise ValueError("empty hint from Claude")
    # The model may disagree with us about tier; trust ours so the UI
    # ladder stays monotone.
    return {
        "tier": requested_tier,
        "tier_label": _TIERS[requested_tier - 1],
        "hint": hint_text,
        "method": "claude",
        "model_used": _DEFAULT_MODEL,
        "exhausted": False,
    }


def get_hint(
    problem: Problem,
    phase: str,
    current_notes: str,
    code: str | None,
    count_so_far: int,
    prior_hints: list[str] | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Public entry. Falls back to deterministic per-phase nudge on any
    LLM error (no API key, network failure, parse error, spend-cap hit).

    `prior_hints` is the array of hint texts already shown for this
    phase. The client tracks them and posts them back each call so
    Claude can escalate without repeating itself.

    `user_id` is passed through to the spend-cap shim — both for the
    pre-call gate (cap reached → use fallback, don't burn API budget)
    and the post-call bookkeeping (record actual tokens used)."""
    from . import spend_cap

    phase = (phase or "").lower()
    if phase not in EM_PHASES:
        # Defensive: phase came from the form, validate before LLM call.
        return {
            "tier": 1,
            "tier_label": _TIERS[0],
            "hint": f"Unknown phase '{phase}'. Pick one of: {', '.join(EM_PHASES)}.",
            "method": "fallback",
            "exhausted": False,
        }
    if is_exhausted(count_so_far):
        return fallback_hint(phase, count_so_far)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return fallback_hint(phase, count_so_far)
    # Spend cap circuit breaker: don't dial the API when the user's
    # over their daily budget. Returns the same fallback shape so the
    # client UI handles it transparently — the user gets a deterministic
    # nudge instead of a "you're out of credits" error.
    if spend_cap.over_cap_for(user_id, "hint"):
        return fallback_hint(phase, count_so_far)
    try:
        return claude_hint(
            problem, phase, current_notes, code, count_so_far,
            prior_hints=prior_hints, user_id=user_id,
        )
    except Exception as e:
        # Surface to Sentry if it's wired so we can actually see why
        # the user is stuck in fallback land. The user-visible result
        # is unchanged.
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
        return fallback_hint(phase, count_so_far)
