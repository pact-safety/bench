"""Local reflection guidance; saved answers are not graded or sent anywhere."""

from __future__ import annotations


def review_checkpoint(*, track, section, answers: str, confidence: str,
                      artifact_url: str, user_id: str | None = None, request_ai: bool = False) -> dict:
    """Return an actionable self-review step without external calls."""
    action = {
        "stuck": "Revisit one worked example, then explain the first step without looking. Save the exact point where you get stuck.",
        "uncertain": "Choose the claim you are least sure of. Test it with a small example, then revise your explanation from memory.",
        "clear": "Try a fresh example without your notes, compare it with the checkpoint, and correct any gap before marking it passed.",
    }.get(confidence, "Compare your explanation with the checkpoint and identify one concrete gap to practice.")
    return {
        "summary": "Your answer is saved. This is self-review guidance, not an assessment of correctness.",
        "next_action": action,
        "questions": [f"What evidence in your answer demonstrates this checkpoint: {section.checkpoint or section.title}?"],
        "source": "self_review",
    }
