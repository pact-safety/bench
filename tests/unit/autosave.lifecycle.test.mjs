import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {JSDOM} from 'jsdom';
const source = readFileSync(new URL('../../static/js/autosave.js', import.meta.url), 'utf8');
const key = (user = 'alice', name = 'body_md') => 'lisbench.autosave:v2:' + JSON.stringify([user, '/writings/7', 'writing-form', name]);
function page({user = 'alice', saved, server = 'server text', persisted = true, storage = {}} = {}) {
  const dom = new JSDOM(`<body data-autosave-user="${user}"><form id="writing-form"><textarea name="body_md" data-autosave ${persisted ? 'data-autosave-persisted' : ''}></textarea><span data-autosave-status="body_md"></span></form>`, {url:'https://bench.test/writings/7', runScripts:'outside-only'});
  const w = dom.window;
  w.document.querySelector('textarea').value = server;
  Object.entries(storage).forEach(([name, value]) => w.localStorage.setItem(name, value));
  if (saved !== undefined) w.localStorage.setItem(key(), saved);
  w.eval(source);
  w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
  const field = w.document.querySelector('textarea');
  const form = w.document.querySelector('form');
  const edit = value => {field.value = value; field.dispatchEvent(new w.Event('input', {bubbles:true}));};
  const ack = (value, user = 'alice') => {
    const elt = w.document.createElement('script');
    elt.type = 'application/json'; elt.dataset.autosaveConfirmed = '';
    elt.textContent = JSON.stringify({user, path:'/writings/7', form:'writing-form', fields:{body_md:value}});
    w.document.body.append(elt);
    w.document.dispatchEvent(new w.CustomEvent('htmx:afterSwap'));
  };
  return {w, field, form, edit, ack};
}
test('submit and generic HTTP success retain unsaved content, including empty edits', () => {
  const {w, form, edit} = page();
  edit('');
  form.dispatchEvent(new w.Event('submit'));
  form.dispatchEvent(new w.CustomEvent('htmx:afterRequest', {detail:{successful:true, xhr:{status:200}}}));
  assert.equal(w.localStorage.getItem(key()), '');
  w.close();
});
test('drafts are isolated by account and unattributed legacy keys are ignored', () => {
  const {w, field, edit} = page({user:'bob', saved:'alice secret', server:''});
  assert.equal(field.value, '');
  edit('bob draft');
  assert.equal(w.localStorage.getItem(key('bob')), 'bob draft');
  assert.equal(w.localStorage.getItem(key()), 'alice secret');
  w.close();
});
test('server text remains until explicit recovery; preview makes both versions available', () => {
  const {w, field} = page({saved:'unsaved local'});
  assert.equal(field.value, 'server text');
  const recovery = w.document.querySelector('[data-autosave-recovery]');
  assert.ok(recovery);
  assert.equal(recovery.querySelector('pre').textContent, 'unsaved local');
  recovery.querySelector('button').click();
  assert.equal(field.value, 'unsaved local');
  w.close();
});
test('authoritative full-page render acknowledges only an exact match', () => {
  const {w} = page({saved:'server text'});
  assert.equal(w.localStorage.getItem(key()), null);
  w.close();
});
test('HTMX exact acknowledgement retains newer edits and rejects another account', () => {
  const {w, edit, ack} = page();
  edit('sent'); edit('newer'); ack('sent');
  assert.equal(w.localStorage.getItem(key()), 'newer');
  ack('newer', 'bob');
  assert.equal(w.localStorage.getItem(key()), 'newer');
  ack('newer');
  assert.equal(w.localStorage.getItem(key()), null);
  w.close();
});
test('HTMX swaps attach newly inserted fields', () => {
  const {w} = page();
  const input = w.document.createElement('input');
  input.name = 'title'; input.dataset.autosave = '';
  w.document.querySelector('form').append(input);
  w.document.dispatchEvent(new w.CustomEvent('htmx:afterSwap'));
  input.value = 'new title'; input.dispatchEvent(new w.Event('input'));
  assert.equal(w.localStorage.getItem(key('alice', 'title')), 'new title');
  w.close();
});
test('missing account disables local draft reads and writes', () => {
  const {w, edit} = page({user:'', saved:'secret'});
  edit('anonymous');
  assert.equal(w.localStorage.length, 1);
  assert.equal(w.localStorage.getItem(key()), 'secret');
  w.close();
});

