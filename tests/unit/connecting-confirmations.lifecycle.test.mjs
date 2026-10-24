import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {JSDOM, VirtualConsole} from 'jsdom';

const template = readFileSync(new URL('../../templates/connecting_detail.html', import.meta.url), 'utf8');
const escapeHtml = value => value.replaceAll('&', '&amp;').replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');

function page(name = 'Alex') {
  // Exercise the actual form attributes after HTML entity decoding, just as a
  // browser does; the name substitution mirrors Jinja's escaped HTML output.
  const forms = [...template.matchAll(/<form\b[\s\S]*?<\/form>/g)].map(match => match[0]).join('\n')
    .replace(/\{\{ contact.name(?: \| e)? \}\}/g, escapeHtml(name))
    .replaceAll('{{ contact.id }}', '7');
  const scripts = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[0]).join('\n');
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error));
  const dom = new JSDOM(forms + scripts, {url: 'https://bench.test/connecting/7', runScripts: 'dangerously', virtualConsole});
  const w = dom.window;
  let accepted = false;
  const prompts = [], posts = [];
  w.confirm = prompt => {prompts.push(prompt); return accepted;};
  // Catch explicit submissions too, so a handler cannot accidentally submit
  // once itself and then let the native default action submit a second time.
  w.HTMLFormElement.prototype.submit = function () {posts.push(this.action);};
  w.HTMLFormElement.prototype.requestSubmit = function () {posts.push(this.action);};
  function submit(suffix) {
    const form = w.document.querySelector(`form[action$="/${suffix}"]`);
    const event = new w.Event('submit', {bubbles: true, cancelable: true});
    if (form.dispatchEvent(event)) posts.push(form.action);
    return event;
  }
  return {w, errors, prompts, posts, submit, accept: () => {accepted = true;}};
}

for (const name of ["O'Brien", 'Li "quoted"', 'Li \\ path', '</script><script>window.compromised=true</script>']) {
  test(`interaction cancel and accept preserve name as text: ${name}`, () => {
    const state = page(name);
    try {
      assert.equal(state.submit('interactions').defaultPrevented, true);
      assert.equal(state.posts.length, 0);
      assert.ok(state.prompts[0].includes(name));
      state.accept();
      assert.equal(state.submit('interactions').defaultPrevented, false);
      assert.deepEqual(state.posts, ['https://bench.test/connecting/7/interactions']);
      assert.equal(state.prompts.length, 2);
      assert.equal(state.w.compromised, undefined);
      assert.deepEqual(state.errors, []);
    } finally {state.w.close();}
  });
}

test('archive cancellation prevents POST and acceptance submits once', () => {
  const state = page();
  try {
    assert.equal(state.submit('archive').defaultPrevented, true);
    assert.equal(state.posts.length, 0);
    assert.match(state.prompts[0], /History is preserved/);
    state.accept();
    assert.equal(state.submit('archive').defaultPrevented, false);
    assert.deepEqual(state.posts, ['https://bench.test/connecting/7/archive']);
    assert.equal(state.prompts.length, 2);
    assert.deepEqual(state.errors, []);
  } finally {state.w.close();}
});

test('private-note confirmation explains that warmth and reply state stay unchanged', () => {
  const state = page("O'Brien");
  try {
    state.w.document.querySelector('[name="kind"]').value = 'note';
    assert.equal(state.submit('interactions').defaultPrevented, true);
    assert.equal(state.posts.length, 0);
    assert.match(state.prompts[0], /private note/i);
    assert.match(state.prompts[0], /warmth and reply state stay unchanged/i);
    state.w.document.querySelector('[name="kind"]').value = 'received';
    state.submit('interactions');
    assert.doesNotMatch(state.prompts[1], /private note/i);
  } finally {state.w.close();}
});
