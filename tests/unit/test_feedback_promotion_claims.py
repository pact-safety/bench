"""Promotion ambiguity must never trigger another external create attempt."""
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape
import pytest

from app.services import github_feedback as gh
from tests.unit.test_feedback_promote import _feedback_row, _USER_UUID, _ADMIN_UUID

URL = 'https://github.com/test/repo/issues/9'


@pytest.fixture
def state(monkeypatch):
    monkeypatch.setenv('GITHUB_FEEDBACK_TOKEN', 'test-only')
    monkeypatch.setenv('GITHUB_FEEDBACK_REPO', 'test/repo')
    fb = _feedback_row(fb_id=7, user_id=_USER_UUID)
    repo = SimpleNamespace(claim_promotion=Mock(return_value=True), mark_promoted=Mock(return_value=True), get=Mock(return_value=fb))
    create = Mock(return_value=(URL, 9))
    monkeypatch.setattr(gh, 'create_gh_issue', create)
    return fb, repo, create


def test_missing_configuration_does_not_claim_or_create(state, monkeypatch):
    fb, repo, create = state
    monkeypatch.delenv('GITHUB_FEEDBACK_TOKEN')
    result = gh.promote_feedback(repo, fb, actor_id=_ADMIN_UUID)
    assert result.status == 'unconfigured'
    repo.claim_promotion.assert_not_called()
    create.assert_not_called()


def test_success_claims_before_external_call_and_finalizes_once(state):
    fb, repo, create = state
    events = []
    repo.claim_promotion.side_effect = lambda **kw: events.append('claim') or True
    create.side_effect = lambda **kw: events.append('create') or (URL, 9)
    repo.mark_promoted.side_effect = lambda **kw: events.append('link') or True
    result = gh.promote_feedback(repo, fb, actor_id=_ADMIN_UUID, auto_promoted=True)
    assert result.status == 'linked' and result.issue_url == URL
    assert events == ['claim', 'create', 'link']
    assert '`feedback_id=7`' in create.call_args.kwargs['body']
    assert _USER_UUID not in create.call_args.kwargs['body']


@pytest.mark.parametrize('failure', [None, TimeoutError('unknown network outcome'), (URL, 9)])
def test_ambiguous_create_or_finalize_keeps_claim_and_blocks_retry(state, failure):
    fb, repo, create = state
    def claim(**kw):
        fb.promoted_at = datetime(2026, 9, 25)
        return True
    repo.claim_promotion.side_effect = claim
    if isinstance(failure, Exception):
        create.side_effect = failure
    else:
        create.return_value = failure
    repo.mark_promoted.side_effect = RuntimeError('DB write outcome unknown')
    assert gh.promote_feedback(repo, fb, actor_id=_ADMIN_UUID).status == 'uncertain'
    assert gh.promote_feedback(repo, fb, actor_id=_ADMIN_UUID).status == 'uncertain'
    create.assert_called_once()
    repo.claim_promotion.assert_called_once()


def test_losing_claim_never_creates_an_issue(state):
    fb, repo, create = state
    repo.claim_promotion.return_value = False
    repo.get.return_value = replace(fb, promoted_at=datetime(2026, 9, 25))
    assert gh.promote_feedback(repo, fb, actor_id=_ADMIN_UUID).status == 'uncertain'
    create.assert_not_called()


def test_losing_claim_returns_concurrently_linked_issue(state):
    fb, repo, create = state
    repo.claim_promotion.return_value = False
    repo.get.return_value = replace(fb, gh_issue_url=URL, gh_issue_number=9)
    result = gh.promote_feedback(repo, fb, actor_id=_ADMIN_UUID)
    assert result.status == 'linked' and result.issue_url == URL
    create.assert_not_called()


def test_failed_claim_never_creates_an_issue(state):
    fb, repo, create = state
    repo.claim_promotion.side_effect = RuntimeError('claim unavailable')
    assert gh.promote_feedback(repo, fb, actor_id=_ADMIN_UUID).status == 'unavailable'
    create.assert_not_called()


