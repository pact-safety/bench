"""Keep saved ML4Good progress stable while exposing the source's refreshers."""
from pathlib import Path

import yaml

PATH = Path('content/tracks/ml4good-prework-fall-2026.md')
ORIGINAL_TITLES = [
    'PyTorch and gradient descent in Colab',
    'PyTorch Basics 0–3: workflow, tensors, data, transforms',
    'PyTorch Basics 4–7: models, gradients, optimization, saving',
    'Why einops: readable tensor operations',
    'Practice manipulating high-dimensional tensors',
    'AI Safety Atlas 1: Capabilities', 'AI Safety Atlas 2: Risks',
    'AI Safety Atlas 3: Strategies', 'AI Safety Atlas 4: Governance',
    "Camp philosophy: Half-assing it with everything you've got",
    'ML4G transversal video playlist',
]


def _sections():
    frontmatter = yaml.safe_load(PATH.read_text().split('---', 2)[1])
    return [s for c in frontmatter['chapters'] for s in c['sections']]


def test_existing_progress_indexes_and_dependencies_remain_stable():
    sections = _sections()
    assert [s['title'] for s in sections[:11]] == ORIGINAL_TITLES
    assert [s['depends_on'] for s in sections[:11]] == [[], [0], [1], [1], [3], [], [], [], [], [], []]
    assert all(not s.get('optional', False) for s in sections[:11])
    assert len(sections) > 11
    assert all(s['optional'] and s['depends_on'] == [] for s in sections[11:])


def test_source_math_and_python_resources_are_attached_to_selectable_sections():
    sections = _sections()
    urls = {r['url'] for s in sections for r in s.get('resources', [])}
    expected = {
        'https://www.youtube.com/watch?v=kYB8IZa5AuE',
        'http://mlwiki.org/index.php/Matrix-Matrix_Multiplication',
        'https://www.youtube.com/watch?v=GkPhwnvRe-8',
        'https://www.youtube.com/watch?v=0EB23unfLSU',
        'https://www.youtube.com/playlist?list=PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab',
        'https://www.lesswrong.com/posts/iupCxk3ddiJBAJkts/six-and-a-half-intuitions-for-svd',
        'https://jonathan-hui.medium.com/probability-in-machine-learning-deep-learning-a2acdd793f18',
        'https://jonathan-hui.medium.com/normal-distributions-in-machine-learning-c8a21c8ba8c9',
        'https://medium.com/jun94-devpblog/prob-stats-3-expected-value-variance-and-standard-deviation-bce9303d8da8',
        'https://www.3blue1brown.com/topics/calculus',
        'https://docs.python.org/3/tutorial/introduction.html',
        'https://docs.python.org/3/tutorial/controlflow.html',
        'https://docs.python.org/3/tutorial/datastructures.html',
        'https://www.w3schools.com/python/python_classes.asp',
        'https://peps.python.org/pep-0020/',
        'https://www.pythontutorial.net/python-oop/',
        'https://peps.python.org/pep-0008/',
        'https://einops.rocks/',
        'https://www.youtube.com/watch?v=IvgV6QcsC64',
    }
    assert expected <= urls
    notes = ' '.join(s.get('notes', '') for s in sections[11:]).lower()
    for capability in ('rank', 'trace', 'determinant', 'transpose', 'bases',
                       'symmetric', 'orthogonal', 'identity', 'rotation', 'eigenvalues',
                       'expected value', 'standard deviation', 'independence',
                       'normal distribution', 'partial differentiation', 'chain rule', 'taylor'):
        assert capability in notes
    assert all(s.get('notes') and s.get('checkpoint') and s.get('resources') for s in sections[11:])


def test_required_work_keeps_its_reference_help_and_scope():
    sections = _sections()
    assert any('pytorch_with_examples' in r['url'] for r in sections[0].get('resources', []))
    assert {r['url'] for r in sections[4]['resources']} == {'https://einops.rocks/', 'https://www.youtube.com/watch?v=IvgV6QcsC64'}
    assert 'every exercise is not required' in sections[4]['checkpoint']
    body = PATH.read_text()
    assert 'source calls these mathematical capabilities essential' in body
    assert 'Bench estimates' in body
