// Prototype variant switcher.
//
// Renders a fixed-position bar at the bottom of the screen with A/B/C
// pills. Reads `?variant=` from the URL, shows the matching variant,
// hides the others. Clicking a pill updates the URL + reveals/hides.
//
// Expects:
//   - Each variant block has class `variant variant--A` / variant--B / variant--C
//   - Body has data-variants="A,B,C" listing which variants exist
//
// No framework. ~50 lines. Delete with the prototype directory.

(function () {
  var qs = new URLSearchParams(window.location.search);
  var current = (qs.get('variant') || 'A').toUpperCase();
  var variants = (document.body.dataset.variants || 'A,B,C').split(',');

  function apply(variant) {
    variants.forEach(function (v) {
      var nodes = document.querySelectorAll('.variant--' + v);
      nodes.forEach(function (n) {
        n.hidden = (v !== variant);
      });
    });
    // Density is a token knob, not per-variant CSS. The compact
    // variant (C) flips html[data-density="compact"] which the
    // shared prototype.css picks up.
    if (variant === 'C') {
      document.documentElement.setAttribute('data-density', 'compact');
    } else {
      document.documentElement.removeAttribute('data-density');
    }
    document.querySelectorAll('.proto-switcher__pill').forEach(function (p) {
      p.classList.toggle('is-active', p.dataset.variant === variant);
    });
    // Update URL without reload.
    var url = new URL(window.location.href);
    url.searchParams.set('variant', variant);
    history.replaceState(null, '', url.toString());
    current = variant;
  }

  // Build the switcher bar.
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

  // Hint with the page title so the operator knows which surface this is.
  var note = document.createElement('span');
  note.className = 'proto-switcher__note';
  note.textContent = document.body.dataset.surface || '';
  bar.appendChild(note);

  document.body.appendChild(bar);
  apply(current);

  // Keyboard: 1/2/3 flip variants
  document.addEventListener('keydown', function (e) {
    if (e.target.matches('input, textarea, [contenteditable]')) return;
    if (e.key === '1') apply('A');
    if (e.key === '2') apply('B');
    if (e.key === '3') apply('C');
  });
})();
