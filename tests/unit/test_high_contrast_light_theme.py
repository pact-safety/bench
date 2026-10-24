"""High contrast must work in LIGHT themes too.

The global `html[data-high-contrast="1"]` block hardcoded a dark-theme
ramp (white text, pale borders) from when the bench was dark-only. Once
`hyperbolic` — a light theme with near-white surfaces — shipped, turning
high contrast ON rendered body copy white on near-white and every
textarea white on white. Unreadable for exactly the people who enabled
it.

The fix is indirection, not a theme-scoped component rule (Law 4): each
theme declares its own `--hc-*` ramp and the global block consumes it
with the dark values as fallback.
"""

from __future__ import annotations

import re
from pathlib import Path

CSS = Path("static/css/main.css").read_text()


def _block(selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}", CSS, re.S)
    assert m, f"{selector} block not found"
    return m.group(1)


def test_global_high_contrast_consumes_a_theme_ramp():
    """It must not hardcode text colour any more, or a light theme has no
    way to opt out of white-on-white."""
    body = _block('html[data-high-contrast="1"]')
    assert "var(--hc-text," in body
    assert "var(--hc-text-alt," in body
    assert "var(--hc-border," in body


def test_dark_ramp_survives_as_the_fallback():
    """Removing the fallback would silently un-fix the dark theme."""
    body = _block('html[data-high-contrast="1"]')
    assert "#ffffff" in body.lower(), "dark-theme fallback must remain"


def test_hyperbolic_declares_a_dark_text_ramp():
    body = _block(':root[data-theme="hyperbolic"]')
    assert "--hc-text:" in body
    m = re.search(r"--hc-text:\s*#([0-9a-fA-F]{6})", body)
    assert m, "hyperbolic must declare --hc-text"
    r, g, b = (int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    # Light theme ⇒ high-contrast text must be DARK, not white.
    assert (r + g + b) / 3 < 80, f"--hc-text is too light for a light theme: #{m.group(1)}"


def test_hyperbolic_high_contrast_beats_its_normal_text():
    """High contrast should be strictly more contrast, not merely different."""
    hyper = _block(':root[data-theme="hyperbolic"]')
    hc = re.search(r"--hc-text:\s*#([0-9a-fA-F]{6})", hyper).group(1)
    normal = re.search(r"--text:\s*#([0-9a-fA-F]{6})", hyper).group(1)
    lum = lambda h: sum(int(h[i:i + 2], 16) for i in (0, 2, 4)) / 3
    assert lum(hc) < lum(normal), "high-contrast text must be darker than normal"


def test_no_theme_scoped_component_rule_was_added():
    """Law 4: the fix must be token indirection, not a theme-scoped
    selector carrying component styles."""
    assert 'html[data-theme="hyperbolic"][data-high-contrast' not in CSS
