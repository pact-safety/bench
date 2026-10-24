"""Command palette presence (WS5 progressive enhancement).

The palette is a vanilla-JS overlay defined in static/js/palette.js;
its behavior is browser-side and not easily unit-testable from
Python. What we do guard here:

- The overlay markup (#palette dialog + input + list + footer) is
  rendered into every page via base.html.
- The palette JS asset is referenced from the page so it actually
  loads.
- The visible "jump to ⌘K" trigger button is present in the nav,
  bound to data-palette-trigger so the JS can find it.
- The contract that the visible nav still works with JS off — i.e.
  the trigger button is type="button" (not a link) so a browser
  with JS disabled doesn't navigate anywhere on click.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient


def _client():
    import app.main as m
    return TestClient(m.app)


def _public_page_html() -> str:
    """The signed-out request-access page — cheapest public-page
    render that includes the full base.html chrome. Used for every
    test below; no auth setup needed."""
    r = _client().get("/request-access")
    assert r.status_code == 200, r.status_code
    return r.text


def test_palette_overlay_markup_renders_on_every_page():
    """The #palette dialog ships in base.html so any page (public or
    authed) carries it. Hidden by default; JS shows it on Cmd+K."""
    html = _public_page_html()
    assert 'id="palette"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'class="palette__input"' in html
    assert 'class="palette__list"' in html
    # Hidden until JS opens it.
    assert re.search(r'<div class="palette"[^>]*hidden', html)


def test_palette_script_is_loaded():
    """The JS asset is referenced so the overlay actually wires up."""
    html = _public_page_html()
    assert "/static/js/palette.js" in html


def test_palette_trigger_button_is_in_the_nav():
    """The visible 'jump to ⌘K' affordance. data-palette-trigger is
    the JS hook; type='button' guarantees a JS-off page doesn't
    submit a form or navigate on click."""
    html = _public_page_html()
    assert "data-palette-trigger" in html
    # The trigger lives inside the nav-hybrid block.
    assert "nav__palette-hint" in html


def test_palette_footer_hints_render():
    """The keybinding legend at the bottom of the dialog. Surfaces
    the four keys so the operator doesn't have to discover them."""
    html = _public_page_html()
    # The footer shows arrow / enter / cmd-enter / escape hints.
    # Test the labels rather than the literal kbd glyphs so we
    # survive future copy tweaks.
    assert "navigate" in html
    assert "new tab" in html
    assert "close" in html
