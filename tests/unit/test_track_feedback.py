from types import SimpleNamespace

import pytest

from app.services.track_feedback import review_checkpoint


@pytest.mark.parametrize('confidence, expected', [
    ('stuck', 'first step'), ('uncertain', 'small example'), ('clear', 'without your notes'),
])
def test_self_review_gives_confidence_specific_practice_without_grading(confidence, expected):
    result = review_checkpoint(
        track=SimpleNamespace(title='ML4Good'),
        section=SimpleNamespace(title='Gradient descent', checkpoint='Explain an update'),
        answers='A gradient gives the direction of steepest ascent.',
        confidence=confidence, artifact_url='https://example.com/notebook', user_id='learner',
    )
    assert result['source'] == 'self_review'
    assert expected in result['next_action']
    assert 'not an assessment of correctness' in result['summary']
    assert 'Explain an update' in result['questions'][0]
    assert 'passed' not in result
