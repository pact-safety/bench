// Drafts stay in this tab and never leave the browser until normal form save.
(function () {
  "use strict";
  const root = document.querySelector("[data-mira-draft-user][data-mira-draft-context]");
  if (!root) return;
  const user = root.dataset.miraDraftUser;
  const context = root.dataset.miraDraftContext;
  if (!user || !context) return;
  const stages = ["frame", "attempt", "check", "reflect"];
  const keyFor = stage => "mira-coach-draft:v1:" + JSON.stringify([user, context, stage]);

  // Context stays stable when the first POST creates a session. Only exact
  // persisted text acknowledges a draft; a newer unsent edit must survive.
  const confirmed = root.querySelector("[data-mira-confirmed-drafts]");
  try {
    const records = confirmed ? JSON.parse(confirmed.textContent) : [];
    if (Array.isArray(records)) records.forEach(record => {
      if (!record || !stages.includes(record.stage) || typeof record.text !== "string") return;
      const key = keyFor(record.stage);
      if (sessionStorage.getItem(key) === record.text) sessionStorage.removeItem(key);
    });
  } catch (_) { /* Storage or malformed metadata must not block ordinary forms. */ }

  const form = root.querySelector("form[data-mira-draft-stage]");
  if (!form || !stages.includes(form.dataset.miraDraftStage)) return;
  const textarea = form.querySelector('textarea[name="message"]');
  if (!textarea) return;
  const key = keyFor(form.dataset.miraDraftStage);
  const status = form.querySelector("[data-mira-draft-status]");
  function announce(text) {
    // Avoid repeatedly announcing the same status on every keystroke.
    if (status && status.textContent !== text) status.textContent = text;
  }
  try {
    const saved = sessionStorage.getItem(key);
    if (textarea.value === "" && saved !== null && saved !== "") {
      textarea.value = saved;
      announce("Your unsaved draft was restored from this tab.");
    }
  } catch (_) { /* Server-returned text remains available without storage. */ }

  function remember() {
    try {
      sessionStorage.setItem(key, textarea.value);
      announce("Draft kept in this tab until you save it.");
    } catch (_) {
      announce("Draft storage is unavailable. Keep this page open until your note is saved.");
    }
  }
  textarea.addEventListener("input", remember);
  textarea.addEventListener("change", remember);
  // Submitting is not proof of persistence: failed requests retain the draft.
  form.addEventListener("submit", remember);
})();
