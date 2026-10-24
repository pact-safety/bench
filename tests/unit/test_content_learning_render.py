from pathlib import Path
from types import SimpleNamespace as N

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

from app.services.resource_reader import resource_reader_url
from app.services.track_content import catalog_items
from app.services.tracks import load_all_tracks

ROOT = Path(__file__).resolve().parents[2]


def render_item():
    item = next(i for i in catalog_items(load_all_tracks(ROOT / 'content/tracks')) if 'Atlas 1:' in i.title)
    item.id = 42
    env = Environment(loader=ChoiceLoader([DictLoader({'base.html': '{% block body %}{% endblock %}'}), FileSystemLoader(ROOT / 'templates')]), autoescape=select_autoescape())
    env.filters['markdown'] = str
    env.globals.update(resource_reader_url=resource_reader_url, static_hash=lambda _: 'test')
    return env.get_template('content.html').render(item=item, progress=N(status='in_progress', favorited=False, rating_1_to_5=4, notes_md='My own reflection'), track_context={'track': N(slug='ml4good', title='ML4Good'), 'section': N(title=item.title, notes='', checkpoint='Explain a trend'), 'idx': 5, 'is_primary': True, 'session': {}, 'continue_url': '/tracks/ml4good/sections/5', 'continue_label': 'Continue to practice check', 'check_url': '/tracks/ml4good/sections/5', 'resources': []}, is_paper=False, chain_step=None, attempts_after=[])


def test_item_feedback_is_accessible_and_has_explicit_save_actions():
    html = render_item()
    assert 'id="content-reflection-42"' in html
    assert 'for="content-reflection"' in html
    assert 'data-autosave-persisted' in html
    assert 'My own reflection' in html
    assert '/content/42/rate' in html and '/content/42/reflect' in html
    assert 'Save rating' in html
    assert 'onchange="this.form.submit()"' not in html
    css = (ROOT / 'static/css/main.css').read_text()
    assert '.content__rating-cell input { display: none; }' not in css


def test_item_reader_and_reflection_share_scope_without_scaffold_recitation():
    html = render_item()
    assert 'data-resource-scope' in html
    assert 'data-resource-reader="https://ai-safety-atlas.com/' in html
    assert 'data-resource-reflection' in html
    assert 'id="recite"' not in html
    assert 'Reading passes' not in html
    assert 'Finish resource + continue' in html