@pytest.mark.parametrize('url', ['https://github.com/other/repo/issues/9', 'http://github.com/test/repo/issues/9', 'https://github.com/test/repo/issues/9?x=1', 'https://evil.test/test/repo/issues/9'])
def test_reconciliation_rejects_wrong_repo_or_noncanonical_url_without_network(state, monkeypatch, url):
    fb, repo, create = state
    fb.promoted_at = datetime(2026, 9, 25)
    get = Mock()
    monkeypatch.setattr(gh, '_github_request_json', get)
    assert gh.reconcile_feedback(repo, fb, issue_url=url, actor_id=_ADMIN_UUID).status == 'invalid'
    get.assert_not_called()
    create.assert_not_called()
    repo.mark_promoted.assert_not_called()


@pytest.mark.parametrize('document, expected', [
    ({'number': 9, 'html_url': URL, 'body': '`feedback_id=7`'}, 'linked'),
    ({'number': 9, 'html_url': URL, 'body': '`feedback_id=70`'}, 'invalid'),
    ({'number': 9, 'html_url': URL, 'body': '`feedback_id=7`', 'pull_request': {}}, 'invalid'),
    (None, 'unavailable'),
])
def test_reconciliation_only_links_verified_matching_issue(state, monkeypatch, document, expected):
    fb, repo, create = state
    fb.promoted_at = datetime(2026, 9, 25)
    get = Mock(return_value=document)
    monkeypatch.setattr(gh, '_github_request_json', get)
    result = gh.reconcile_feedback(repo, fb, issue_url=URL, actor_id=_ADMIN_UUID)
    assert result.status == expected
    assert get.call_args.kwargs['method'] == 'GET'
    assert get.call_args.kwargs['path'] == '/repos/test/repo/issues/9'
    assert repo.mark_promoted.call_count == (expected == 'linked')
    create.assert_not_called()


def test_uncertain_inbox_has_search_and_reconciliation_but_no_promote_button(state):
    fb, _, _ = state
    fb.promoted_at = datetime(2026, 9, 25)
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '{% block body %}{% endblock %}'}),
        FileSystemLoader(Path(__file__).resolve().parents[2] / 'templates'),
    ]), autoescape=select_autoescape(['html']))
    html = env.get_template('feedback_inbox.html').render(items=[fb], active_status='open',
        tab_statuses=['open'], counts={'open': 1}, attachments_by_fb={}, is_admin=True,
        promotion_search_urls={7: gh.promotion_search_url(7)})
    assert 'outcome is uncertain' in html
    assert '/feedback/7/promote' not in html
    assert '/feedback/7/reconcile' in html
    assert 'https://github.com/test/repo/issues?' in html
    assert 'for="feedback-issue-7"' in html


@pytest.mark.parametrize('result', [('https://evil.test/issues/9', 9), (URL, 10), (URL, True)])
def test_untrusted_create_result_keeps_claim_without_linking(state, result):
    fb, repo, create = state
    create.return_value = result
    assert gh.promote_feedback(repo, fb, actor_id=_ADMIN_UUID).status == 'uncertain'
    repo.mark_promoted.assert_not_called()


def test_invalid_repository_configuration_does_not_claim(state, monkeypatch):
    fb, repo, create = state
    monkeypatch.setenv('GITHUB_FEEDBACK_REPO', 'test/repo?bad=1')
    assert gh.promote_feedback(repo, fb, actor_id=_ADMIN_UUID).status == 'unconfigured'
    repo.claim_promotion.assert_not_called()
    create.assert_not_called()


def test_reconciliation_does_not_mark_unclaimed_feedback(state, monkeypatch):
    fb, repo, create = state
    get = Mock()
    monkeypatch.setattr(gh, '_github_request_json', get)
    assert gh.reconcile_feedback(repo, fb, issue_url=URL, actor_id=_ADMIN_UUID).status == 'invalid'
    get.assert_not_called()
    repo.mark_promoted.assert_not_called()
