from pathlib import Path
from types import SimpleNamespace as N

import pytest
from fastapi import HTTPException
from starlette.requests import Request


@pytest.fixture
def routes(monkeypatch):
    import app.main as m
    from app.services import tracks
    catalog = tracks.load_all_tracks(Path('content/tracks'))
    monkeypatch.setattr(m, '_tracks_by_slug', catalog)
    monkeypatch.setattr(tracks, '_tracks_by_slug', catalog)
    monkeypatch.setattr(m, '_daily_chain_step', lambda *a, **k: None)
    monkeypatch.setattr(m.problem_repo, 'all_core', lambda: [])
    monkeypatch.setattr(m.problem_repo, 'all_warmups', lambda: [])
    monkeypatch.setattr(m.attempt_repo, 'all_for_user', lambda *a: [])
    monkeypatch.setattr(m.content_repo, 'progress_for_user', lambda *a: {})
    monkeypatch.setattr(m.templates, 'TemplateResponse', lambda request, name, context, **kw: dict(template=name, **context))
    return m


def request(settings=None):
    r = Request({'type': 'http', 'method': 'GET', 'path': '/library', 'headers': [], 'query_string': b''})
    r.state.user_session = N(user_id='learner')
    r.state.user_settings = settings or {}
    return r


def item_for(m, idx):
    from app.services.track_content import catalog_items, item_slug
    track = m._tracks_by_slug['ml4good-prework-fall-2026']
    slug = item_slug(track.slug, track.all_sections[idx].url)
    return next(item for item in catalog_items(m._tracks_by_slug) if item.slug == slug)


def test_atlas_opens_own_content_page_with_track_context(routes, monkeypatch):
    item = item_for(routes, 5)
    monkeypatch.setattr(routes.content_repo, 'get_by_slug', lambda *a, **k: item)
    result = routes.view_content(request(), item.slug)
    assert result['template'] == 'content.html'
    assert result['track_context']['idx'] == 5
    assert result['track_context']['check_url'] == '/tracks/ml4good-prework-fall-2026/sections/5'
    assert result['track_context']['unlocked']


def test_locked_item_does_not_render_source_or_allow_progress_write(routes, monkeypatch):
    item = item_for(routes, 1)
    monkeypatch.setattr(routes.content_repo, 'get_by_slug', lambda *a, **k: item)
    monkeypatch.setattr(routes.content_repo, 'get_by_id', lambda *a, **k: item)
    monkeypatch.setattr(routes.content_repo, 'set_rating', lambda *a: pytest.fail('locked rating write'))
    result = routes.view_content(request(), item.slug)
    assert result['template'] == 'track_content_locked.html'
    assert result['track_context']['missing_prerequisites']
    with pytest.raises(HTTPException) as exc:
        routes.rate_content(request(), 1, rating=5)
    assert exc.value.status_code == 403


def test_finishing_resource_continues_to_check_without_granting_checkpoint(routes, monkeypatch):
    item = item_for(routes, 5)
    track = routes._tracks_by_slug['ml4good-prework-fall-2026']
    state = {'active_track': {'slug': track.slug, 'checkpoint_passed_sections': []}}
    r = request(state)
    monkeypatch.setattr(routes.content_repo, 'get_by_id', lambda *a, **k: item)
    writes = []
    monkeypatch.setattr(routes.content_repo, 'mark_completed', lambda *a, **k: writes.append(a))
    response = routes.check_content(r, 1, next=1, initiative_slug='')
    assert response.headers['location'] == f'/tracks/{track.slug}/sections/5'
    assert len(writes) == 1
    assert state['active_track']['checkpoint_passed_sections'] == []


def test_library_type_filter_includes_only_requested_kind(routes, monkeypatch):
    from app.services.track_content import catalog_items
    items = catalog_items(routes._tracks_by_slug)
    monkeypatch.setattr(routes.content_repo, 'all_by_kind', lambda kind, **kw: [c for c in items if c.kind == kind])
    monkeypatch.setattr(routes, '_bubbles_for', lambda *a: [])
    result = routes.library_page(request(), type='video')
    assert result['all_content']
    assert {c.kind for c in result['all_content']} == {'video'}
    assert {'reading', 'video', 'exercise'} <= set(result['all_types'])


def test_dedicated_section_page_owns_checkpoint_form(routes, monkeypatch):
    monkeypatch.setattr(routes, '_track_gate_status', lambda *a: None)
    track = routes._tracks_by_slug['ml4good-prework-fall-2026']
    r = request({'active_track': {'slug': track.slug, 'checkpoint_passed_sections': []}})
    page = routes.track_section_page(r, track.slug, 5)
    assert page['template'] == 'track_section.html'
    assert page['row']['idx'] == 5
    assert page['row']['checkpoint_questions']


