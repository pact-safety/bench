// Variant switcher + per-variant view-toggle wiring.
// Keys 1/2/3 flip variants. Each variant has its OWN toggle for
// rail↔timeline; the per-variant toggle wires up on init.
(function () {
  var qs = new URLSearchParams(window.location.search);
  var current = (qs.get('variant') || 'D').toUpperCase();
  var variants = (document.body.dataset.variants || 'D,E,F').split(',');

  function apply(v) {
    variants.forEach(function (vv) {
      document.querySelectorAll('.variant--' + vv).forEach(function (n) {
        n.hidden = (vv !== v);
      });
    });
    document.querySelectorAll('.proto-switcher__pill').forEach(function (p) {
      p.classList.toggle('is-active', p.dataset.variant === v);
    });
    var url = new URL(window.location.href);
    url.searchParams.set('variant', v);
    history.replaceState(null, '', url.toString());
    current = v;
  }

  // Build switcher bar
  var bar = document.createElement('div');
  bar.className = 'proto-switcher';
  bar.setAttribute('role', 'tablist');
  bar.setAttribute('aria-label', 'Variant switcher');
  var label = document.createElement('span');
  label.className = 'proto-switcher__label';
  label.textContent = 'variant';
  bar.appendChild(label);
  variants.forEach(function (v) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'proto-switcher__pill';
    btn.dataset.variant = v;
    btn.setAttribute('role', 'tab');
    btn.textContent = v;
    btn.addEventListener('click', function () { apply(v); });
    bar.appendChild(btn);
  });
  var note = document.createElement('span');
  note.className = 'proto-switcher__note';
  note.textContent = document.body.dataset.surface || '';
  bar.appendChild(note);
  document.body.appendChild(bar);
  apply(current);

  document.addEventListener('keydown', function (e) {
    if (e.target.matches('input, textarea, [contenteditable]')) return;
    if (e.key === '1') apply('D');
    if (e.key === '2') apply('E');
    if (e.key === '3') apply('F');
  });

  // Wire per-variant view toggles. Each variant has [data-view-toggle]
  // controls that flip the variant's display-mode via a data-mode
  // attribute on the variant root.
  document.querySelectorAll('[data-view-toggle]').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      var target = btn.dataset.viewToggle;  // "rail" or "timeline"
      var root = btn.closest('.variant');
      if (!root) return;
      root.dataset.mode = target;
      // Update pressed state on sibling toggles in this variant
      root.querySelectorAll('[data-view-toggle]').forEach(function (b) {
        b.setAttribute('aria-pressed', b.dataset.viewToggle === target ? 'true' : 'false');
        b.classList.toggle('is-active', b.dataset.viewToggle === target);
      });
    });
  });
})();
