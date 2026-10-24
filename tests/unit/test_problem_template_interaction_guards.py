"""Regression guards for `/problem` client-side interaction scripts.

Issue #300 tracked two UX bugs in `templates/problem.html`:
1) first hint activation after typing could no-op,
2) rapid double-submit on Run Tests could stack duplicate reviews.

With no browser E2E harness, these tests assert the inline JS contract
that prevents those regressions.
"""

from __future__ import annotations

from pathlib import Path
import re


_TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "problem.html"


def _source() -> str:
    return _TEMPLATE.read_text(encoding="utf-8")


def test_hint_trigger_prefers_pointerdown_with_click_keyboard_fallback():
    """Issue #300: first pointer activation must not be lost after typing.

    Contract:
    - pointer devices trigger hint requests on `pointerdown`
    - click path remains as fallback for keyboard activation and
      non-PointerEvent browsers.
    """
    body = _source()

    assert 'var supportsPointerEvents = typeof window.PointerEvent === "function";' in body
    assert 'btn.addEventListener("pointerdown", function (evt) {' in body
    assert "if (evt.button !== 0) return;" in body
    assert 'btn.addEventListener("click", function (evt) {' in body
    assert "if (supportsPointerEvents && evt.detail > 0) return;" in body


def test_solve_form_blocks_second_submit_while_request_in_flight():
    """Issue #300: rapid double-click should suppress duplicate submit.

    We require an explicit in-flight gate on form submit (capture phase)
    plus reset hooks once the HTMX request completes/errors.
    """
    body = _source()

    assert "var submitInFlight = false;" in body

    submit_guard = re.compile(
        r"form\.addEventListener\(\"submit\", function \(evt\) \{"
        r".*?if \(submitInFlight\) \{"
        r".*?evt\.preventDefault\(\);"
        r".*?evt\.stopImmediatePropagation\(\);"
        r".*?return;"
        r".*?\}"
        r".*?submitInFlight = true;"
        r".*?\}, true\);",
        re.DOTALL,
    )
    assert submit_guard.search(body)

    assert 'form.addEventListener("htmx:afterRequest", clearSubmitGuard);' in body
    assert 'form.addEventListener("htmx:responseError", clearSubmitGuard);' in body
    assert 'form.addEventListener("htmx:sendError", clearSubmitGuard);' in body
    assert 'form.addEventListener("htmx:timeout", clearSubmitGuard);' in body
