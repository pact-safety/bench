// Browser recovery copies are account-scoped. A submit or a login page's
// HTTP 200 is not proof of persistence; only exact server text clears a copy.
(function () {
  "use strict";
  var PREFIX = "lisbench.autosave:v2:";
  function user() { return document.body.dataset.autosaveUser || ""; }
  function keyFor(field) {
    return PREFIX + JSON.stringify([user(), window.location.pathname,
      (field.form && field.form.id) || field.id || "anon", field.name || field.id || "field"]);
  }
  function confirmDrafts() {
    document.querySelectorAll("[data-autosave-confirmed]").forEach(function (node) {
      if (node.__ackRead) return;
      node.__ackRead = true;
      try {
        var ack = JSON.parse(node.textContent);
        if (!user() || ack.user !== user() || typeof ack.path !== "string" ||
            typeof ack.form !== "string" || !ack.fields || typeof ack.fields !== "object") return;
        Object.keys(ack.fields).forEach(function (name) {
          var value = ack.fields[name];
          var key = PREFIX + JSON.stringify([ack.user, ack.path, ack.form, name]);
          if (typeof value === "string" && localStorage.getItem(key) === value) localStorage.removeItem(key);
        });
        var form = document.getElementById(ack.form);
        if (form && ack.path === window.location.pathname) {
          form.dispatchEvent(new CustomEvent("autosave:confirmed", {detail: ack}));
        }
      } catch (_) { /* Malformed metadata must leave recovery copies intact. */ }
    });
  }
  function attach(field) {
    if (field.__autosaveAttached || !user()) return;
    field.__autosaveAttached = true;
    var owner = user();
    var key = keyFor(field);
    var recoveryKey = key + ":unresolved";
    var pending = [];
    function readPending() {
      var values = JSON.parse(localStorage.getItem(recoveryKey) || "[]");
      if (!Array.isArray(values) || values.some(function(value){ return typeof value !== "string"; })) throw new Error("Invalid recovery copies");
      return values;
    }
    function storePending(values) {
      if (values.length) localStorage.setItem(recoveryKey, JSON.stringify(values));
      else localStorage.removeItem(recoveryKey);
    }
    function protectPending() {
      // Reread before writing so another tab's unresolved copies survive too.
      var values = readPending();
      pending.forEach(function(value){ if (values.indexOf(value) === -1) values.push(value); });
      storePending(values);
    }
    function resolvePending(value) {
      storePending(readPending().filter(function(copy){ return copy !== value; }));
      pending = pending.filter(function(copy){ return copy !== value; });
    }
    var initial = field.value;
    var last = initial;
    var status = field.form && Array.from(field.form.querySelectorAll("[data-autosave-status]")).find(function (el) {
      return el.dataset.autosaveStatus === field.name;
    });
    if (!status) {
      status = document.createElement("span");
      status.className = "autosave-status muted";
      status.setAttribute("aria-live", "polite");
      field.after(status);
    }
    function say(text) { if (status.textContent !== text) status.textContent = text; }
    function remember() {
      if (user() !== owner) return;
      last = field.value;
      try {
        // A visible recovery choice must survive typing into current text.
        // Preserve it first; if storage is full, never overwrite the only copy.
        protectPending();
        // Empty text is also an unsaved edit (for example deleting a paragraph).
        localStorage.setItem(key, field.value);
        say("Recovery copy kept in this browser. Save to persist your work.");
      } catch (_) { say("Recovery storage unavailable. Keep this page open or copy your work before leaving."); }
    }
    try {
      pending = readPending();
      var saved = localStorage.getItem(key);
      if (saved !== null && field.hasAttribute("data-autosave-persisted") && saved === initial) {
        localStorage.removeItem(key);
      } else if (saved !== null && saved !== initial && pending.indexOf(saved) === -1) {
        pending.push(saved);
      }
      protectPending();
      pending.forEach(function(saved) {
        var recovery = document.createElement("details");
        recovery.dataset.autosaveRecovery = "";
        var summary = document.createElement("summary");
        summary.textContent = "Unsaved " + (field.name || "text") + " recovery copy available";
        var preview = document.createElement("pre");
        preview.textContent = saved;
        var restore = document.createElement("button");
        restore.type = "button";
        restore.className = "bordered-button";
        restore.textContent = "Use recovery copy";
        restore.addEventListener("click", function () {
          if (field.disabled || (field.form && field.form.dataset.cutoffLocked === "1") || user() !== owner) return;
          try { resolvePending(saved); } catch (_) {
            say("Recovery storage unavailable. Copy your work before leaving.");
            return;
          }
          field.value = saved;
          field.dispatchEvent(new Event("input", {bubbles: true}));
          recovery.remove();
          field.focus();
        });
        var discard = document.createElement("button");
        discard.type = "button";
        discard.className = "muted-button";
        discard.textContent = "Keep current text";
        discard.addEventListener("click", function () {
          if (user() !== owner) return;
          try {
            resolvePending(saved);
            if (localStorage.getItem(key) === saved) localStorage.removeItem(key);
          } catch (_) {
            say("Recovery storage unavailable. Copy your work before leaving.");
            return;
          }
          recovery.remove();
          say("Current text kept.");
        });
        recovery.append(summary, preview, restore, discard);
        status.after(recovery);
        say("An unsaved recovery copy is available below. Current text has been preserved.");
      });
    } catch (_) { say("Recovery storage unavailable. Keep this page open or copy your work before leaving."); }
    field.addEventListener("input", remember);
    field.addEventListener("change", remember);
    function flushChanged() { if (field.value !== last) remember(); }
    field.addEventListener("blur", flushChanged);
    if (field.form) {
      field.form.addEventListener("submit", flushChanged);
      field.form.addEventListener("autosave:confirmed", function(event) {
        if (event.detail.fields[field.name] === field.value) say("Saved.");
      });
    }
    window.addEventListener("pagehide", flushChanged);
  }
  function init() {
    confirmDrafts();
    document.querySelectorAll("textarea[data-autosave], input[data-autosave]").forEach(attach);
  }
  window.benchAutosave = {keyFor: keyFor};
  document.addEventListener("htmx:afterSwap", init);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
