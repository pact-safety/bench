from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from tests.unit.test_connecting import _contact, _interaction, NOW


def request():
    req = Request({'type':'http', 'method':'GET', 'path':'/connecting/1', 'headers':[]})
    req.state.user_session = SimpleNamespace(user_id='owner-a')
    return req


@pytest.mark.parametrize('has_touch', [False, True])
def test_detail_uses_touchpoint_outside_fifty_note_history(monkeypatch, has_touch):
    import app.main as m
    class FrozenDateTime(datetime):
        @classmethod
        def utcnow(cls):
            return NOW
    monkeypatch.setattr(m, 'datetime', FrozenDateTime)
    monkeypatch.setattr(m.contacts_repo, 'get', Mock(return_value=_contact(1)))
    notes = [_interaction(1, NOW, kind='note') for _ in range(50)]
    monkeypatch.setattr(m.contacts_repo, 'list_interactions_for_contact', Mock(return_value=notes))
    touch = _interaction(1, NOW - timedelta(days=90), direction='inbound') if has_touch else None
    latest = Mock(return_value=touch)
    monkeypatch.setattr(m.contacts_repo, 'latest_interaction_for_contact', latest, raising=False)
    monkeypatch.setattr(m.templates, 'TemplateResponse', lambda req, name, ctx: ctx)
    ctx = m.connecting_detail(request(), 1)
    assert ctx['tier'] == ('cold' if has_touch else 'never')
    assert ctx['days_since'] == (90 if has_touch else None)
    assert ctx['interactions'] == notes
    latest.assert_called_once_with(1, user_id='owner-a')


def test_foreign_detail_stops_before_history_or_touch_queries(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m.contacts_repo, 'get', Mock(return_value=None))
    history, latest = Mock(), Mock()
    monkeypatch.setattr(m.contacts_repo, 'list_interactions_for_contact', history)
    monkeypatch.setattr(m.contacts_repo, 'latest_interaction_for_contact', latest, raising=False)
    with pytest.raises(HTTPException) as exc:
        m.connecting_detail(request(), 1)
    assert exc.value.status_code == 404
    history.assert_not_called()
    latest.assert_not_called()


@pytest.mark.parametrize('missing', [True, False])
def test_invalid_log_returns_http_error_without_name_error(monkeypatch, missing):
    import app.main as m
    monkeypatch.setattr(m.contacts_repo, 'get', Mock(return_value=None if missing else _contact(1)))
    add = Mock(side_effect=ValueError('invalid'))
    monkeypatch.setattr(m.contacts_repo, 'add_interaction', add)
    with pytest.raises(HTTPException) as exc:
        m.connecting_log_interaction(request(), 1, kind='invalid', direction='', occurred_at='', notes='')
    assert exc.value.status_code == (404 if missing else 422)
    if missing:
        add.assert_not_called()
