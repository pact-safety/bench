import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const template = readFileSync(new URL('../../templates/base.html', import.meta.url), 'utf8');
const script = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(match => match[1]).find(source => source.includes('var fab ='));

function setup(userId = 'user-a', storage = new Map()) {
  const elements = new Map();
  const doc = {activeElement: null, title: 'Page', addEventListener() {},
    documentElement: {dataset: {}, hasAttribute: () => false}};
  function element(id) {
    if (elements.has(id)) return elements.get(id);
    const listeners = new Map(), classes = new Set();
    const el = {id, value: '', files: [], checked: false, disabled: false, dataset: {feedbackUserId: userId},
      innerHTML: '', textContent: '', attributes: {},
      classList: {add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x)},
      addEventListener(name, cb) { const callbacks = listeners.get(name) || []; callbacks.push(cb); listeners.set(name, callbacks); },
      fire(name, detail = {}) { const event = {detail, target: el, prevented: false,
        preventDefault() { this.prevented = true; }};
        for (const cb of listeners.get(name) || []) cb(event);
        return event;
      },
      focus() { doc.activeElement = el; },
      setAttribute(name, value) { this.attributes[name] = value; },
      removeAttribute(name) { delete this.attributes[name]; },
      querySelector(selector) { return selector.includes('submit') ? element('submit-button') : null; },
    };
    elements.set(id, el); return el;
  }
  doc.getElementById = element;
  const window = {location: {pathname: '/library', search: '?token=secret-query'},
    innerWidth: 800, innerHeight: 600, devicePixelRatio: 1, __benchErrs: ['private error contains user text']};
  vm.runInNewContext(script, {document: doc, window, navigator: {userAgent: 'test-browser'},
    localStorage: {getItem: k => storage.get(k), setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k)}});
  return {el: element, storage, doc};
}
function response(state, text = 'saved as feedback #4', status = 200) {
  state.el('fb-panel').fire('htmx:afterRequest', {successful: status >= 200 && status < 300,
    xhr: {status, responseText: text}});
}

test('confirmed save clears unchanged text', () => {
  const state = setup(); state.el('fb-body').value = 'sent';
  state.el('fb-panel').fire('htmx:beforeRequest'); response(state);
  assert.equal(state.el('fb-body').value, '');
});

test('successful login redirect is not a confirmed feedback save', () => {
  const state = setup(); state.el('fb-body').value = 'keep this';
  state.el('fb-panel').fire('htmx:beforeRequest'); response(state, '<html>Sign in</html>');
  assert.equal(state.el('fb-body').value, 'keep this');
});

test('edits and attachments added while sending survive success', () => {
  const state = setup(); state.el('fb-body').value = 'sent';
  state.el('fb-panel').fire('htmx:beforeRequest');
  state.el('fb-body').value = 'new draft'; state.el('fb-body').fire('input');
  state.el('fb-images').files = [{name: 'new.png'}]; state.el('fb-images').value = 'new.png';
  response(state);
  assert.equal(state.el('fb-body').value, 'new draft');
  assert.equal(state.storage.get('lisbench.fb.draft.user-a'), 'new draft');
  assert.equal(state.el('fb-images').value, 'new.png');
});

test('duplicate requests are rejected until completion, then retry works', () => {
  const state = setup();
  assert.equal(state.el('fb-panel').fire('htmx:beforeRequest').prevented, false);
  assert.equal(state.el('fb-panel').fire('htmx:beforeRequest').prevented, true);
  response(state, 'image too large — max 2 MB each', 400);
  assert.equal(state.el('fb-panel').fire('htmx:beforeRequest').prevented, false);
});

test('validation error explains recovery without discarding draft', () => {
  const state = setup(); state.el('fb-body').value = 'keep';
  state.el('fb-panel').fire('htmx:beforeRequest'); response(state, 'image too large — max 2 MB each', 400);
  assert.match(state.el('fb-status').textContent, /image too large/);
  assert.equal(state.el('fb-body').value, 'keep');
});

test('closing returns focus to the feedback trigger', () => {
  const state = setup(); state.el('fb-fab-open').fire('click'); state.el('fb-panel-close').fire('click');
  assert.equal(state.doc.activeElement, state.el('fb-fab-open'));
});

test('capture excludes URL query and raw error text even when diagnostics opted in', () => {
  const state = setup(); state.el('fb-diag').checked = true;
  const detail = {parameters: {body: 'report'}};
  state.el('fb-panel').fire('htmx:configRequest', detail);
  assert.equal(detail.parameters.url, '/library');
  assert.doesNotMatch(detail.parameters.body, /private error|secret-query/);
  assert.match(detail.parameters.body, /1/);
});

test('diagnostics are opt-in and body has an associated label', () => {
  assert.doesNotMatch(template, /id="fb-diag"[^>]*checked/);
  assert.match(template, /<label[^>]*for="fb-body"/);
});

test('network failure releases the send button and permits retry', () => {
  const state = setup(); state.el('fb-body').value = 'keep';
  state.el('fb-panel').fire('htmx:beforeRequest');
  assert.equal(state.el('submit-button').disabled, true);
  state.el('fb-panel').fire('htmx:sendError');
  assert.equal(state.el('submit-button').disabled, false);
  assert.equal(state.el('fb-body').value, 'keep');
  assert.equal(state.el('fb-panel').fire('htmx:beforeRequest').prevented, false);
});


test('draft storage is isolated across users and signed-out browsing', () => {
  const storage = new Map();
  const first = setup('user-a', storage);
  first.el('fb-body').value = 'User A private draft'; first.el('fb-body').fire('input');
  const second = setup('user-b', storage); second.el('fb-fab-open').fire('click');
  assert.equal(second.el('fb-body').value, '');
  const signedOut = setup('', storage); signedOut.el('fb-fab-open').fire('click');
  assert.equal(signedOut.el('fb-body').value, '');
  const returning = setup('user-a', storage); returning.el('fb-fab-open').fire('click');
  assert.equal(returning.el('fb-body').value, 'User A private draft');
});

test('unowned legacy draft is never restored or migrated into an account', () => {
  const storage = new Map([['lisbench.fb.draft', 'unknown owner private draft']]);
  const state = setup('user-a', storage); state.el('fb-fab-open').fire('click');
  assert.equal(state.el('fb-body').value, '');
  assert.equal(storage.has('lisbench.fb.draft.user-a'), false);
});