test('timed cutoff freezes editing but serializes code, notes and metadata; failure offers retry and copy', () => {
  const template = readFileSync(new URL('../../templates/problem.html', import.meta.url), 'utf8');
  const script = template.split('{% if interview_mode %}\n<script>')[1].split('</script>')[0]
    .replace('{{ problem.time_bucket }}', '0').replace('{{ problem.phase_budgets | tojson }}', '{}');
  const dom = new JSDOM(`<body><div class="problem__head"></div><div id="interview-timer"></div><form id="solve-form"><textarea name="code">partial code</textarea><textarea name="notes_md">partial notes</textarea><input name="time_per_phase_json" value='{"plan":9}'><input id="cutoff_bool" name="cutoff_bool" value="0"><button id="run-tests-btn">run</button></form></body>`, {runScripts:'outside-only'});
  const w = dom.window;
  const intervals = [];
  w.setInterval = fn => {intervals.push(fn); return intervals.length;};
  w.clearInterval = () => {};
  let submissions = 0;
  w.htmx = {trigger: () => {submissions++;}};
  w.eval(script);
  intervals[0]();
  const form = w.document.querySelector('form');
  const data = new w.FormData(form);
  assert.equal(data.get('code'), 'partial code');
  assert.equal(data.get('notes_md'), 'partial notes');
  assert.equal(data.get('time_per_phase_json'), '{"plan":9}');
  assert.equal(data.get('cutoff_bool'), '1');
  assert.equal(form.inert, true);
  intervals[1](); intervals[1](); intervals[1]();
  assert.equal(submissions, 1);
  form.dispatchEvent(new w.CustomEvent('htmx:sendError'));
  const retry = w.document.querySelector('[data-cutoff-retry]');
  assert.ok(retry);
  assert.match(w.document.querySelector('[data-cutoff-copy]').textContent, /partial code/);
  assert.match(w.document.querySelector('[data-cutoff-copy]').textContent, /partial notes/);
  retry.click();
  assert.equal(submissions, 2);
  const parameters = {code:'late async change', unwanted:'late field'};
  form.dispatchEvent(new w.CustomEvent('htmx:configRequest', {detail:{parameters}}));
  assert.equal(parameters.code, 'partial code');
  assert.equal(parameters.notes_md, 'partial notes');
  assert.equal(parameters.unwanted, undefined);
  form.dispatchEvent(new w.CustomEvent('autosave:confirmed', {detail:{cutoff:false}}));
  assert.ok(w.document.querySelector('[data-cutoff-copy]'));
  form.dispatchEvent(new w.CustomEvent('autosave:confirmed', {detail:{cutoff:true}}));
  assert.equal(w.document.querySelector('[data-cutoff-copy]'), null);
  w.close();
});

