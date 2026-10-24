"""Coverage for the public /writing index page."""

from __future__ import annotations


_EXPECTED_TITLES = (
    "Tag vocabulary",
    "Imposter-signal detection and mitigation",
    "Rest days (Saturday + Sunday)",
    "Curriculum tracks (ARENA 3.0 and beyond)",
    "Autonomous coding agents",
)

_EXPECTED_DOCS_URLS = (
    "https://docs.libearden.dev/architecture/tag-vocabulary/",
    "https://docs.libearden.dev/architecture/imposter-syndrome/",
    "https://docs.libearden.dev/architecture/rest-days/",
    "https://docs.libearden.dev/architecture/tracks/",
    "https://docs.libearden.dev/development/agents/",
)


def _client():
    import app.main as m
    from fastapi.testclient import TestClient

    return TestClient(m.app)


def test_get_writing_returns_200():
    client = _client()

    r = client.get("/writing")

    assert r.status_code == 200


def test_get_writing_contains_expected_essay_titles():
    client = _client()

    r = client.get("/writing")

    assert r.status_code == 200
    for title in _EXPECTED_TITLES:
        assert title in r.text


def test_get_writing_contains_expected_docs_urls():
    client = _client()

    r = client.get("/writing")

    assert r.status_code == 200
    for url in _EXPECTED_DOCS_URLS:
        assert f'href="{url}"' in r.text


def test_get_writings_still_requires_auth():
    client = _client()

    r = client.get("/writings", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/login"
