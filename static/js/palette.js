// Command palette — WS5, 2026-05-28.
//
// Progressive enhancement on top of the hybrid nav (WS2 port). Opens
// on Cmd/Ctrl+K. The visible nav stays canonical; this is a faster
// path for the operator who knows where they want to go and would
// rather type than mouse.
//
// Pure vanilla JS. No framework, no build step. ~200 lines including
// keyboard handling. The commands array below is the source of truth
// for what's reachable via the palette — keep it in sync with the
// nav-group dropdowns in templates/base.html when adding routes.
//
// If the palette doesn't work, the visible nav still does. That's
// the progressive-enhancement contract.

(function () {
  "use strict";

  // ─── Command vocabulary ──────────────────────────────────────
  //
  // Each command is { label, url, hint, group }. label is what
  // the operator types to match; hint is the right-aligned grey
  // text (route or affordance); group is the eyebrow shown above
  // the first command in each group when the input is empty.
  //
  // Order within a group matches frequency-of-use intuition: most-
  // common first. Across groups: roughly the same order as the nav.
  const COMMANDS = [
    // Today
    { label: "Today",                url: "/",                    hint: "/",           group: "Today" },
    { label: "Continue next step",       url: "/today/next",          hint: "/today/next", group: "Today" },

    // Prep
    { label: "Warmup",               url: "/warmup",              hint: "/warmup",     group: "Prep" },
    { label: "Voices",               url: "/voices",              hint: "/voices",     group: "Prep" },
    { label: "Tracks",               url: "/tracks",              hint: "/tracks",     group: "Prep" },

    // Ingest
    { label: "Library",              url: "/library",             hint: "/library",    group: "Ingest" },
    { label: "Add to library",       url: "/library/add",         hint: "external",    group: "Ingest" },
    { label: "Papers", url: "/papers", hint: "/papers", group: "Ingest" },
    { label: "News",                 url: "/news",                hint: "/news",       group: "Ingest" },

    // Produce
    { label: "Writings",             url: "/writings",            hint: "/writings",   group: "Produce" },
    { label: "Decisions",            url: "/decisions",           hint: "/decisions",  group: "Produce" },
    { label: "Reflect",              url: "/reflect",             hint: "/reflect",    group: "Produce" },

    // Assess
    { label: "Aim — skills + JDs",   url: "/aim",                 hint: "/aim",        group: "Assess" },
    { label: "Readiness",            url: "/readiness",           hint: "/readiness",  group: "Assess" },
    { label: "Signal", url: "/signal", hint: "/signal", group: "Assess" },
    { label: "Focus",                url: "/focus",               hint: "/focus",      group: "Assess" },

    // Relationships
    { label: "Connecting",           url: "/connecting",          hint: "/connecting", group: "Relationships" },

    { label: "Mira", url: "/mira", hint: "/mira", group: "Coach", signedIn: true },

    // Settings + utility
    { label: "Settings",             url: "/settings",            hint: "/settings",   group: "Settings" },
    { label: "Feedback inbox",       url: "/feedback/inbox",      hint: "admin",       group: "Settings", admin: true },
  ];

  // ─── Setup ───────────────────────────────────────────────────
  // BEN-142 — in hyperfocus the palette narrows to the two moves that keep
  // you in the work. Filtering here rather than shipping a second command
  // list means a new command cannot forget to declare itself.
  const HYPERFOCUS_LABELS = ["Today", "Continue next step", "Settings"];
  const hyperfocus = document.documentElement.hasAttribute("data-hyperfocus");

  const overlay = document.getElementById("palette");
  if (!overlay) return;  // page didn't render the markup

  const input = overlay.querySelector(".palette__input");
  const listEl = overlay.querySelector(".palette__list");
  const empty = overlay.querySelector(".palette__empty");

  let activeIndex = 0;
  let currentResults = [];
  let previouslyFocused = null;

  // ─── Search ──────────────────────────────────────────────────
  //
  // Substring match against the label (case-insensitive). Ranks by
  // match position (earlier = better) then by label length (shorter
  // = better). Empty query returns the full set in command order so
  // the operator can browse on first open.
  function search(query) {
    const q = (query || "").trim().toLowerCase();
    // Narrow the whole surface in hyperfocus, not just the empty-query view,
    // so typing cannot reach past the filter.
    const pool = COMMANDS.filter(c =>
      (!c.admin || overlay.dataset.admin === "true") &&
      (!c.signedIn || overlay.dataset.signedIn === "true") &&
      (!hyperfocus || HYPERFOCUS_LABELS.indexOf(c.label) !== -1));
    if (!q) return pool.slice();
    const scored = [];
    for (const c of pool) {
      const lbl = c.label.toLowerCase();
      const idx = lbl.indexOf(q);
      if (idx === -1) continue;
      scored.push({ c, idx });
    }
    scored.sort((a, b) => a.idx - b.idx || a.c.label.length - b.c.label.length);
    return scored.map(s => s.c);
  }

  // ─── Render ──────────────────────────────────────────────────
  function render(results) {
    currentResults = results;
    listEl.innerHTML = "";
    input.removeAttribute("aria-activedescendant");
    if (results.length === 0) {
      listEl.hidden = true;
      empty.hidden = false;
      return;
    }
    listEl.hidden = false;
    empty.hidden = true;

    let lastGroup = null;
    const showGroups = !input.value.trim();  // only on empty query

    results.forEach((c, i) => {
      if (showGroups && c.group !== lastGroup) {
        const eyebrow = document.createElement("li");
        eyebrow.className = "palette__group";
        eyebrow.textContent = c.group;
        eyebrow.setAttribute("role", "presentation");
        listEl.appendChild(eyebrow);
        lastGroup = c.group;
      }
      const li = document.createElement("li");
      li.className = "palette__item";
      li.id = "palette-option-" + i;
      if (i === activeIndex) li.classList.add("is-active");
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", i === activeIndex ? "true" : "false");
      li.dataset.index = String(i);

      const label = document.createElement("span");
      label.className = "palette__item-label";
      label.textContent = c.label;
      li.appendChild(label);

      const hint = document.createElement("span");
      hint.className = "palette__item-hint";
      hint.textContent = c.hint;
      li.appendChild(hint);

      li.addEventListener("mouseenter", () => setActive(i));
      li.addEventListener("click", () => activate(c, false));
      listEl.appendChild(li);
    });
    setActive(activeIndex);
  }

  function setActive(i) {
    activeIndex = Math.max(0, Math.min(i, currentResults.length - 1));
    listEl.querySelectorAll(".palette__item").forEach((el, idx) => {
      const isActive = Number(el.dataset.index) === activeIndex;
      el.classList.toggle("is-active", isActive);
      el.setAttribute("aria-selected", isActive ? "true" : "false");
      if (isActive) {
        input.setAttribute("aria-activedescendant", el.id);
        el.scrollIntoView({ block: "nearest" });
      }
    });
  }

  function activate(cmd, newTab) {
    if (!cmd) return;
    closePalette();
    if (newTab) {
      window.open(cmd.url, "_blank", "noopener");
    } else {
      window.location.assign(cmd.url);
    }
  }

  // ─── Open / close ────────────────────────────────────────────
  function openPalette() {
    if (!overlay.hidden) return;
    previouslyFocused = document.activeElement;
    overlay.hidden = false;
    input.setAttribute("aria-expanded", "true");
    input.value = "";
    activeIndex = 0;
    render(search(""));
    input.focus();
  }

  function closePalette() {
    if (overlay.hidden) return;
    overlay.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    if (previouslyFocused && previouslyFocused.focus) {
      previouslyFocused.focus();
    }
  }

  // ─── Wire it up ──────────────────────────────────────────────
  document.addEventListener("keydown", function (e) {
    // Cmd+K (mac) / Ctrl+K (everyone else). Don't fire inside the
    // feedback panel — its own keyboard handler (Cmd+Enter to send)
    // should win when the user's typing there.
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      // Avoid the browser's "focus URL bar" default on Ctrl+K.
      e.preventDefault();
      if (overlay.hidden) openPalette();
      else closePalette();
      return;
    }
    if (overlay.hidden) return;

    if (e.key === "Tab") {
      // The combobox is this modal's only tab stop; options use arrow keys.
      e.preventDefault();
      input.focus();
    } else if (e.key === "Escape") {
      e.preventDefault();
      closePalette();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive(activeIndex + 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive(activeIndex - 1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      activate(currentResults[activeIndex], e.metaKey || e.ctrlKey);
    }
  });

  input.addEventListener("input", function () {
    activeIndex = 0;
    render(search(input.value));
  });

  // Click backdrop closes; click inside dialog doesn't.
  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) closePalette();
  });

  const navGroups = document.querySelectorAll("details.nav__group");
  navGroups.forEach(group => {
    group.addEventListener("keydown", e => {
      if (e.key === "Escape" && group.open) {
        e.preventDefault();
        group.open = false;
        group.querySelector("summary").focus();
      }
    });
  });
  document.addEventListener("click", e => {
    navGroups.forEach(group => {
      if (!group.contains(e.target)) group.open = false;
    });
  });

  // Also wire the visible ⌘K hint button in the nav.
  const trigger = document.querySelector("[data-palette-trigger]");
  if (trigger) {
    trigger.addEventListener("click", function (e) {
      e.preventDefault();
      openPalette();
    });
  }
})();
