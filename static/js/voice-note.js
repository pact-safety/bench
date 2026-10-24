/**
 * Voice notes — dictation into any textarea marked `data-voice-note`.
 *
 * Architecture (rewritten 2026-05-17, see operator's #80 → #88 → #90 trace)
 *   Previously used Chrome's Web Speech API (SpeechRecognition). That
 *   "client-side" API actually streams audio to speech.googleapis.com,
 *   which is unreachable in many privacy-extension / DNS-filtered
 *   browser environments. The operator's environment hits a
 *   deterministic `error: network` on every attempt. Not fixable
 *   client-side without compromising their extension setup.
 *
 *   The current approach: capture audio locally with MediaRecorder,
 *   POST the blob to our own backend (`/api/transcribe`), and insert
 *   the returned transcript at the cursor position. Audio never
 *   touches Google. Extension-immune.
 *
 *   Backend: `app/services/transcription.py` (Groq Whisper-Large-v3-
 *   Turbo, ~200-400ms latency, $0.001/min). Daily spend cap enforced
 *   server-side.
 *
 * UX
 *   Click mic → "Listening — tap mic again to stop and transcribe."
 *   Click again → "Transcribing…" while the POST is in flight,
 *   then the transcript appears at the cursor and the status clears.
 *   Errors surface in the status line with actionable copy.
 *
 * Tagging a textarea
 *   <textarea data-voice-note ...></textarea>
 *
 *   Optional `data-voice-note-label="..."` overrides the default
 *   "Dictate notes" caption on the mic button.
 *
 * Toggle diagnostic logging off via `?vn_quiet=1` URL flag.
 */

