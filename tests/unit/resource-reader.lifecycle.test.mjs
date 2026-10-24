import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {JSDOM} from 'jsdom';

const source = readFileSync(new URL('../../static/js/resource-reader.js', import.meta.url), 'utf8');
const panel = readFileSync(new URL('../../templates/_resource_reader.html', import.meta.url), 'utf8');
const atlas = 'https://ai-safety-atlas.com/chapters/v1/capabilities/introduction/';
function page(query = '') {
  const dom = new JSDOM(`<body>
    <li id="section-0" class="learning-section"><details data-track-section><summary>Section</summary>
      <p><a href="${atlas}" data-resource-reader="${atlas}" data-resource-title="Atlas chapter">Read chapter</a></p>
      <details data-supplements><summary>Supplements</summary><ul><li><a href="${atlas}#evidence" data-resource-reader="${atlas}#evidence" data-resource-title="Evidence">Read evidence</a></li></ul></details>
      <textarea name="stopping_point">Unsaved stopping point</textarea>
      <h3 data-resource-reflection tabindex="-1">Explain from memory</h3>
      <textarea name="answers">Unsaved explanation</textarea>
    </details></li>
    <li id="section-1"><details data-track-section><summary>Locked</summary></details></li>
    ${panel}</body>`, {url: 'https://bench.test/tracks/ml4good' + query, runScripts: 'outside-only'});
  const w = dom.window;
  w.eval(source);
  w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
  return {w, links: [...w.document.querySelectorAll('[data-resource-reader]')],
    panel: w.document.getElementById('resource-reader'), frame: w.document.querySelector('iframe')};
}

test('opening is lazy and hiding preserves the source, drafts, and reflection focus', () => {
  const {w, links, panel, frame} = page();
  assert.equal(frame.hasAttribute('src'), false);
  assert.equal(panel.hidden, true);
  links[0].click();
  assert.equal(panel.hidden, false);
  assert.equal(frame.src, atlas);
  assert.equal(frame.title, 'Atlas chapter');
  assert.equal(links[0].getAttribute('aria-expanded'), 'true');
  assert.equal(w.document.activeElement, panel.querySelector('[data-resource-heading]'));
  assert.equal(panel.closest('#section-0') !== null, true);
  assert.equal(panel.querySelector('[data-resource-original]').href, atlas);
  assert.equal(panel.querySelector('[data-resource-original]').target, '_blank');
  panel.querySelector('[data-resource-close]').click();
  assert.equal(panel.hidden, true);
  assert.equal(frame.src, atlas);
  assert.equal(links[0].getAttribute('aria-expanded'), 'false');
  assert.equal(w.document.activeElement, w.document.querySelector('[data-resource-reflection]'));
  assert.equal(w.document.querySelector('[name=stopping_point]').value, 'Unsaved stopping point');
  assert.equal(w.document.querySelector('[name=answers]').value, 'Unsaved explanation');
  const parent = panel.parentElement;
  let sourceWrites = 0;
  const original = frame.setAttribute.bind(frame);
  frame.setAttribute = (name, value) => { if (name === 'src') sourceWrites++; original(name, value); };
  links[0].click();
  assert.equal(panel.parentElement, parent);
  assert.equal(sourceWrites, 0);
  assert.equal(panel.hidden, false);
  w.close();
});

test('switching sources reuses one panel and keeps keyboard controls operable', () => {
  const {w, links, panel, frame} = page();
  links[0].click();
  links[1].dispatchEvent(new w.KeyboardEvent('keydown', {key: ' ', bubbles: true, cancelable: true}));
  assert.equal(frame.src, atlas + '#evidence');
  assert.equal(links[0].getAttribute('aria-expanded'), 'false');
  assert.equal(links[1].getAttribute('aria-expanded'), 'true');
  assert.equal(panel.parentElement, links[1].parentElement);
  assert.equal(w.document.querySelector('[data-supplements]').open, true);
  assert.equal(w.document.querySelectorAll('#resource-reader').length, 1);
  assert.equal(w.document.querySelector('[name=answers]').value, 'Unsaved explanation');
  links[1].click();
  assert.equal(panel.hidden, true);
  w.close();
});

test('modified link gestures retain browser navigation', () => {
  const {w, links, panel} = page();
  const event = new w.MouseEvent('click', {ctrlKey: true, bubbles: true, cancelable: true});
  links[0].dispatchEvent(event);
  assert.equal(event.defaultPrevented, false);
  assert.equal(panel.hidden, true);
  w.close();
});

test('read query selects only an existing server-rendered section link', () => {
  let view = page('?read=0');
  assert.equal(view.frame.src, atlas);
  assert.equal(view.w.document.querySelector('[data-track-section]').open, true);
  view.w.close();
  for (const query of ['?read=1', '?read=-1', '?read=https://evil.example/', '?read=999']) {
    view = page(query);
    assert.equal(view.panel.hidden, true);
    assert.equal(view.frame.hasAttribute('src'), false);
    view.w.close();
  }
});

test('iframe load does not claim that cross-origin content succeeded', () => {
  const {w, links, panel, frame} = page();
  links[0].click();
  const status = panel.querySelector('[role=status]');
  const before = status.textContent;
  frame.dispatchEvent(new w.Event('load'));
  assert.equal(status.textContent, before);
  assert.ok(panel.querySelector('[data-resource-original]'));
  w.close();
});

function contentPage(query = '') {
  const dom = new JSDOM(`<body>
    <article data-resource-scope>
      <p><a href="${atlas}" data-resource-reader="${atlas}" data-resource-title="Atlas chapter">Read chapter</a></p>
      <h2 data-resource-reflection tabindex="-1">Reflect on this reading</h2>
      <textarea name="reflection">Unsaved item reflection</textarea>
    </article>${panel}</body>`, {
    url: 'https://bench.test/content/track-atlas' + query, runScripts: 'outside-only',
  });
  const w = dom.window;
  w.eval(source);
  w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
  return {w, link: w.document.querySelector('[data-resource-reader]'),
    panel: w.document.getElementById('resource-reader'), frame: w.document.querySelector('iframe')};
}

test('content source hides into its item reflection and reopens the same browsing context', () => {
  const {w, link, panel, frame} = contentPage();
  assert.equal(frame.hasAttribute('src'), false);
  link.click();
  const browsingContext = frame.contentWindow;
  assert.equal(panel.hidden, false);
  assert.equal(panel.closest('[data-resource-scope]') !== null, true);
  assert.equal(frame.src, atlas);
  assert.equal(panel.querySelector('[data-resource-close]').textContent, 'Hide source and reflect');
  panel.querySelector('[data-resource-close]').click();
  assert.equal(panel.hidden, true);
  assert.equal(w.document.activeElement, w.document.querySelector('[data-resource-reflection]'));
  assert.equal(w.document.querySelector('[name=reflection]').value, 'Unsaved item reflection');
  let sourceWrites = 0;
  const original = frame.setAttribute.bind(frame);
  frame.setAttribute = (name, value) => { if (name === 'src') sourceWrites++; original(name, value); };
  link.click();
  assert.equal(panel.hidden, false);
  assert.equal(frame.contentWindow, browsingContext);
  assert.equal(sourceWrites, 0);
  w.close();
});

test('content-page queries cannot provide or auto-open a source', () => {
  for (const query of ['?read=0', '?read=https://evil.example/', '?url=https://evil.example/']) {
    const {w, panel, frame} = contentPage(query);
    assert.equal(panel.hidden, true);
    assert.equal(frame.hasAttribute('src'), false);
    w.close();
  }
});
