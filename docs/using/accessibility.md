# Accessibility

What's implemented, how to turn it on, and what is still weak. The last section
is the honest one.

## The three toggles

`/settings` → Accessibility. Each writes to `users.settings_json.a11y` and sets
a `data-*` attribute on `<html>` before paint, so there is no flash of the
wrong state on load.

| Toggle | Attribute | Effect |
|---|---|---|
| Reduce motion | `data-reduce-motion` | Stops every animation and transition in the app |
| Larger text | `data-larger-text` | Raises the base type scale; layout reflows rather than clipping |
| High contrast | `data-high-contrast` | Removes glass and blur, restores opaque surfaces, thickens focus rings |

**Reduce motion** is also honoured without the toggle: the app respects your
operating system's `prefers-reduced-motion` setting. The toggle exists so you
can ask for stillness in bench specifically without changing your OS.

Both switches are enforced in one global block in `static/css/motion.css`
rather than per component, which is why a newly added animation cannot forget
to have an off-switch — and why the style gate fails a `@keyframes` that has no
matching off-switch.

**High contrast** is the reason the theme system has an indirection layer at
all. Components read `--panel-fill` / `--panel-blur` rather than glass tokens
directly, so a single override at the `[data-high-contrast]` scope makes every
translucent surface in the app opaque at once. See
[Themes](../THEMES.md) and [Design tokens](../architecture/tokens.md).

## Baked in, not optional

These hold regardless of your settings:

- **Every form input has an associated `<label>`.** Not a placeholder standing
  in for one.
- **Focus is always visible.** Focus rings come from a `--focus-ring` token,
  and get thicker and brand-coloured under high contrast.
- **Asynchronous updates announce themselves.** Anything that swaps in without
  a page load — hint slots, HTMX swaps, the feedback widget — sits in an ARIA
  live region.
- **Work surfaces stay opaque in every theme.** Code blocks, the compose
  editor, reading panes and the Mira transcript never take a translucent fill,
  even in the glass theme, because text you are working in must not sit on a
  moving background.
- **Not-yet-live controls are marked.** Tabs for features that aren't built
  carry `aria-disabled="true"` rather than looking clickable.
- **The page never scrolls sideways.** Wide content scrolls inside its own
  container.

## Themes and contrast

Two themes ship: a dark default and "hyperbolic", a light glass theme. Both are
built from the same tokens, so the difference between them is colour and
translucency, never layout. If a theme is hard to read, high contrast is the
switch to reach for — it applies in both.

## Where it's still weak

Stated because a checklist that only lists wins isn't an accessibility
statement:

- **No formal WCAG audit has been done.** The invariants above are enforced by
  convention and a style gate, not verified against a conformance standard.
  Treat this page as a description of intent and implementation, not a
  conformance claim.
- **Screen-reader testing has been informal.** The semantics are there —
  server-rendered HTML, landmarks, labels, live regions — but the app has not
  been walked end to end with NVDA, JAWS or VoiceOver.
- **Keyboard coverage is not proven exhaustive.** Everything is a real link,
  button or input, so it should all be reachable, but "should" is doing work in
  that sentence. The command palette (`⌘K`) is keyboard-first by design.
- **Colour is sometimes doing work alone.** Skill-axis charts distinguish axes
  primarily by colour.
- **The audio surfaces assume you can hear.** Read-aloud and speak-and-grade
  are additive — every one of them has a text path — but they are not captioned
  equivalents.

If something is unusable for you, that is a bug and it will get priority over
whatever is queued. Send it through the feedback widget or open an issue.

## Related

- [Settings](settings.md)
- [Design tokens](../architecture/tokens.md)
- [UI style guide](../STYLEGUIDE.md)
