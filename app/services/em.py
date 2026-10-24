"""Engineering Method phase scaffolding.

Each problem gets default phase prompts based on its problem_type and
warmup flag. Problems may override any phase's prompt via the `em:`
frontmatter block. This module provides the resolved per-phase prompts
for a Problem instance.

Phase order is fixed: Explore, Brainstorm, Plan, Implement, Verify.

em_mode semantics:
- "full":    all five phases surfaced (default for core problems)
- "lite":    Brainstorm + Plan hidden (used for short / easy core)
- "bypass":  no EM scaffolding (default for warmups)
"""

from __future__ import annotations

from ..models import EM_PHASES, Problem


# Defaults by problem_type. Each entry is one prompt per phase.
# Implement is intentionally light — the editor + form below already
# carry the "write the code" framing.
_DEFAULTS_BY_TYPE: dict[str, dict[str, str]] = {
    "code_compose": {
        "explore": (
            "Pin the I/O contract: shapes, dtypes, expected output. "
            "What edge cases would matter (empty inputs, degenerate "
            "shapes, numerical overflow)? Write the smallest correct "
            "example you can think of."
        ),
        "brainstorm": (
            "Two or three approaches. For each: rough complexity, "
            "which PyTorch / library primitives you'd reach for, and "
            "the one pitfall most likely to bite. Start with a brute "
            "or naive version; that's often the cleanest reference."
        ),
        "plan": (
            "Outline the implementation a paragraph deep. What's "
            "the invariant the code must preserve? What axis "
            "discipline matters (which dim is reduced, which is "
            "broadcast)? Mention any mask construction, scaling, or "
            "normalization detail. Detailed enough that another "
            "engineer could implement it."
        ),
        "verify": (
            "Beyond the provided tests: what property would you "
            "check? A boundary case the tests don't probe? "
            "What's your minimum hand-traceable input?"
        ),
    },
    "code_debug": {
        "explore": (
            "Restate the symptom and what it ISN'T. What does the "
            "code claim to do? What's the smallest input that "
            "should reproduce the failure?"
        ),
        "brainstorm": (
            "List the candidate bug locations. For each: what "
            "symptom would it produce? Rank by likelihood given "
            "the reported behavior."
        ),
        "plan": (
            "Where do you look first and why? What change do you "
            "expect to make? What's the test that proves the bug "
            "is gone AND that you didn't introduce a regression?"
        ),
        "verify": (
            "Does the fix address the root cause or a symptom? "
            "What's the minimum change that fixes it? Could the "
            "bug recur under a related but different code path?"
        ),
    },
    "code_read": {
        "explore": (
            "Read both implementations end-to-end before judging. "
            "What is each doing line by line? Where do they differ?"
        ),
        "brainstorm": (
            "What's the intent of the operation? Match each line "
            "to the spec. Which line(s) could be wrong?"
        ),
        "plan": (
            "Argue for your choice. What property does the "
            "correct one preserve that the wrong one violates? "
            "How would you demonstrate that gap with a test?"
        ),
        "verify": (
            "Construct the input that exposes the difference. "
            "Predict the output of both implementations on that "
            "input."
        ),
    },
}

# Algo problems use a research-engineer-flavored variant of the
# "Engineering Method for Algo Tasks" prompts (formation.dev).
_ALGO_OVERRIDES: dict[str, str] = {
    "explore": (
        "I/O contract: exact input/output types, size bounds, "
        "value ranges. Build at least one happy-path example and "
        "two edge cases (boundary, empty, degenerate). "
        "All examples become test cases later."
    ),
    "brainstorm": (
        "Multiple approaches. For each, name the data structure "
        "or pattern, estimate time and space complexity, and "
        "identify the key constraint it leverages. Brute-force "
        "first is a feature, not a bug — it gives you the "
        "correctness oracle."
    ),
    "plan": (
        "Step-by-step outline in plain English, not pseudocode. "
        "Loop structure, state variables, invariants, "
        "boundary conditions. Detailed enough that the only "
        "remaining work is translation."
    ),
    "verify": (
        "Walk through your happy-path example mentally. Then the "
        "edge cases. Sanity-check the complexity you claimed."
    ),
}

# Lite mode (Brainstorm + Plan hidden). Auto-applied for 10-min core
# problems and code_read problems where the prompt itself does most of
# the explore work. Manual override via frontmatter possible.
_LITE_TYPES_TIME = {"code_compose"}
_LITE_TIME_THRESHOLD = 10


def _is_algo(problem: Problem) -> bool:
    return any(t in {"algo", "algorithmic"} for t in problem.structural_tags)


def _default_mode(problem: Problem) -> str:
    if problem.is_warmup:
        return "bypass"
    if problem.problem_type in _LITE_TYPES_TIME and problem.time_bucket <= _LITE_TIME_THRESHOLD:
        return "lite"
    return "full"


def resolve_mode(problem: Problem) -> str:
    """em_mode from frontmatter wins; otherwise infer from problem shape."""
    if problem.em_mode and problem.em_mode != "full":
        # Authoring explicitly set it (lite / bypass) — honor it.
        return problem.em_mode
    return _default_mode(problem)


def visible_phases(problem: Problem) -> list[str]:
    mode = resolve_mode(problem)
    if mode == "bypass":
        return []
    if mode == "lite":
        return ["explore", "implement", "verify"]
    return list(EM_PHASES)


def resolve_prompts(problem: Problem) -> dict[str, str]:
    """Per-phase prompt text for the given problem, with frontmatter overrides."""
    base = dict(_DEFAULTS_BY_TYPE.get(problem.problem_type, _DEFAULTS_BY_TYPE["code_compose"]))
    if _is_algo(problem):
        base.update(_ALGO_OVERRIDES)
    # Frontmatter overrides any default.
    for phase, text in (problem.em_prompts or {}).items():
        if text:
            base[phase] = text
    return base
