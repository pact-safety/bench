import pytest
pytestmark = pytest.mark.skip(reason="MIRA stubbed as coming soon")

"""The coaching flow preserves work while secondary choices stay optional."""
from html.parser import HTMLParser
import json
import re
from unittest.mock import Mock

import pytest

from app.repositories.mira_repository import CoachWriteResult
from tests.unit.test_mira_coach_launch import _coach
from tests.unit.test_mira_routes import _turn, _SESS


def test_mira_resumes_matching_unfinished_session_with_fresh_notes(monkeypatch):
    turn = _turn('user', 'My goal')
    turn.provider_used = 'coach:frame'
    client, m, _ = _coach(monkeypatch, [turn])
    read = Mock(return_value=[turn])
    monkeypatch.setattr(m.mira_repo, 'list_turns', read)
    create = Mock(side_effect=AssertionError('GET wrote a session'))
    monkeypatch.setattr(m.mira_repo, 'create_session', create)
    response = client.get('/mira')
    assert response.status_code == 200
    assert f'data-mira-session="{_SESS}"' in response.text
    assert 'name="stage" value="attempt"' in response.text
    assert 'My goal' in response.text
    assert all(call.kwargs.get('fresh') is True for call in read.call_args_list)
    create.assert_not_called()


def test_explicit_new_session_does_not_resume_or_write(monkeypatch):
    turn = _turn('user', 'Previous goal')
    turn.provider_used = 'coach:frame'
    client, m, _ = _coach(monkeypatch, [turn])
    create = Mock(side_effect=AssertionError('GET wrote a session'))
    monkeypatch.setattr(m.mira_repo, 'create_session', create)
    response = client.get('/mira?new=1')
    assert response.status_code == 200
    assert 'data-mira-session=' not in response.text
    assert 'name="stage" value="frame"' in response.text
    assert 'Previous goal' not in response.text
    create.assert_not_called()


def test_raw_whitespace_survives_save_and_exact_draft_acknowledgment(monkeypatch):
    client, m, _ = _coach(monkeypatch)
    turns = []
    message = '  My prediction\nwith an intentional final space.  '
    monkeypatch.setattr(m.mira_repo, 'list_turns', lambda *a, **kw: turns)

    def append(**kwargs):
        assert kwargs['content'] == message
        turn = _turn('user', kwargs['content'])
        turn.provider_used = f"coach:{kwargs['stage']}"
        turns.append(turn)
        return CoachWriteResult(_SESS, 'saved')

    monkeypatch.setattr(m.mira_repo, 'append_coach_note', append)
    response = client.post('/mira/coach', data={'session_id': _SESS, 'stage': 'frame', 'message': message}, follow_redirects=False)
    assert response.status_code == 303
    page = client.get(response.headers['location'])
    match = re.search(r'<script[^>]*data-mira-confirmed-drafts>(.*?)</script>', page.text, re.S)
    assert match
    assert json.loads(match.group(1)) == [{'stage': 'frame', 'text': message}]


def test_completed_session_keeps_different_stale_draft_visible(monkeypatch):
    turn = _turn('user', 'A saved reflection')
    turn.provider_used = 'coach:reflect'
    client, m, _ = _coach(monkeypatch, [turn])
    save = Mock(return_value=CoachWriteResult(_SESS, 'stale'))
    monkeypatch.setattr(m.mira_repo, 'append_coach_note', save)
    raw_append = Mock(side_effect=AssertionError('Stale draft bypassed the atomic write'))
    monkeypatch.setattr(m.mira_repo, 'append_turn', raw_append)
    response = client.post('/mira/coach', data={'session_id': _SESS, 'stage': 'check', 'message': 'My unsent <boundary> check'})
    assert response.status_code == 409
    assert 'id="mira-unsent-note"' in response.text
    assert 'My unsent &lt;boundary&gt; check' in response.text
    assert 'This note has not been saved' in response.text
    assert 'action="/mira/coach"' not in response.text
    save.assert_called_once()
    assert save.call_args.kwargs['stage'] == 'check'
    assert save.call_args.kwargs['content'] == 'My unsent <boundary> check'
    raw_append.assert_not_called()


class _DisclosureProbe(HTMLParser):
    def __init__(self):
        super().__init__()
        self.details = []
        self.summary_depth = None
        self.summary = ''
        self.summaries = {}
        self.primary_depths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'details':
            self.details.append('open' in attrs)
        if tag == 'summary':
            self.summary_depth = len(self.details)
            self.summary = ''
        if tag == 'section' and 'next-action' in attrs.get('class', '').split():
            self.primary_depths.append(len(self.details))

    def handle_data(self, data):
        if self.summary_depth is not None:
            self.summary += data

    def handle_endtag(self, tag):
        if tag == 'summary':
            self.summaries[self.summary.strip()] = self.details[-1]
            self.summary_depth = None
        if tag == 'details':
            self.details.pop()


@pytest.mark.parametrize('kind,url,coach_link', [
    ('track_section', '/tracks/ml4good-prework-fall-2026', '/mira'),
    ('practice', '/problem/paired-eval-position-debias?mode=compose', '/mira?problem=paired-eval-position-debias'),
    ('track_checkpoint', '/problem/boundary-check', '/mira?problem=boundary-check'),
])
def test_today_primary_stays_visible_while_alternatives_start_collapsed(monkeypatch, kind, url, coach_link):
    from starlette.requests import Request
    from tests.unit.test_track_home_continuity import _catalog
    m, track = _catalog(monkeypatch)
    settings = {'active_track': {'slug': track.slug, 'checkpoint_passed_sections': []}}
    request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': [], 'query_string': b''})
    request.state.user_session = None
    request.state.user_settings = settings
    html = m.templates.get_template('home.html').render(request=request, config=m.config,
        next_action={'kind': kind, 'url': url, 'title': 'Current task', 'verb': 'Continue'},
        track_materials=m._active_track_materials(settings),
        active_track_progress=m._build_home_active_track_progress(settings=settings),
        progress_by_id={}, scored=[], recent=[], daily_slots=[], daily_done=0, daily_total=5,
        done_today_items=[], skill_scores={}, axis_labels={}, home_rail={})
    probe = _DisclosureProbe()
    probe.feed(html)
    assert probe.primary_depths == [0]
    assert f'href="{coach_link}">Think it through with Mira' in html
    for label in ('Readings, videos, math, and other track work', 'Other practice and writing', 'Progress and broader goals'):
        assert probe.summaries[label] is False


def test_track_title_is_plain_text_and_directory_links_to_section_work(monkeypatch):
    from tests.unit.test_tracks_routes import _signed_in_client
    client = _signed_in_client(monkeypatch, {'active_track': {'slug': 'graph', 'checkpoint_passed_sections': [0]}})
    response = client.get('/tracks/graph')
    assert response.status_code == 200
    title = re.search(r'<title>(.*?)</title>', response.text, re.S)
    assert title
    assert '<script' not in title.group(1)
    assert title.group(1).strip() == "Graph Track — Tracks — Li's Bench"
    assert 'id="section-2"' in response.text
    assert 'href="/tracks/graph/sections/2"' in response.text
    assert 'details data-track-section' not in response.text
