"""BEN-142 — hyperfocus mode.

The mode strips the shell, so the thing worth testing hardest is that it
cannot strand anyone: the exit renders, the toggle round-trips, and the
`next` field that feeds a redirect can't be pointed off-site.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as m


@pytest.fixture
def client():
    return TestClient(m.app)


def _html(client, monkeypatch, *, hyperfocus: bool):
    monkeypatch.setattr(
        m, "_user_settings", lambda uid: {"hyperfocus": hyperfocus}, raising=False
    )
    r = client.get("/settings", follow_redirects=False)
    return r


def test_attribute_absent_by_default(client, monkeypatch):
    monkeypatch.setattr(m, "_user_settings", lambda uid: {}, raising=False)
    r = client.get("/login")
    assert 'data-hyperfocus' not in r.text


# --- the redirect guard -----------------------------------------------------

@pytest.mark.parametrize(
    "hostile",
    [
        "//evil.example.com",
        "https://evil.example.com",
        "http://evil.example.com/x",
        "javascript:alert(1)",
        "",
        "settings",
    ],
)
def test_next_cannot_leave_the_site(hostile):
    """The exit button posts `next` so it can return you where you were. A
    form field that feeds a redirect is an open redirect the moment it isn't
    validated."""
    dest = (hostile or "").strip()
    if not dest.startswith("/") or dest.startswith("//"):
        dest = "/settings"
    assert dest.startswith("/"), hostile
    assert not dest.startswith("//"), hostile
    assert "://" not in dest, hostile


@pytest.mark.parametrize("ok", ["/problem/softmax", "/mira", "/", "/aim#stand"])
def test_next_keeps_same_origin_paths(ok):
    dest = ok.strip()
    if not dest.startswith("/") or dest.startswith("//"):
        dest = "/settings"
    assert dest == ok, "a legitimate in-app path must survive the guard"


def test_route_exists_and_is_a_post():
    routes = {
        (r.path, tuple(sorted(r.methods)))
        for r in m.app.routes
        if getattr(r, "path", None) == "/settings/hyperfocus"
    }
    assert routes, "/settings/hyperfocus is not registered"
    methods = set().union(*[set(mm) for _, mm in routes])
    assert "POST" in methods
    assert "GET" not in methods, (
        "a GET toggle would let a link or an <img> flip the user's shell"
    )


def test_hyperfocus_is_not_filed_under_a11y():
    """It is a focus feature, not an accessibility one. Keeping it out of the
    a11y dict means the a11y save handler cannot clobber it."""
    import inspect

    src = inspect.getsource(m.settings_save_hyperfocus)
    assert '"a11y"' not in src
    a11y_src = inspect.getsource(m.settings_save_a11y)
    assert "hyperfocus" not in a11y_src, (
        "saving accessibility settings must not touch the hyperfocus flag"
    )


# --- the exit actually renders ---------------------------------------------

def _render_base(hyperfocus: bool) -> str:
    """Render base.html directly. Going through the app would need a session
    and a DB; the question here is purely template logic."""
    from types import SimpleNamespace

    tmpl = m.templates.env.get_template("base.html")
    request = SimpleNamespace(
        state=SimpleNamespace(
            user_settings={"hyperfocus": hyperfocus},
            user_session=SimpleNamespace(email="x@example.com", user_id="u"),
            is_admin=False,
        ),
        url=SimpleNamespace(path="/problem/softmax"),
    )
    return tmpl.render(request=request, a11y={}, nav_section=None)


def test_exit_control_renders_only_in_hyperfocus():
    on = _render_base(True)
    off = _render_base(False)
    assert "hyperfocus-exit" in on, (
        "a stripped shell with no way out is a trap, not a focus mode"
    )
    assert "hyperfocus-exit" not in off


def test_exit_posts_the_current_path_so_you_land_back_where_you_were():
    html = _render_base(True)
    assert 'name="next" value="/problem/softmax"' in html
    assert 'action="/settings/hyperfocus"' in html
    assert 'name="enabled" value="0"' in html, "the exit must turn it OFF"


def test_attribute_is_stamped_on_html():
    assert 'data-hyperfocus="1"' in _render_base(True)
    assert "data-hyperfocus" not in _render_base(False)
