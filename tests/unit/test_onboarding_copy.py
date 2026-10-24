"""Copy guardrails for onboarding + assessment framing.

Issue #167 shifts these screens to growth/data-oriented language while
keeping quiz mechanics unchanged.
"""

from __future__ import annotations

import re
from pathlib import Path


_TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "templates"


def _read(name: str) -> str:
    return (_TEMPLATE_ROOT / name).read_text(encoding="utf-8")


def test_onboarding_intro_mentions_starting_signal():
    body = _read("onboarding.html")
    assert "collecting a useful starting signal" in body
    assert "does not affect an application outcome" in body


def test_assess_question_uses_yet_framing_and_not_sure_yet_label():
    body = _read("assess_question.html")
    assert "starting snapshot" in body
    assert "Not sure yet" in body


def test_assess_result_uses_first_marker_and_starting_profile_framing():
    body = _read("assess_result.html")
    assert "Your starting profile" in body
    assert "you've laid the first marker" in body
    assert "does not automatically update" in body
    assert "re-measure as you go" not in body


def test_onboarding_templates_avoid_forbidden_terms():
    combined = "\n".join(
        [
            _read("onboarding.html"),
            _read("assess_question.html"),
            _read("assess_result.html"),
        ]
    ).lower()
    assert not re.search(r"\btest\b", combined)
    assert not re.search(r"\bjudgment\b", combined)
    assert not re.search(r"\bverdict\b", combined)