def test_track_scaffold_rejects_paper_ladder_even_when_unlocked(routes, monkeypatch):
    import asyncio
    from starlette.datastructures import FormData
    item = item_for(routes, 5)
    monkeypatch.setattr(routes.content_repo, 'get_by_id', lambda *a, **k: item)
    monkeypatch.setattr(routes.content_repo, 'save_paper_state', lambda *a: pytest.fail('scaffold paper write'))
    r = request()
    r._form = FormData({'to_pass': '1'})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.content_advance_pass(r, 1))
    assert exc.value.status_code == 409


def test_retired_track_resource_has_no_public_detail_or_rating(routes, monkeypatch):
    item = item_for(routes, 5)
    monkeypatch.setattr(routes, '_tracks_by_slug', {})
    monkeypatch.setattr(routes.content_repo, 'get_by_slug', lambda *a, **k: item)
    with pytest.raises(HTTPException) as exc:
        routes.view_content(request(), item.slug)
    assert exc.value.status_code == 404


@pytest.fixture
def shared_resource(routes, monkeypatch):
    from app.services.track_content import catalog_items, references_for_slug
    item = next(item for item in catalog_items(routes._tracks_by_slug)
                if item.title == 'Essence of Linear Algebra series')
    refs = references_for_slug(routes._tracks_by_slug, item.slug)
    state = {'checkpoint_passed_sections': [], 'preferred_section': 12,
             'session_per_section': {'11': {'stopping_point': 'Foundation notes'},
                                    '12': {'stopping_point': 'Extension notes'}}}
    monkeypatch.setattr(routes, '_track_status_and_state', lambda *a, **k: ('active', state))
    monkeypatch.setattr(routes, '_track_exemptions', lambda *a, **k: set())
    monkeypatch.setattr(routes.content_repo, 'get_by_id', lambda *a, **k: item)
    return item, refs, state


def test_shared_supplement_returns_to_selected_section_and_its_stopping_point(routes, shared_resource, monkeypatch):
    item, _, state = shared_resource
    context = routes._track_content_context(request(), item)
    assert context['idx'] == 12
    assert context['session']['stopping_point'] == 'Extension notes'
    assert context['check_url'].endswith('/sections/12')
    writes = []
    monkeypatch.setattr(routes.content_repo, 'mark_completed', lambda *a, **k: writes.append(a))
    response = routes.check_content(request(), 42, next=1, initiative_slug='')
    assert response.headers['location'] == context['primary_url']
    assert writes == [('learner', 42)]
    assert state['checkpoint_passed_sections'] == []


@pytest.mark.parametrize('preferred', ['absent', None, 'invalid', {}, [], True, 12.5, 999])
def test_shared_supplement_without_valid_selection_keeps_default_context(routes, shared_resource, preferred):
    item, _, state = shared_resource
    if preferred == 'absent':
        state.pop('preferred_section')
    else:
        state['preferred_section'] = preferred
    assert routes._track_content_context(request(), item)['idx'] == 11


@pytest.mark.parametrize('preferred', [12, '12'])
def test_shared_supplement_accepts_saved_integer_or_string_selection(routes, shared_resource, preferred):
    item, _, state = shared_resource
    state['preferred_section'] = preferred
    assert routes._track_content_context(request(), item)['idx'] == 12


def test_shared_supplement_locked_selection_falls_back_to_unlocked_context(routes, shared_resource, monkeypatch):
    item, refs, _ = shared_resource
    track = refs[1].track
    original = routes.tracks_service.missing_prerequisites
    monkeypatch.setattr(routes.tracks_service, 'missing_prerequisites',
                        lambda t, idx, done: [(0, track.all_sections[0].title)] if idx == 12 else original(t, idx, done))
    context = routes._track_content_context(request(), item)
    assert context['idx'] == 11 and context['unlocked']


def test_shared_supplement_all_locked_rejects_progress_write(routes, shared_resource, monkeypatch):
    item, _, _ = shared_resource
    monkeypatch.setattr(routes.tracks_service, 'missing_prerequisites', lambda *a: [(0, 'Prerequisite')])
    monkeypatch.setattr(routes.content_repo, 'set_rating', lambda *a: pytest.fail('locked rating write'))
    assert not routes._track_content_context(request(), item)['unlocked']
    with pytest.raises(HTTPException) as exc:
        routes.rate_content(request(), 42, rating=5)
    assert exc.value.status_code == 403
