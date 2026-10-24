"""A local exercise coach that returns only authored reflection questions."""
from __future__ import annotations


STAGES = ("frame", "attempt", "check", "reflect")
STAGE_LABELS = {
    "frame": "Frame the task",
    "attempt": "Describe your attempt",
    "check": "Choose a check",
    "reflect": "Reflect and continue",
}

# No user text, exercise answers, retrieved material, or model output enters
# these replies. The finite response set enforces the no-answer boundary;
# an unconstrained model followed by a text filter could not guarantee it.
_QUESTIONS = {
    "frame": (
        "What are you trying to produce, and which constraints must it satisfy? "
        "How would you restate the goal in your own words?"
    ),
    "attempt": (
        "What have you tried so far? What is your next small move, and what "
        "do you predict you will observe?"
    ),
    "check": (
        "What is the smallest check you can run yourself? Which assumption "
        "does it test, and what result would make you reconsider?"
    ),
    "reflect": (
        "What changed in your understanding after your attempt and check? "
        "What will you try or revisit next, and why?"
    ),
}


def coaching_reply(stage: str, learner_text: str) -> str:
    """Return a fixed stage question without evaluating or echoing learner text."""
    if not isinstance(stage, str) or stage not in _QUESTIONS:
        raise ValueError("Unknown coaching stage.")
    return _QUESTIONS[stage]


def first_prompt() -> str:
    """Return the question shown before the learner starts a conversation."""
    return _QUESTIONS["frame"]
