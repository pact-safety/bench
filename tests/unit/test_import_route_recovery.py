from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlsplit

import asyncio
from starlette.datastructures import UploadFile
from starlette.requests import Request
import io


def request():
    req = Request({'type': 'http', 'method': 'POST', 'path': '/', 'headers': []})
    req.state.user_session = SimpleNamespace(user_id='owner')
    return req


def test_upload_shows_safe_validation_message_without_coarse_quota_gate(monkeypatch):
    import app.main as m
    from app.services import kb_ingest
    error = type('VaultImportError', (ValueError,), {})
    monkeypatch.setattr(kb_ingest, 'VaultImportError', error, raising=False)
    monkeypatch.setattr(m, '_mira_gate', lambda req: None)
    coarse = Mock(return_value='Vault quota reached')
    monkeypatch.setattr(kb_ingest, 'check_quota', coarse)
    monkeypatch.setattr(kb_ingest, 'ingest_zip', Mock(side_effect=error('Expanded archive is too large.')))
    response = m.mira_kb_upload(request(), UploadFile(io.BytesIO(b'zip'), filename='vault.zip'))
    assert parse_qs(urlsplit(response.headers['location']).query)['kb_error'] == ['Expanded archive is too large.']
    coarse.assert_not_called()


def test_unexpected_import_failure_has_retry_guidance_not_bad_zip_claim(monkeypatch):
    import app.main as m
    from app.services import kb_ingest
    monkeypatch.setattr(m, '_mira_gate', lambda req: None)
    monkeypatch.setattr(kb_ingest, 'check_quota', Mock(return_value=None))
    monkeypatch.setattr(kb_ingest, 'ingest_zip', Mock(side_effect=RuntimeError('database secret diagnostic')))
    response = m.mira_kb_upload(request(), UploadFile(io.BytesIO(b'zip'), filename='vault.zip'))
    message = parse_qs(urlsplit(response.headers['location']).query)['kb_error'][0]
    assert 'retry' in message.lower()
    assert 'as a zip' not in message
    assert 'secret' not in message


def test_parse_url_awaits_fetch_and_preserves_provider_owner(monkeypatch):
    import app.main as m
    from app.services import external_capture
    fetch = AsyncMock(return_value={'page_title': 'Example', 'source_text': 'text'})
    parse = Mock(return_value={'title': 'Example', 'source': '', 'axes': [], 'summary_md': ''})
    monkeypatch.setattr(external_capture, 'fetch_body', fetch)
    monkeypatch.setattr(external_capture, 'parse_with_claude', parse)
    # Bypass only the rate-limit decorator; exercise the route's actual async contract.
    route = getattr(m.parse_external_url, '__wrapped__', m.parse_external_url)
    response = asyncio.run(route(request(), url='https://example.org/article'))
    assert response.status_code == 200
    fetch.assert_awaited_once_with('https://example.org/article')
    assert parse.call_args.kwargs['user_id'] == 'owner'


def test_parse_url_http_failure_keeps_manual_entry_and_skips_provider(mock_anthropic, monkeypatch):
    from tests.unit.test_kb_routes import _client, _ADMIN_UUID
    from app.services import external_capture
    client, _ = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    fetch = AsyncMock(return_value=None)
    parse = Mock()
    monkeypatch.setattr(external_capture, 'fetch_body', fetch)
    monkeypatch.setattr(external_capture, 'parse_with_claude', parse)
    response = client.post('/library/add/parse-url', data={'url':'https://example.org/article'})
    assert response.status_code == 200
    assert response.json() == {'ok':False, 'reason':'fetch-failed'}
    fetch.assert_awaited_once()
    parse.assert_not_called()
