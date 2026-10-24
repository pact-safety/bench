from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from starlette.datastructures import UploadFile

from app import mcp_server


def _mcp_builder(monkeypatch, allowed, *, token='test-token', owner=None):
    import app.main as m
    from app.services import access
    monkeypatch.delenv('LIS_SKIP_STARTUP_LOAD', raising=False)
    monkeypatch.setenv('BENCH_MCP_ENABLED', '1')
    monkeypatch.setenv('BENCH_MCP_TOKEN', token)
    if owner is None:
        monkeypatch.delenv('BENCH_MCP_USER_ID', raising=False)
    else:
        monkeypatch.setenv('BENCH_MCP_USER_ID', owner)
    monkeypatch.setattr(access, 'allowed_user_ids', lambda: set(allowed))
    build = Mock(return_value=object())
    monkeypatch.setattr(mcp_server, 'build_mcp_server', build)
    return m, build


def test_mcp_will_not_mount_without_token(monkeypatch):
    m, build = _mcp_builder(monkeypatch, {'a'}, token='')
    assert m._build_mcp_server_or_none() == (None, None)
    build.assert_not_called()


def test_mcp_rejects_ambiguous_account_configuration(monkeypatch):
    m, build = _mcp_builder(monkeypatch, {'a', 'b'})
    assert m._build_mcp_server_or_none() == (None, None)
    build.assert_not_called()


def test_mcp_explicit_owner_is_validated_and_stable(monkeypatch):
    m, build = _mcp_builder(monkeypatch, {'a', 'b'}, owner='b')
    assert m._build_mcp_server_or_none()[0] is build.return_value
    assert build.call_args.kwargs['user_id'] == 'b'
    monkeypatch.setenv('BENCH_MCP_USER_ID', 'outsider')
    build.reset_mock()
    assert m._build_mcp_server_or_none() == (None, None)
    build.assert_not_called()


def test_mcp_single_allowed_account_remains_compatible(monkeypatch):
    m, build = _mcp_builder(monkeypatch, {'a'})
    assert m._build_mcp_server_or_none()[0] is build.return_value
    assert build.call_args.kwargs['user_id'] == 'a'


def test_mcp_middleware_missing_configuration_cannot_dispatch():
    sent = []
    inner = Mock()
    async def send(message):
        sent.append(message)
    middleware = mcp_server._BearerTokenMiddleware(inner, token=None)
    asyncio.run(middleware({'type': 'http', 'headers': []}, None, send))
    inner.assert_not_called()
    assert sent[0]['status'] == 503


@pytest.mark.parametrize('filename', ['../outside.txt', '<absolute>', r'..\outside.txt', '..', 'bad\x00name.txt'])
def test_credential_filename_cannot_control_destination(monkeypatch, tmp_path, filename):
    import app.main as m
    if filename == '<absolute>':
        filename = str(tmp_path / 'outside.txt')
    monkeypatch.setattr(m, 'REPO_ROOT', tmp_path)
    start = Mock(return_value=17)
    monkeypatch.setattr(m.credentials_repo, 'start_run', start)
    monkeypatch.setattr(m.credentials_repo, 'record_file', Mock())
    monkeypatch.setattr(m.credentials_repo, 'complete_run', Mock())
    monkeypatch.setattr(m.credentials_service, 'extract_text', Mock(return_value='text'))
    request = SimpleNamespace(state=SimpleNamespace(user_session=SimpleNamespace(user_id='owner')))
    response = asyncio.run(m.credentials_upload(request, UploadFile(BytesIO(b'payload'), filename=filename)))
    assert response.status_code == 400
    start.assert_not_called()
    assert not (tmp_path / 'data').exists()


def test_credential_keeps_display_name_but_uses_server_filename(monkeypatch, tmp_path):
    import app.main as m
    monkeypatch.setattr(m, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(m.credentials_repo, 'start_run', Mock(return_value=17))
    record = Mock()
    monkeypatch.setattr(m.credentials_repo, 'record_file', record)
    monkeypatch.setattr(m.credentials_repo, 'complete_run', Mock())
    monkeypatch.setattr(m.credentials_service, 'extract_text', Mock(return_value='text'))
    request = SimpleNamespace(state=SimpleNamespace(user_session=SimpleNamespace(user_id='owner')))
    response = asyncio.run(m.credentials_upload(request, UploadFile(BytesIO(b'payload'), filename='my resume.pdf')))
    assert response.status_code == 303
    assert record.call_args.kwargs['filename'] == 'my resume.pdf'
    files = list((tmp_path / 'data' / 'credentials' / 'owner' / '17').iterdir())
    assert len(files) == 1
    assert files[0].name != 'my resume.pdf'
    assert files[0].read_bytes() == b'payload'