(function () {
  // ─── Diagnostic logging (issue #88, kept for ongoing observability) ──
  var DEBUG = (function () {
    try {
      return !/[?&]vn_quiet=1\b/.test(window.location.search || "");
    } catch (_) {
      return false;
    }
  })();

  function dbg() {
    if (!DEBUG) return;
    var d = new Date();
    var ts =
      String(d.getHours()).padStart(2, "0") + ":" +
      String(d.getMinutes()).padStart(2, "0") + ":" +
      String(d.getSeconds()).padStart(2, "0") + "." +
      String(d.getMilliseconds()).padStart(3, "0");
    var args = ["[voice-note " + ts + "]"].concat(
      Array.prototype.slice.call(arguments)
    );
    // eslint-disable-next-line no-console
    console.log.apply(console, args);
  }

  function dbgEnvironment() {
    var loc = {};
    try { loc.href = window.location.href; } catch (_) { loc.href = "(unavailable)"; }
    dbg("boot — env:", {
      userAgent: navigator.userAgent,
      language: navigator.language,
      online: navigator.onLine,
      cookieEnabled: navigator.cookieEnabled,
      doNotTrack: navigator.doNotTrack,
      url: loc.href,
      hasMediaDevices: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
      hasMediaRecorder: typeof MediaRecorder === "function",
    });
    if (navigator.permissions && navigator.permissions.query) {
      try {
        navigator.permissions
          .query({ name: "microphone" })
          .then(function (p) {
            dbg("permissions.microphone:", p.state);
            p.onchange = function () {
              dbg("permissions.microphone changed →", p.state);
            };
          })
          .catch(function (e) {
            dbg("permissions.query(microphone) rejected:", e.message);
          });
      } catch (e) {
        dbg("permissions.query threw:", e.message);
      }
    }
    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
      navigator.mediaDevices
        .enumerateDevices()
        .then(function (devices) {
          var mics = devices
            .filter(function (d) { return d.kind === "audioinput"; })
            .map(function (d) {
              return { label: d.label || "(label hidden — pre-grant)", deviceId: d.deviceId };
            });
          dbg("audioinput devices:", mics);
        })
        .catch(function (e) {
          dbg("enumerateDevices rejected:", e.message);
        });
    }
  }
  // ─────────────────────────────────────────────────────────────────

  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      // Defer one tick so the DOM-modifying code is still async-shaped
      // (matches the listener path's timing semantics).
      setTimeout(fn, 0);
    }
  }

  dbgEnvironment();

  var SUPPORTED = (
    typeof MediaRecorder === "function" &&
    navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === "function"
  );

  if (!SUPPORTED) {
    onReady(function () {
      var tagged = document.querySelectorAll("textarea[data-voice-note]");
      if (tagged.length === 0) {
        console.warn("[voice-note] no data-voice-note textareas found on this page");
      }
      tagged.forEach(function (ta) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "voice-note-btn voice-note-btn--disabled";
        btn.disabled = true;
        btn.title = "Voice notes require a browser with MediaRecorder (Chrome, Edge, Firefox, Safari ≥ 14).";
        btn.innerHTML = "🎙 <span class='voice-note-btn__label'>Voice unavailable</span>";
        ta.parentNode.insertBefore(btn, ta.nextSibling);
      });
    });
    return;
  }

  // Pick the best supported MIME for the browser. webm/opus is preferred
  // (Chrome / Firefox / Edge); Safari falls back to mp4. Empty string
  // means "let MediaRecorder pick its default."
  function pickMimeType() {
    if (typeof MediaRecorder.isTypeSupported !== "function") return "";
    var options = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/mp4;codecs=mp4a.40.2",
      "audio/mp4",
      "audio/ogg;codecs=opus",
    ];
    for (var i = 0; i < options.length; i++) {
      if (MediaRecorder.isTypeSupported(options[i])) return options[i];
    }
    return "";
  }

  // Whisper's auto-detection uses the file extension as a fallback when
  // the content-type is generic. Pair the recorded MIME with a
  // matching extension so the upstream never has to guess.
  function filenameFor(mime) {
    if (!mime) return "dictation.webm";
    if (mime.indexOf("webm") >= 0) return "dictation.webm";
    if (mime.indexOf("mp4") >= 0) return "dictation.m4a";
    if (mime.indexOf("ogg") >= 0) return "dictation.ogg";
    if (mime.indexOf("wav") >= 0) return "dictation.wav";
    return "dictation.webm";
  }

  function attach(textarea) {
    var label = textarea.dataset.voiceNoteLabel || "Dictate notes";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "voice-note-btn";
    btn.innerHTML = "🎙 <span class='voice-note-btn__label'>" + label + "</span>";
    btn.setAttribute("aria-pressed", "false");

    var status = document.createElement("span");
    status.className = "voice-note-status muted";
    status.setAttribute("aria-live", "polite");

    textarea.parentNode.insertBefore(btn, textarea.nextSibling);
    btn.parentNode.insertBefore(status, btn.nextSibling);

    var mediaStream = null;
    var mediaRecorder = null;
    var chunks = [];
    var recording = false;
    var transcribing = false;  // POST in flight
    var activeSessionId = 0;

    function reportBusy(on) {
      textarea.dataset.voiceNoteBusy = on ? "1" : "0";
      textarea.dispatchEvent(new Event("voice-note-state", { bubbles: true }));
    }

    function beginSession() {
      reportBusy(true);
      activeSessionId += 1;
      dbg("beginSession →", activeSessionId);
      return activeSessionId;
    }

    function invalidateSession() {
      reportBusy(false);
      activeSessionId += 1;
      dbg("invalidateSession → now", activeSessionId);
    }

    function isActiveSession(id) { return id === activeSessionId; }

    function setRecording(on) {
      recording = on;
      btn.classList.toggle("voice-note-btn--recording", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.querySelector(".voice-note-btn__label").textContent =
        on ? "Stop & transcribe" : label;
    }

    function setBusy(on) {
      // While transcribing the POST, button stays disabled so the user
      // can't fire off a new recording mid-request. Re-enables on
      // response (success or error) so retries are possible.
      btn.disabled = on;
    }

    function setStatus(text, opts) {
      status.textContent = text;
      if (opts && opts.autoClearMs) {
        setTimeout(function () {
          // Only clear if we haven't moved into another state since.
          if (status.textContent === text && !recording && !transcribing) {
            status.textContent = "";
          }
        }, opts.autoClearMs);
      }
    }

    function releaseMic() {
      if (mediaStream) {
        try {
          mediaStream.getTracks().forEach(function (t) { t.stop(); });
        } catch (_) {}
        mediaStream = null;
      }
    }

    function insertAtCursor(text) {
      if (!text) return;
      var start = typeof textarea.selectionStart === "number"
        ? textarea.selectionStart : textarea.value.length;
      var end = typeof textarea.selectionEnd === "number"
        ? textarea.selectionEnd : start;
      // Assessments append so selection or edits made during transcription
      // cannot discard an existing answer. Other voice-note fields retain
      // their established insert-at-selection behavior.
      if (textarea.dataset.voiceNoteAppend !== undefined) {
        start = end = textarea.value.length;
      }
      var before = textarea.value.slice(0, start);
      var after = textarea.value.slice(end);
      // Pad with spaces so dictated text doesn't slam into existing
      // characters. Only when needed (no double-space).
      var prefix = (before && !/\s$/.test(before)) ? " " : "";
      var suffix = (after && !/^\s/.test(after)) ? " " : "";
      var insert = prefix + text + suffix;
      textarea.value = before + insert + after;
      var caret = before.length + insert.length;
      if (typeof textarea.setSelectionRange === "function") {
        textarea.setSelectionRange(caret, caret);
      }
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    }

    function startRecording() {
      var sessionId = beginSession();
      navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
        if (!isActiveSession(sessionId)) {
          // User clicked stop before permission resolved.
          stream.getTracks().forEach(function (t) { t.stop(); });
          return;
        }
        mediaStream = stream;
        var mime = pickMimeType();
        try {
          mediaRecorder = mime
            ? new MediaRecorder(stream, { mimeType: mime })
            : new MediaRecorder(stream);
        } catch (e) {
          dbg("MediaRecorder constructor failed:", e.message);
          setStatus("Couldn't start recorder: " + e.message);
          releaseMic();
          invalidateSession();
          return;
        }
        chunks = [];

        mediaRecorder.addEventListener("dataavailable", function (evt) {
          if (evt.data && evt.data.size > 0) chunks.push(evt.data);
        });

        mediaRecorder.addEventListener("stop", function () {
          handleRecorderStop(sessionId);
        });

        mediaRecorder.addEventListener("error", function (evt) {
          dbg("recorder error:", evt && evt.error ? evt.error.name : "(unknown)");
          setStatus("Recorder error. Try again.", { autoClearMs: 3000 });
          setRecording(false);
          releaseMic();
          invalidateSession();
        });

        try {
          mediaRecorder.start();
          setRecording(true);
          setStatus("Listening — tap mic again to stop and transcribe.");
          dbg("session " + sessionId + " recording started mime=" + (mime || "(default)"));
        } catch (e) {
          dbg("recorder.start failed:", e.message);
          setStatus("Couldn't start recorder: " + e.message);
          releaseMic();
          invalidateSession();
        }
      }).catch(function (e) {
        dbg("getUserMedia denied:", e.name, e.message);
        if (e.name === "NotAllowedError" || e.name === "SecurityError") {
          setStatus("Mic access denied. Allow mic permission to dictate.");
        } else if (e.name === "NotFoundError") {
          setStatus("No microphone found on this device.");
        } else {
          setStatus("Couldn't access mic: " + e.message);
        }
        setRecording(false);
        invalidateSession();
      });
    }

    function handleRecorderStop(sessionId) {
      if (!isActiveSession(sessionId)) {
        dbg("session " + sessionId + " stop event ignored (stale)");
        releaseMic();
        return;
      }
      releaseMic();
      var mime = (mediaRecorder && mediaRecorder.mimeType) || "audio/webm";
      var blob = new Blob(chunks, { type: mime });
      chunks = [];
      dbg("session " + sessionId + " stopped — blob bytes=" + blob.size + " mime=" + mime);

      if (blob.size === 0) {
        setStatus("(no audio captured)", { autoClearMs: 2500 });
        invalidateSession();
        return;
      }

      transcribing = true;
      setBusy(true);
      setStatus("Transcribing…");

      var fd = new FormData();
      fd.append("audio", blob, filenameFor(mime));

      fetch("/api/transcribe", {
        method: "POST",
        body: fd,
        credentials: "same-origin",
      }).then(function (resp) {
        // Read the body even on error so we can surface the server's
        // detail message when present.
        return resp.json().then(function (data) {
          return { ok: resp.ok, status: resp.status, data: data };
        }).catch(function () {
          return { ok: resp.ok, status: resp.status, data: {} };
        });
      }).then(function (r) {
        if (!isActiveSession(sessionId)) {
          dbg("session " + sessionId + " transcribe response ignored (stale)");
          return;
        }
        transcribing = false;
        setBusy(false);
        if (!r.ok) {
          dbg("transcribe failed:", r.status, r.data);
          if (r.status === 429) {
            setStatus(r.data.detail || "Daily dictation budget reached. Try again tomorrow.", { autoClearMs: 6000 });
          } else if (r.status === 400) {
            setStatus(r.data.detail || "Audio invalid — try a longer recording.", { autoClearMs: 4000 });
          } else if (r.status === 502) {
            setStatus("Transcription service is unavailable. Try again in a moment.", { autoClearMs: 4000 });
          } else {
            setStatus("Transcription failed (" + r.status + ").", { autoClearMs: 4000 });
          }
          invalidateSession();
          return;
        }
        var text = ((r.data && r.data.text) || "").trim();
        if (!text) {
          setStatus("(no speech detected)", { autoClearMs: 2500 });
          invalidateSession();
          return;
        }
        insertAtCursor(text);
        setStatus("Transcribed.", { autoClearMs: 1800 });
        invalidateSession();
        dbg("session " + sessionId + " transcribed text_len=" + text.length);
      }).catch(function (e) {
        if (!isActiveSession(sessionId)) return;
        transcribing = false;
        setBusy(false);
        dbg("fetch error:", e.message);
        setStatus("Network error — couldn't reach transcription service. Try again.", { autoClearMs: 4000 });
        invalidateSession();
      });
    }

    function stopRecording() {
      setRecording(false);
      if (mediaRecorder && mediaRecorder.state !== "inactive") {
        try {
          mediaRecorder.stop();
          // The "stop" event will fire, which triggers the POST.
        } catch (e) {
          dbg("recorder.stop failed:", e.message);
          releaseMic();
          invalidateSession();
        }
      } else {
        // No active recorder — release any orphan stream and reset.
        releaseMic();
        invalidateSession();
      }
    }

    btn.addEventListener("click", function () {
      dbg("click — recording was:", recording, "transcribing:", transcribing);
      if (transcribing) return;  // ignore clicks while POST in flight
      if (recording) stopRecording();
      else startRecording();
    });
  }

  onReady(function () {
    var tagged = document.querySelectorAll("textarea[data-voice-note]");
    if (tagged.length === 0) {
      console.warn("[voice-note] no data-voice-note textareas found on this page");
      return;
    }
    console.log("[voice-note] attaching to " + tagged.length + " textarea(s)");
    tagged.forEach(attach);
  });
})();
