// bubbles.js — the ONLY client-side responsibility of the bubble system:
// Esc dismisses the strip currently on the page. Advancing, persistence, and
// rendering are HTMX + server. If this file grows a second job, the design
// has drifted — go back to the handoff README.
document.addEventListener("keydown", function (e) {
  if (e.key !== "Escape" || e.defaultPrevented) return;
  var strip = document.querySelector(".ob-bubble");
  if (!strip) return;
  var skip = strip.querySelector(".ob-bubble__close");
  if (!skip) return;
  // Do not steal an Escape a real dialog or the command palette wants.
  if (document.querySelector(".palette[open], dialog[open]")) return;
  skip.click();
});
