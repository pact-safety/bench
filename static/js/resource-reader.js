(function () {
  "use strict";
  function init() {
    var panel = document.getElementById("resource-reader");
    if (!panel || panel.dataset.ready) return;
    panel.dataset.ready = "1";
    var frame = panel.querySelector("iframe");
    var heading = panel.querySelector("[data-resource-heading]");
    var original = panel.querySelector("[data-resource-original]");
    var close = panel.querySelector("[data-resource-close]");
    var active = null;
    var reflection = null;

    function hide() {
      panel.hidden = true;
      if (active) active.setAttribute("aria-expanded", "false");
      // Keep the browsing context alive so returning to this source keeps its place.
      if (reflection || active) (reflection || active).focus();
    }

    function open(link) {
      if (active === link && !panel.hidden) { hide(); return; }
      if (active) active.setAttribute("aria-expanded", "false");
      var scope = link.closest(".learning-section, [data-resource-scope]");
      reflection = scope && scope.querySelector("[data-resource-reflection]");
      var ancestor = link.parentElement;
      while (ancestor) {
        if (ancestor.tagName === "DETAILS") ancestor.open = true;
        ancestor = ancestor.parentElement;
      }
      if (active !== link) {
        var host = link.closest("p, li") || link;
        if (host.tagName === "LI") host.append(panel);
        else host.after(panel);
        // Only server-approved links carry this attribute; query strings cannot supply a URL.
        frame.setAttribute("src", link.dataset.resourceReader);
      }
      active = link;
      frame.title = link.dataset.resourceTitle || link.textContent.trim();
      heading.textContent = frame.title;
      original.href = link.href;
      close.textContent = reflection ? "Hide source and reflect" : "Hide source";
      link.setAttribute("aria-expanded", "true");
      panel.hidden = false;
      heading.focus();
    }

    document.querySelectorAll("a[data-resource-reader]").forEach(function (link) {
      link.setAttribute("role", "button");
      link.setAttribute("aria-controls", panel.id);
      link.setAttribute("aria-expanded", "false");
      link.addEventListener("click", function (event) {
        if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        open(link);
      });
      link.addEventListener("keydown", function (event) {
        if (event.key === " " && !event.metaKey && !event.ctrlKey && !event.altKey && !event.shiftKey) {
          event.preventDefault();
          open(link);
        }
      });
    });
    close.addEventListener("click", hide);
    var read = new URLSearchParams(window.location.search).get("read");
    if (read && /^\d+$/.test(read)) {
      var requested = document.getElementById("section-" + read);
      var link = requested && requested.querySelector("a[data-resource-reader]");
      if (link) open(link);
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
