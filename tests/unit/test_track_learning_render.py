"""Track pages keep saved work readable without reopening gated activities."""
from pathlib import Path
from types import SimpleNamespace as N
import re

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

ROOT = Path(__file__).resolve().parents[2]


def render_track(template="track_detail.html", **changes):
    section = N(title='Array foundations', notes='Use small examples.', url='https://source.example/section',
                kind='external_exercise', duration_min=120, resources=[], optional=False)
    row = N(idx=0, section=section, content_url='/content/track-ml4good-arrays', resources=[], exemption=False, exam_url=None, is_current=True, is_completed=False, is_unlocked=True,
            is_future=False, missing_prerequisites=[], checkpoint_text='Explain array dimensions.',
            prep_items=[], gate=None, check_version="check-v2", checkpoint_questions=['What does each dimension mean?'],
            response={}, stale_response={'answers': 'Earlier saved answer'},
            session={'stopping_point': 'Cell 12', 'next_action': 'Test broadcasting',
                     'artifact_url': 'https://work.example/notebook'})
    for key in list(changes):
        if key.startswith('section_'):
            setattr(section, key[8:], changes.pop(key))
    for key in list(changes):
        if key.startswith('row_'):
            setattr(row, key[4:], changes.pop(key))
    track = N(title='ML4Good', slug='ml4good', description='Build and explain models.',
              body_md='Read these notes before starting.', source_url='https://source.example/curriculum')
    context = dict(track=track, is_active=True, is_paused=False, is_available=True,
                   completed_count=0, total_sections=1, optional_total=0, optional_completed=0,
                   next_section_number=1, gate_blocked_title='', current_row=row,
                   row=row, chapter_rows=[N(title='Foundations', sections=[row])])
    context.update(changes)
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '{% block body %}{% endblock %}'}),
        FileSystemLoader(ROOT / 'templates'),
    ]), autoescape=select_autoescape())
    env.filters['markdown'] = lambda text: Markup('<p>') + text + Markup('</p>')
    from app.services.resource_reader import resource_reader_url
    env.globals['resource_reader_url'] = resource_reader_url
    env.globals['static_hash'] = lambda _: 'test'
    return env.get_template(template).render(**context)


def render_section(**changes):
    return render_track('track_section.html', **changes)


def test_notes_precede_start_and_curriculum_links():
    html = render_track(is_active=False)
    assert html.index('Read these notes') < html.index('Source curriculum')
    assert html.index('Read these notes') < html.index('Activate track')


@pytest.mark.parametrize('state', ['pending', 'locked', 'completed', 'paused'])
def test_saved_session_and_replaced_answers_survive_noneditable_states(state):
    changes = {'pending': dict(is_available=False),
               'locked': dict(row_is_unlocked=False, row_is_future=True),
               'completed': dict(row_is_completed=True),
               'paused': dict(is_active=False, is_paused=True)}[state]
    html = render_section(**changes)
    assert 'Cell 12' in html
    assert 'https://work.example/notebook' in html
    assert 'Earlier saved answer' in html
    assert 'name="answers"' not in html


def test_pending_page_has_saved_work_but_no_curriculum_activities():
    html = render_section(is_available=False)
    assert 'Request this track' in html
    assert 'https://source.example/' not in html
    assert '/activate' not in html
    assert '/focus' not in html
    assert '/complete' not in html
    assert '/mira?' not in html


def test_locked_section_hides_source_and_names_missing_prerequisite():
    html = render_section(row_is_unlocked=False, row_is_future=True,
                        row_missing_prerequisites=[(2, 'Python basics')])
    assert 'https://source.example/section' not in html
    assert 'href="/tracks/ml4good/sections/2">Python basics</a>' in html


def test_active_track_has_one_styled_primary_next_step():
    html = render_track(row_response={'answers': 'Arrays have dimensions', 'confidence': 'clear'})
    assert html.count('class="btn btn--primary"') == 1
    assert 'class="btn btn--primary" href="/content/track-ml4good-arrays"' in html
    assert 'class="primary"' not in html


def test_learning_styles_only_reference_defined_tokens():
    css = (ROOT / 'static/css/main.css').read_text()
    tokens = css + (ROOT / 'static/css/tokens.css').read_text()
    known = set(re.findall(r'(--[\w-]+)\s*:', tokens))
    learning = css[css.index('.learning-page {'):]
    assert set(re.findall(r'var\((--[\w-]+)', learning)) <= known


def test_explanation_form_carries_the_rendered_check_version():
    html = render_section()
    assert 'name="check_version" value="check-v2"' in html


def test_next_step_is_reachable_without_scrolling_through_all_notes():
    html = render_track()
    assert 'href="#track-next"' in html
    assert 'id="track-next"' in html


