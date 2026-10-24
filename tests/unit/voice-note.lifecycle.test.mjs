/**
 * Lifecycle tests for static/js/voice-note.js after the 2026-05-17
 * rewrite (MediaRecorder + POST to /api/transcribe replacing Chrome's
 * Web Speech API).
 *
 * Strategy: load the production JS into a sandboxed VM context with a
 * minimal fake DOM, fake MediaRecorder, fake navigator.mediaDevices,
 * and fake fetch. The test asserts UI state transitions and the
 * fetch payload shape directly — no headless browser needed.
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";


// ---------- Fake DOM ---------------------------------------------------------


class FakeClassList {
  constructor(owner) { this.owner = owner; }
  toggle(token, force) {
    const tokens = new Set((this.owner.className || "").split(/\s+/).filter(Boolean));
    if (force) tokens.add(token); else tokens.delete(token);
    this.owner.className = Array.from(tokens).join(" ");
  }
}

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.parentNode = null;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.className = "";
    this.classList = new FakeClassList(this);
    this.listeners = new Map();
    this.type = "";
    this.disabled = false;
    this.title = "";
    this.textContent = "";
    this.value = "";
    this.selectionStart = 0;
    this.selectionEnd = 0;
    this._labelNode = null;
    this._innerHTML = "";
  }

  appendChild(n) { n.parentNode = this; this.children.push(n); return n; }

  insertBefore(node, ref) {
    node.parentNode = this;
    if (!ref) { this.children.push(node); return node; }
    const i = this.children.indexOf(ref);
    if (i === -1) this.children.push(node);
    else this.children.splice(i, 0, node);
    return node;
  }

  get nextSibling() {
    if (!this.parentNode) return null;
    const i = this.parentNode.children.indexOf(this);
    return this.parentNode.children[i + 1] || null;
  }

  addEventListener(type, fn) {
    const arr = this.listeners.get(type) || [];
    arr.push(fn);
    this.listeners.set(type, arr);
  }

  dispatchEvent(evt) {
    const arr = this.listeners.get(evt.type) || [];
    for (const fn of arr) fn(evt);
    return true;
  }

  setAttribute(n, v) { this.attributes[n] = String(v); }
  getAttribute(n) { return this.attributes[n] ?? null; }
  setSelectionRange(s, e) { this.selectionStart = s; this.selectionEnd = e; }

  set innerHTML(v) {
    this._innerHTML = v;
    const m = v.match(/voice-note-btn__label['"]>([^<]*)</);
    if (m) this._labelNode = { textContent: m[1] };
  }
  get innerHTML() { return this._innerHTML; }

  querySelector(sel) {
    if (sel === ".voice-note-btn__label") return this._labelNode;
    return null;
  }
}

class FakeDocument {
  constructor(textareas) {
    this.readyState = "complete";
    this._textareas = textareas;
    this.listeners = new Map();
  }
  addEventListener(t, fn) {
    const arr = this.listeners.get(t) || [];
    arr.push(fn);
    this.listeners.set(t, arr);
  }
  createElement(t) { return new FakeElement(t); }
  querySelectorAll(sel) {
    if (sel === "textarea[data-voice-note]") return this._textareas.slice();
    return [];
  }
}


// ---------- Fake MediaRecorder + mediaDevices --------------------------------


class FakeBlob {
  constructor(parts, opts) {
    this.parts = parts;
    this.type = (opts && opts.type) || "";
    this.size = (opts && opts.size != null) ? opts.size : (parts.join("").length);
  }
}

class FakeMediaRecorder {
  static instances = [];
  static isTypeSupported(_mime) { return true; }

  constructor(stream, opts) {
    this.stream = stream;
    this.mimeType = (opts && opts.mimeType) || "audio/webm";
    this.state = "inactive";
    this.listeners = new Map();
    this.startCalls = 0;
    this.stopCalls = 0;
    FakeMediaRecorder.instances.push(this);
  }

  addEventListener(t, fn) {
    const arr = this.listeners.get(t) || [];
    arr.push(fn);
    this.listeners.set(t, arr);
  }

  start() { this.state = "recording"; this.startCalls += 1; }

  stop() {
    this.state = "inactive";
    this.stopCalls += 1;
    // Synthesize the data + stop events the real API fires.
    this._emit("dataavailable", { data: new FakeBlob(["aud"], { type: this.mimeType, size: 3 }) });
    this._emit("stop", {});
  }

  emit(type, payload = {}) { this._emit(type, payload); }

  _emit(type, payload) {
    const arr = this.listeners.get(type) || [];
    for (const fn of arr) fn({ type, ...payload });
  }
}

class FakeFormData {
  constructor() { this._fields = []; }
  append(name, value, filename) { this._fields.push({ name, value, filename }); }
}

class FakeMediaStream {
  constructor() { this.tracks = [{ stop: () => { this._stopped = true; } }]; }
  getTracks() { return this.tracks; }
}


// ---------- Boot harness ------------------------------------------------------


function makeDefaultMediaDevices() {
  return {
    getUserMedia: () => Promise.resolve(new FakeMediaStream()),
    enumerateDevices: () => Promise.resolve([]),
  };
}


async function bootVoiceNote({ mediaDevices, fetchImpl } = {}) {
  FakeMediaRecorder.instances.length = 0;

  const container = new FakeElement("div");
  const textarea = new FakeElement("textarea");
  textarea.value = "";
  container.appendChild(textarea);
  const document = new FakeDocument([textarea]);

  const fetchCalls = [];
  const defaultFetch = function (url, init) {
    fetchCalls.push({ url, init });
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ text: "transcribed text" }),
    });
  };

  const ctx = {
    window: { location: { search: "?vn_quiet=1" } },
    document,
    navigator: {
      userAgent: "node-test",
      language: "en-US",
      onLine: true,
      cookieEnabled: true,
      mediaDevices: mediaDevices || makeDefaultMediaDevices(),
    },
    MediaRecorder: FakeMediaRecorder,
    Blob: FakeBlob,
    FormData: FakeFormData,
    Event: typeof Event !== "undefined" ? Event : class {
      constructor(type, init) { this.type = type; this.bubbles = !!(init && init.bubbles); }
    },
    fetch: fetchImpl || defaultFetch,
    setTimeout,
    clearTimeout,
    console: { log() {}, warn() {} },
  };

  vm.createContext(ctx);
  const here = path.dirname(fileURLToPath(import.meta.url));
  const src = readFileSync(path.resolve(here, "../../static/js/voice-note.js"), "utf8");
  vm.runInContext(src, ctx, { filename: "voice-note.js" });

  await new Promise((r) => setTimeout(r, 0));

  return {
    container,
    textarea,
    button: container.children[1],
    status: container.children[2],
    fetchCalls,
    recorders: FakeMediaRecorder.instances,
  };
}


async function flushMicrotasks() {
  // Multiple turns cover: getUserMedia → recorder events → fetch → response.
  for (let i = 0; i < 6; i++) {
    await new Promise((r) => setTimeout(r, 0));
  }
}


// ---------- Tests -------------------------------------------------------------


test("click → recording starts; getUserMedia + MediaRecorder.start fire", async () => {
  const env = await bootVoiceNote();

  env.button.dispatchEvent({ type: "click" });
  await flushMicrotasks();

  assert.equal(env.recorders.length, 1, "one recorder constructed");
  assert.equal(env.recorders[0].startCalls, 1, "recorder.start() called once");
  assert.equal(env.button.getAttribute("aria-pressed"), "true");
  assert.equal(
    env.button.querySelector(".voice-note-btn__label").textContent,
    "Stop & transcribe"
  );
});


test("click → click stops recorder, POSTs blob, inserts returned text at cursor", async () => {
  const env = await bootVoiceNote();
  env.textarea.value = "before";
  env.textarea.selectionStart = env.textarea.selectionEnd = env.textarea.value.length;

  env.button.dispatchEvent({ type: "click" }); // start
  await flushMicrotasks();
  env.button.dispatchEvent({ type: "click" }); // stop
  await flushMicrotasks();

  // POST fired.
  assert.equal(env.fetchCalls.length, 1, "fetch called once");
  assert.equal(env.fetchCalls[0].url, "/api/transcribe");
  assert.equal(env.fetchCalls[0].init.method, "POST");
  assert.equal(env.fetchCalls[0].init.credentials, "same-origin");

  // Body is FormData with the audio blob.
  const fd = env.fetchCalls[0].init.body;
  assert.equal(fd._fields.length, 1);
  assert.equal(fd._fields[0].name, "audio");
  assert.equal(fd._fields[0].filename, "dictation.webm");

  // Transcript landed in the textarea.
  assert.equal(env.textarea.value, "before transcribed text");
  // Button returns to idle.
  assert.equal(env.button.getAttribute("aria-pressed"), "false");
});


test("server returns 429 → status surfaces cap-reached message; no text inserted", async () => {
  const env = await bootVoiceNote({
    fetchImpl: () => Promise.resolve({
      ok: false,
      status: 429,
      json: () => Promise.resolve({
        error: "transcription_cap_reached",
        detail: "Daily dictation budget reached. Resets at UTC midnight.",
      }),
    }),
  });
  env.textarea.value = "untouched";
  env.textarea.selectionStart = env.textarea.selectionEnd = env.textarea.value.length;

  env.button.dispatchEvent({ type: "click" });
  await flushMicrotasks();
  env.button.dispatchEvent({ type: "click" });
  await flushMicrotasks();

  assert.equal(env.textarea.value, "untouched", "no insertion on error");
  assert.match(env.status.textContent, /Daily dictation budget/);
});


test("getUserMedia rejection (permission denied) → friendly status, no recorder created", async () => {
  const denied = {
    getUserMedia: () => {
      const e = new Error("permission denied by user");
      e.name = "NotAllowedError";
      return Promise.reject(e);
    },
    enumerateDevices: () => Promise.resolve([]),
  };
  const env = await bootVoiceNote({ mediaDevices: denied });

  env.button.dispatchEvent({ type: "click" });
  await flushMicrotasks();

  assert.equal(env.recorders.length, 0, "no recorder when permission denied");
  assert.match(env.status.textContent, /[Mm]ic access denied/);
  assert.equal(env.button.getAttribute("aria-pressed"), "false");
});


test("empty transcript response → '(no speech detected)' status, textarea untouched", async () => {
  const env = await bootVoiceNote({
    fetchImpl: () => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ text: "   " }),  // whitespace only
    }),
  });
  env.textarea.value = "kept";
  env.textarea.selectionStart = env.textarea.selectionEnd = env.textarea.value.length;

  env.button.dispatchEvent({ type: "click" });
  await flushMicrotasks();
  env.button.dispatchEvent({ type: "click" });
  await flushMicrotasks();

  assert.equal(env.textarea.value, "kept");
  assert.match(env.status.textContent, /no speech detected/);
});


test("fetch network error → 'Network error' status, button re-enabled", async () => {
  const env = await bootVoiceNote({
    fetchImpl: () => Promise.reject(new Error("connection refused")),
  });

  env.button.dispatchEvent({ type: "click" });
  await flushMicrotasks();
  env.button.dispatchEvent({ type: "click" });
  await flushMicrotasks();

  assert.match(env.status.textContent, /Network error/);
  // Button is no longer locked in transcribing state.
  assert.equal(env.button.disabled, false);
});

test('append dictation preserves selected text and edits made while transcription is pending', async () => {
  let respond;
  const env = await bootVoiceNote({fetchImpl: () => new Promise(resolve => {respond = resolve;})});
  env.textarea.dataset.voiceNoteAppend = '';
  env.textarea.value = 'My original answer';
  env.textarea.selectionStart = 0; env.textarea.selectionEnd = 18;
  env.button.dispatchEvent({type:'click'}); await flushMicrotasks();
  assert.equal(env.textarea.dataset.voiceNoteBusy, '1');
  env.button.dispatchEvent({type:'click'}); await flushMicrotasks();
  env.textarea.value += ' plus typed correction';
  respond({ok:true,status:200,json:()=>Promise.resolve({text:'spoken addition'})});
  await flushMicrotasks();
  assert.equal(env.textarea.value, 'My original answer plus typed correction spoken addition');
  assert.equal(env.textarea.dataset.voiceNoteBusy, '0');
});

test('unavailable transcription clears busy state and preserves typing', async () => {
  const env = await bootVoiceNote({fetchImpl:()=>Promise.resolve({ok:false,status:502,json:()=>Promise.resolve({})})});
  env.textarea.value = 'Keep typing';
  env.button.dispatchEvent({type:'click'}); await flushMicrotasks();
  env.button.dispatchEvent({type:'click'}); await flushMicrotasks();
  assert.equal(env.textarea.value, 'Keep typing');
  assert.equal(env.textarea.dataset.voiceNoteBusy, '0');
  assert.match(env.status.textContent, /unavailable/);
  assert.equal(env.status.getAttribute('aria-live'), 'polite');
});