test('submitting unchanged server text keeps an unresolved recovery copy', () => {
  const {w, form} = page({saved:'unresolved draft'});
  form.dispatchEvent(new w.Event('submit'));
  assert.equal(w.localStorage.getItem(key()), 'unresolved draft');
  w.close();
});
test('legacy unowned drafts are never restored into an authenticated form', () => {
  const {w, field} = page();
  w.localStorage.setItem('lisbench.autosave:/writings/7:writing-form:body_md', 'legacy secret');
  delete field.__autosaveAttached;
  field.value = '';
  w.document.dispatchEvent(new w.CustomEvent('htmx:afterSwap'));
  assert.equal(field.value, '');
  w.close();
});
test('malformed acknowledgement cannot remove a recovery copy', () => {
  const {w, edit} = page();
  edit('keep me');
  const script = w.document.createElement('script');
  script.dataset.autosaveConfirmed = '';
  script.textContent = '{not valid json';
  w.document.body.append(script);
  w.document.dispatchEvent(new w.CustomEvent('htmx:afterSwap'));
  assert.equal(w.localStorage.getItem(key()), 'keep me');
  w.close();
});
test('delete confirmation treats hostile titles as text and cancellation blocks submission', () => {
  const template = readFileSync(new URL('../../templates/writings_index.html', import.meta.url), 'utf8');
  const script = template.split('<script>')[1].split('</script>')[0];
  const dom = new JSDOM('<form data-confirm-delete></form>', {runScripts:'outside-only'});
  const {window:w} = dom;
  const form = w.document.querySelector('form');
  const title = `Li's "draft" \\ </script><script>window.compromised=true</script>`;
  form.dataset.confirmDelete = title;
  let prompt;
  w.confirm = value => {prompt = value; return false;};
  w.eval(script);
  const event = new w.Event('submit', {cancelable:true});
  form.dispatchEvent(event);
  assert.equal(event.defaultPrevented, true);
  assert.ok(prompt.endsWith(title));
  assert.equal(w.compromised, undefined);
  w.close();
});


test('unresolved recovery and newer current edits both survive reload until explicit choices', () => {
  const first = page({saved:'valuable unsaved recovery'});
  first.edit('server text plus a new edit');
  const storage = Object.fromEntries(Object.keys(first.w.localStorage).map(name => [name, first.w.localStorage.getItem(name)]));
  first.w.close();
  const second = page({storage});
  assert.equal(second.field.value, 'server text');
  const copies = Array.from(second.w.document.querySelectorAll('[data-autosave-recovery] pre')).map(node => node.textContent);
  assert.deepEqual(copies.sort(), ['server text plus a new edit', 'valuable unsaved recovery'].sort());
  // A further edit and another reload must not discard either pending choice.
  second.edit('third edit');
  const nextStorage = Object.fromEntries(Object.keys(second.w.localStorage).map(name => [name, second.w.localStorage.getItem(name)]));
  second.w.close();
  const third = page({storage:nextStorage});
  const panels = Array.from(third.w.document.querySelectorAll('[data-autosave-recovery]'));
  assert.equal(panels.length, 3);
  const original = panels.find(panel => panel.querySelector('pre').textContent === 'valuable unsaved recovery');
  original.querySelector('button').click();
  assert.equal(third.field.value, 'valuable unsaved recovery');
  assert.equal(third.w.document.querySelectorAll('[data-autosave-recovery]').length, 2);
  third.w.close();
});

test('discarding one pending copy preserves newer edits and other recoveries', () => {
  const first = page({saved:'original recovery'});
  first.edit('new work');
  first.w.document.querySelector('[data-autosave-recovery] button:last-child').click();
  assert.equal(first.w.localStorage.getItem(key()), 'new work');
  const storage = Object.fromEntries(Object.keys(first.w.localStorage).map(name => [name, first.w.localStorage.getItem(name)]));
  first.w.close();
  const second = page({storage});
  const copies = Array.from(second.w.document.querySelectorAll('[data-autosave-recovery] pre')).map(node => node.textContent);
  assert.deepEqual(copies, ['new work']);
  second.w.close();
});

test('persisting current edits never acknowledges an unresolved older copy', () => {
  for (const viaHtmx of [false, true]) {
    const first = page({saved:'unresolved older copy'});
    first.edit('current persisted edit');
    if (viaHtmx) first.ack('current persisted edit');
    const storage = Object.fromEntries(Object.keys(first.w.localStorage).map(name => [name, first.w.localStorage.getItem(name)]));
    first.w.close();
    const second = page({storage, server:'current persisted edit'});
    assert.equal(second.w.localStorage.getItem(key()), null);
    assert.equal(second.field.value, 'current persisted edit');
    const copies = Array.from(second.w.document.querySelectorAll('[data-autosave-recovery] pre')).map(node => node.textContent);
    assert.deepEqual(copies, ['unresolved older copy']);
    second.w.close();
  }
});
