from pathlib import Path
from types import SimpleNamespace as N

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[2]


def render(name='track_exam.html', **extra):
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '{% block body %}{% endblock %}'}),
        FileSystemLoader(ROOT / 'templates'),
    ]), autoescape=select_autoescape())
    context = dict(track=N(slug='arena_3', title='ARENA'), section=N(title='Prerequisites'), idx=0,
        spec=dict(id='pilot', version='v2', questions=[{'id':'q1','prompt':'Explain dimensions.','kind':'explanation'},
            {'id':'q2','prompt':'Apply this to a new shape.','kind':'application'}],
            criteria=[dict(id='shape',label='Shape reasoning',description='Explain the axes.',essential=True,
                anchors={0:'No evidence',1:'Limited',2:'Partial',3:'Accurate',4:'Accurate and justified'})],
            threshold=80, practical_required=['tensor-check']), request_id='r1', form={}, error='', submissions=[], queue=[], selected=None)
    context.update(extra)
    return env.get_template(name).render(**context)


def test_exam_has_shared_rubric_and_no_automatic_pass_claim():
    html=render()
    for text in ('Explain dimensions.', 'Apply this to a new shape.', 'Fresh application', 'Shape reasoning',
                 '80%', '3/4', 'human review', 'unproctored', 'not certification'):
        assert text in html
    assert 'name="exam_version" value="v2"' in html
    assert 'name="request_id" value="r1"' in html
    assert 'maxlength="12000"' in html
    assert 'data-voice-note-append' in html


def test_exam_preserves_failed_form_and_escapes_answers():
    html=render(form={'answers':'<script>draft</script>', 'modality':'oral', 'assistance':'notes',
                     'artifact_url':'https://example.com/work', 'transcript_confirmed':True},error='Please review transcript')
    assert '&lt;script&gt;draft&lt;/script&gt;' in html
    assert 'value="oral" selected' in html
    assert 'value="notes" selected' in html
    assert 'value="https://example.com/work"' in html
    assert 'role="alert"' in html
    assert 'name="transcript_confirmed"' in html


def test_pending_submission_keeps_answers_visible():
    html=render(submissions=[dict(id='a1', state='pending',modality='oral',assistance='none',
               submitted_at='2026-09-25',spec_version='v2',responses={'answers':'Saved explanation'},review={})])
    assert 'Pending human review' in html
    assert 'Saved explanation' in html
    assert 'id="submissions"' in html


def test_reviewer_has_evidence_fields_no_prefilled_scores():
    selected=dict(id='a1',user_id='owner',state='pending',spec_version='v2',modality='written',
                  assistance='none',responses={'answers':'Explain <axes>','artifact_url':''},review={})
    html=render('track_exam_review.html', selected=selected)
    assert '/track-assessments/owner/a1/review' in html
    assert 'name="score_shape"' in html
    assert 'name="evidence_shape"' in html
    assert 'Explain &lt;axes&gt;' in html
    assert 'Paste an exact excerpt' in html
    assert 'value="" selected' in html
    assert 'name="exam_version" value="v2"' in html


def test_stale_exam_cannot_be_reviewed_against_current_rubric():
    html=render('track_exam_review.html', selected=dict(id='a1',user_id='owner',state='pending',
        spec_version='old',responses={'answers':'Preserved old answer'},review={}))
    assert 'Preserved old answer' in html
    assert 'name="score_shape"' not in html
    assert 'version' in html


def test_stale_form_does_not_upgrade_answers_to_current_exam():
    html=render(form={'exam_version':'v1','answers':'Preserved old draft'})
    assert 'name="exam_version" value="v1"' in html
    assert 'Open current assessment' in html
    assert 'Preserved old draft' in html


def test_assisted_submission_is_clearly_practice_only():
    html=render(submissions=[dict(id='a1',state='pending',modality='written',assistance='help',
               submitted_at='2026-09-25',spec_version='v2',responses={'answers':'My practice'},review={})])
    assert 'Practice review only — cannot test out.' in html


def test_exam_confirmation_lifecycle():
    import shutil
    import subprocess
    import pytest
    if not shutil.which('node'):
        pytest.skip('node is required for form lifecycle checks')
    result=subprocess.run(['node','--test',str(ROOT/'tests/unit/track-exam.lifecycle.test.mjs')],
                          capture_output=True,text=True,cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_practical_exercise_does_not_offer_a_broken_activity_link():
    html=render(practical_gate={'passed':False,'passed_count':0,'total':1,
        'items':[{'slug':'missing','title':'Missing check','unavailable':True,'passed':False}]})
    assert '/problem/missing' not in html
    assert 'assessment unavailable' in html


def test_completed_or_exempt_track_has_no_continue_and_reviewer_link_is_admin_only():
    row=N(track=N(slug='arena_3',title='ARENA',description='Practice'),is_available=True,
          is_active=True,is_paused=False,completed_count=1,exempt_count=1,satisfied_count=2,
          total_sections=2,first_section=None,cursor=0)
    html=render('tracks_index.html',track_rows=[row],active_row=row,is_admin=False)
    assert 'Continue your track' not in html
    assert '1/2 core practice checks completed · 1 tested out' in html
    assert '/track-assessments/review' not in html
    admin=render('tracks_index.html',track_rows=[row],active_row=row,is_admin=True)
    assert '/track-assessments/review' in admin


def test_review_recovery_read_outage_keeps_escaped_draft_without_actionable_form():
    html=render('track_exam_review.html',selected=None,spec=None,
        error='Review could not be confirmed. Retry after service recovery.',
        form={'exam_version':'v2', 'score_shape':'3', 'evidence_shape':'<script>quoted answer</script>'})
    assert 'Your review draft' in html
    assert 'No submissions are waiting' not in html
    assert 'score_shape' in html and '>3<' in html
    assert 'evidence_shape' in html
    assert '&lt;script&gt;quoted answer&lt;/script&gt;' in html
    assert '<script>quoted answer</script>' not in html
    assert 'exam_version' in html and '>v2<' in html
    assert 'after service recovery' in html
    assert '<form' not in html


def test_review_history_shows_criterion_rating_with_current_rubric_label():
    html=render(submissions=[dict(id='a1',state='reviewed',modality='written',assistance='none',
        submitted_at='2026-09-25',spec_version='v2',responses={'answers':'My explanation'},
        review={'verdict':'not_approved','percentage':50,'scores':{'shape':2},
                'evidence':{'shape':'My explanation'}})])
    assert 'Shape reasoning — 2/4' in html
    assert 'My explanation' in html


def test_old_review_is_not_presented_as_a_current_exemption_or_relabelled():
    html=render(submissions=[dict(id='a1',state='reviewed',modality='written',assistance='none',
        submitted_at='2026-09-25',spec_version='v1',responses={'answers':'Old answer'},
        review={'verdict':'approved','percentage':100,'scores':{'shape':4},
                'evidence':{'shape':'Old answer'}})])
    history=html.split('id="submissions"',1)[1]
    assert 'Earlier assessment version; does not grant a current exemption' in history
    assert 'shape — 4/4' in history
    assert 'Shape reasoning' not in history
