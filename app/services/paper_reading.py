"""Multi-pass paper reading (Andrew Ng's method, Stanford CS230).

The method, faithfully: you do not read a paper front-to-back once. You
make several passes, each with a different job, and you decide after the
first one whether the paper deserves the rest of your attention. Most
papers should not — that judgement is the efficiency, not a failure.

    pass 1  title, abstract, figures            → is this relevant to me
    pass 2  intro, conclusion, figures, scan    → what did they claim
    pass 3  the whole thing, skipping the maths → how does it work
    pass 4  the maths and the unfamiliar terms  → only when going deep

On top of Ng's four questions this adds the operator's four dimensions —
content, methods, research taste, findings — revealed per pass, so a
pass-3 question never lands during pass 1.

WHY A FIXED QUESTION SPINE, not per-paper generated questions: the same
questions on every paper are the point. Reuse is the mechanism (the
subgoal-labelling result — a label set transfers only if it is the same
label set), it costs no tokens, and it works with no API key and under a
spend cap. The questions are prompts, never a quiz.

NO GRADING. `recitation.py` states this as product law for the bench:
"the operator disengages the moment he feels judged, so a discouraging
grader is worse than none." Nothing here scores an answer, counts
answered-vs-total as a percentage, or treats a blank as a failure. The
only consequence of leaving something blank is that it is still blank.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

# Detection: what counts as a paper. Book chapters and blog posts have no
# abstract and no figures, so the ladder would be a lie on them.
_PAPER_URL = re.compile(
    r"(arxiv\.org|doi\.org|/doi/|papers\.nips\.cc|openreview\.net|aclanthology\.org|"
    r"proceedings\.mlr\.press|dl\.acm\.org|biorxiv\.org|semanticscholar\.org)",
    re.I,
)

VERDICTS = ("relevant", "park", "drop")
MAX_PASS = 4


@dataclass(frozen=True)
class Question:
    key: str
    dimension: str  # content | methods | taste | findings
    prompt: str
    hint: str = ""


@dataclass(frozen=True)
class Pass:
    number: int
    label: str
    read: str          # what to actually read in this pass
    purpose: str
    questions: tuple[Question, ...]


PASSES: tuple[Pass, ...] = (
    Pass(
        number=1,
        label="Orient",
        read="Title, abstract, figures. Nothing else.",
        purpose="Decide whether this paper deserves the rest of your attention.",
        questions=(
            Question(
                "content.predict", "content",
                "From the title, abstract and figures alone — what do you think this claims?",
                "Commit before you read on. Being wrong here is useful; it is the "
                "cheapest place to find out your prior was off.",
            ),
            Question(
                "findings.relevance", "findings",
                "Is this relevant to what you are actually working on, and why?",
                "Most papers are not. Saying so and parking it is the point of "
                "pass 1, not a failure to finish.",
            ),
        ),
    ),
    Pass(
        number=2,
        label="Claim",
        read="Introduction, conclusion, the figures again, then scan the rest.",
        purpose="Get the claim and the headline result without the machinery.",
        questions=(
            Question(
                "content.aim", "content",
                "What did the authors set out to do, and what do they say they achieved?",
            ),
            Question(
                "findings.citable", "findings",
                "Which single result would you actually cite?",
                "If nothing here is citable, that is a finding about the paper.",
            ),
            Question(
                "findings.useful", "findings",
                "What in this is useful to you, specifically?",
            ),
        ),
    ),
    Pass(
        number=3,
        label="Mechanism",
        read="The whole paper. Skip maths and terminology you do not know yet.",
        purpose="Understand how it works and whether the evidence carries the claim.",
        questions=(
            Question(
                "methods.measurement", "methods",
                "What is the actual measurement, and what would have to be true for "
                "that evidence to support that claim?",
            ),
            Question(
                "methods.control", "methods",
                "What is the baseline or control, and is the comparison fair?",
                "A missing control is the most common reason a strong-sounding "
                "result does not survive contact.",
            ),
            Question(
                "taste.why_now", "taste",
                "Why was this problem worth a paper, and what made it tractable now?",
            ),
            Question(
                "taste.not_done", "taste",
                "What did they choose NOT to do, and do you think that was wise?",
            ),
            Question(
                "taste.change_mind", "taste",
                "What would change your mind about the conclusion?",
                "If nothing would, you are reading it as a fact rather than a claim.",
            ),
        ),
    ),
    Pass(
        number=4,
        label="Depth",
        read="The maths, the derivations, the terms you skipped.",
        purpose="Only for papers you intend to build on or argue with.",
        questions=(
            Question(
                "methods.load_bearing", "methods",
                "Which step of the derivation is doing the real work?",
            ),
            Question(
                "findings.references", "findings",
                "Which references do you now want to follow, and why those?",
            ),
        ),
    ),
)

DIMENSIONS = {
    "content": "Content — what it says",
    "methods": "Methods — how they know",
    "taste": "Research taste — why this, why now",
    "findings": "Findings — what changes for you",
}


def is_paper(url: str | None, source: str | None = None, kind: str | None = None) -> bool:
    """True when the multi-pass ladder actually applies.

    Conservative on purpose: a Rust Book chapter has no abstract and no
    figures, so offering it a four-pass ladder would be theatre.
    """
    if kind and kind not in ("reading", "paper"):
        return False
    if url and _PAPER_URL.search(url):
        return True
    # An explicit frontmatter opt-in for papers hosted somewhere odd.
    return bool(source and "arxiv" in source.lower())


def pass_at(number: int) -> Pass | None:
    for p in PASSES:
        if p.number == number:
            return p
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_pass(state: dict | None) -> int:
    """Furthest pass reached. 0 = not started."""
    try:
        return max(0, min(MAX_PASS, int((state or {}).get("pass", 0))))
    except (TypeError, ValueError):
        return 0


def advance(state: dict | None, to_pass: int) -> dict:
    """Record that a pass was completed. Idempotent and monotonic — a
    re-click cannot walk the ladder backwards, and re-reading pass 2
    after pass 3 does not demote you."""
    out = dict(state or {})
    target = max(1, min(MAX_PASS, int(to_pass)))
    passes = dict(out.get("passes") or {})
    passes.setdefault(str(target), _now_iso())
    out["passes"] = passes
    out["pass"] = max(current_pass(out), target)
    return out


def set_verdict(state: dict | None, verdict: str) -> dict:
    if verdict not in VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r}")
    out = dict(state or {})
    out["verdict"] = verdict
    out["verdict_at"] = _now_iso()
    return out


def save_answers(state: dict | None, answers: dict[str, str]) -> dict:
    """Merge answers in. Blank values delete rather than store empties,
    so 'answered' means something."""
    out = dict(state or {})
    merged = dict(out.get("answers") or {})
    valid = {q.key for p in PASSES for q in p.questions}
    for key, value in (answers or {}).items():
        if key not in valid:
            continue
        text = (value or "").strip()
        if text:
            merged[key] = text[:4000]
        else:
            merged.pop(key, None)
    out["answers"] = merged
    return out


def answered_keys(state: dict | None) -> set[str]:
    return set((state or {}).get("answers") or {})


def visible_passes(state: dict | None) -> list[dict]:
    """The ladder to render.

    A pass is `open` when its predecessor is done. Questions from later
    passes are not shown early — asking "what is the baseline" during
    pass 1 trains skimming for an answer rather than reading.
    """
    reached = current_pass(state)
    stamps = (state or {}).get("passes") or {}
    answers = answered_keys(state)
    out = []
    for p in PASSES:
        out.append({
            "pass": p,
            "done": p.number <= reached,
            "open": p.number <= reached + 1,
            "completed_at": stamps.get(str(p.number)),
            "answered": sum(1 for q in p.questions if q.key in answers),
        })
    return out


def is_deep_read(state: dict | None) -> bool:
    """Reached the mechanism pass AND left something behind in writing.

    This is the bar for offering to file the read as evidence on
    /signal — a pass counter alone is not evidence of anything.
    """
    if current_pass(state) < 3:
        return False
    answers = answered_keys(state)
    pass3 = {q.key for q in (pass_at(3).questions if pass_at(3) else ())}
    return bool(answers & pass3)