def test_pending_active_track_is_not_offered_as_a_continue_action():
    row = N(track=N(title='Pending curriculum', slug='pending', description='Under review'),
            is_available=False, is_active=True, is_paused=False, completed_count=1,
            total_sections=3, first_section=None, cursor=1)
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '{% block body %}{% endblock %}'}),
        FileSystemLoader(ROOT / 'templates'),
    ]), autoescape=select_autoescape())
    html = env.get_template('tracks_index.html').render(active_row=row, track_rows=[row])
    assert 'Continue your track' not in html
    assert 'Request this track' in html
    assert 'View saved work' in html
    assert '/activate' not in html


def test_exemption_remains_distinct_and_has_no_practice_completion_form():
    html = render_section(row_exemption=True, exempt_count=1, satisfied_count=1)
    assert 'Tested out' in html
    assert 'name="answers"' not in html
    assert '/complete' not in html
    assert 'Cell 12' in html


def test_locked_pilot_section_offers_exam_without_opening_curriculum():
    html = render_section(row_is_unlocked=False, row_is_future=True,
                        row_exam_url='/tracks/ml4good/sections/0/exam')
    assert 'href="/tracks/ml4good/sections/0/exam"' in html
    assert 'https://source.example/section' not in html
    assert 'name="answers"' not in html


def test_outline_has_typed_library_links_and_a_separate_check_page():
    html = render_track(row_resources=[N(kind='video', url='/content/tensor-video', title='Tensor video')])
    assert 'href="/content/track-ml4good-arrays"' in html
    assert 'href="/content/tensor-video"' in html
    assert 'video' in html
    assert 'exercise' in html
    assert 'href="/tracks/ml4good/sections/0"' in html
    for endpoint in ('/session', '/feedback', '/complete', '/focus'):
        assert '/tracks/ml4good/sections/0' + endpoint not in html
    assert 'Earlier saved answer' not in html
    assert '<iframe' not in html
    assert 'resource-reader.js' not in html


def test_section_links_to_library_without_an_embedded_reader():
    html = render_section(row_resources=[N(kind='reading', url='/content/tensor-docs', title='Tensor docs')])
    assert 'href="/content/track-ml4good-arrays"' in html
    assert 'href="/content/tensor-docs"' in html
    assert 'https://source.example/section' not in html
    assert '<iframe' not in html
    assert 'resource-reader.js' not in html


@pytest.mark.parametrize('changes', [dict(is_available=False),
    dict(row_is_unlocked=False, row_is_future=True)])
@pytest.mark.parametrize('template', ['track_detail.html', 'track_section.html'])
def test_pending_or_locked_resources_preserve_their_gate(changes, template):
    html = render_track(template, row_resources=[N(kind='video', url='/content/tensor-video', title='Tensor video')],
                        **changes)
    assert 'href="/content/track-ml4good-arrays"' not in html
    assert 'href="/content/tensor-video"' not in html


def test_section_notes_keep_recovery_and_original_form_actions():
    html = render_section()
    assert 'id="track-session-0"' in html
    assert 'id="track-feedback-0"' in html
    for endpoint in ('/session', '/feedback', '/focus'):
        assert 'action="/tracks/ml4good/sections/0' + endpoint + '"' in html
    for field in ['stopping-point-0', 'next-action-0', 'checkpoint-answers-0']:
        tag = re.search(r'<textarea\b[^>]*id="' + field + r'"[^>]*>', html).group()
        assert 'data-autosave' in tag
        assert 'data-autosave-persisted' in tag


@pytest.mark.parametrize('state', ['pending', 'locked', 'completed', 'paused'])
def test_current_and_historical_responses_remain_reviewable(state):
    changes = {'pending': dict(is_available=False),
               'locked': dict(row_is_unlocked=False, row_is_future=True),
               'completed': dict(row_is_completed=True),
               'paused': dict(is_active=False, is_paused=True)}[state]
    html = render_section(row_response={'answers': 'Current explanation', 'confidence': 'clear',
                          'previous_checks': [{'answers': 'First explanation'}],
                          'feedback': {'summary': 'Try a small example', 'next_action': 'Check values'}},
                          row_stale_response={'answers': 'Replaced explanation',
                                              'previous_checks': [{'answers': 'Older explanation'}]},
                          **changes)
    for text in ('Current explanation', 'First explanation', 'Try a small example', 'Check values',
                 'Replaced explanation', 'Older explanation'):
        assert text in html
    assert 'name="answers"' not in html


def test_section_keeps_practical_gate_prep_and_mentor_links():
    gate = {'passed': False, 'passed_count': 0, 'total': 1,
            'items': [N(slug='einsum', title='Einsum test', unavailable=False, passed=False)],
            'remaining': ['einsum']}
    html = render_section(row_gate=gate, row_prep_items=[N(slug='tensor-prep', title='Tensor prep', duration_min=10)])
    assert 'href="/content/tensor-prep"' in html
    assert 'href="/problem/einsum"' in html
    assert 'Prove it cold' in html
    assert 'href="/mira?track=ml4good&amp;section=0"' in html
    assert 'Complete practice check' not in html
