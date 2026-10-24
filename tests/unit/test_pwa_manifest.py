"""PWA install-surface coverage for BEN-85 phase 1."""

from __future__ import annotations


def _client():
    import app.main as m
    from fastapi.testclient import TestClient

    return TestClient(m.app), m


def test_manifest_endpoint_returns_manifest_media_type():
    """Baseline manifest fields. Name bumped to 'Li's Bench' on the
    2026-05-28 PWA polish so the install-prompt copy matches the
    brand shown everywhere else, then renamed to 'bench' for the
    2026-10-24 public release; short_name stays 'Bench' for the
    dock icon label where space is tight."""
    client, _m = _client()

    response = client.get("/static/manifest.json")

    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("application/manifest+json")

    manifest = response.json()
    assert manifest["name"] == "bench"
    assert manifest["short_name"] == "Bench"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["background_color"] == "#0A0B0D"
    assert manifest["theme_color"] == "#0A0B0D"

    icons = {icon["src"]: icon for icon in manifest["icons"]}
    assert icons["/static/icons/icon-192.png"]["sizes"] == "192x192"
    assert icons["/static/icons/icon-512.png"]["sizes"] == "512x512"
    assert icons["/static/icons/icon-512-maskable.png"]["purpose"] == "maskable"


def test_manifest_has_polish_fields_for_install_prompts():
    """Fields added in the 2026-05-28 polish so the install prompt
    has copy + the dock icon has right-click shortcuts.

    Guards against accidental removal — if a future edit drops
    `id`, `description`, or `shortcuts`, the install experience
    degrades silently and this test catches it."""
    client, _m = _client()
    manifest = client.get("/static/manifest.json").json()

    # `id` stabilises the PWA identity across manifest changes so
    # the browser doesn't re-prompt to install on every tweak.
    assert manifest["id"], "missing id"

    # Install-prompt copy.
    assert "description" in manifest
    assert len(manifest["description"]) > 10

    # Dock-icon right-click shortcuts. Order matches the operator's
    # most-common entry points (the WS3 IA's high-frequency surfaces).
    shortcuts = manifest.get("shortcuts", [])
    assert len(shortcuts) >= 4
    short_urls = {s["url"] for s in shortcuts}
    assert {"/today/next", "/focus", "/connecting", "/reflect"} <= short_urls
    # Each shortcut needs at least one icon for cross-platform support.
    for s in shortcuts:
        assert s.get("icons"), f"shortcut {s.get('name')!r} missing icons"


def test_base_page_includes_required_pwa_and_apple_tags(mock_anthropic):
    client, _m = _client()

    # /about used to be the test page here; it now 301-redirects to
    # libearden.dev (operator review 2026-05-27 — about content lives
    # on the portfolio, not the bench). /login is the next-best
    # public page that renders the same base template.
    response = client.get("/login")

    assert response.status_code == 200
    html = response.text

    # Existing baseline head metadata remains present.
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert '<meta name="color-scheme" content="dark light">' in html

    # New Phase 1 PWA install tags.
    assert '<link rel="manifest" href="/static/manifest.json">' in html
    assert '<link rel="apple-touch-icon" href="/static/icons/icon-180.png">' in html
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in html
    assert '<meta name="apple-mobile-web-app-title" content="Bench">' in html
    assert '<meta name="theme-color" content="#0A0B0D">' in html
