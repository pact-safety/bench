import source from '../../js/palette.js?raw';
import { afterEach, describe, expect, it, vi } from 'vitest';

let teardown = () => {};
afterEach(() => teardown());

function setup(admin = false, signedIn = true) {
  teardown();
  document.body.innerHTML = `<button data-palette-trigger>Jump</button><a id="outside" href="/">Outside</a>
    <div id="palette" hidden data-admin="${admin}" data-signed-in="${signedIn}">
      <input class="palette__input"><ul id="palette-results" class="palette__list"></ul><p class="palette__empty" hidden></p>
    </div>`;
  HTMLElement.prototype.scrollIntoView = () => {};
  const controller = new AbortController();
  const addListener = document.addEventListener.bind(document);
  vi.spyOn(document, 'addEventListener').mockImplementation((type, listener) => {
    addListener(type, listener, { signal: controller.signal });
  });
  teardown = () => { controller.abort(); vi.restoreAllMocks(); };
  window.eval(source);
  const trigger = document.querySelector<HTMLButtonElement>('[data-palette-trigger]')!;
  trigger.focus();
  trigger.click();
  const input = document.querySelector<HTMLInputElement>('input')!;
  const key = (name: string, shiftKey = false) => input.dispatchEvent(new KeyboardEvent('keydown', { key: name, shiftKey, bubbles: true, cancelable: true }));
  return { doc: document, trigger, input, key };
}

describe('navigation palette', () => {
  it('names the generic next step accurately and includes visible destinations', () => {
    const { doc } = setup();
    const text = doc.querySelector('.palette__list')!.textContent;
    expect(text).toContain('Continue next step');
    expect(text).not.toContain('Pick a problem');
    expect(text).toContain('Papers');
    expect(text).toContain('Signal');
    expect(text).toContain('Mira');
    expect(text).not.toContain('Feedback inbox');
  });

  it('offers admin and signed-in destinations only to those users', () => {
    expect(setup(true).doc.querySelector('.palette__list')!.textContent).toContain('Feedback inbox');
    const { doc } = setup(false, false);
    expect(doc.querySelector('.palette__list')!.textContent).not.toContain('Mira');
    expect(doc.querySelector('.palette__list')!.textContent).not.toContain('Feedback inbox');
  });

  it('keeps keyboard focus inside and exposes the selected result', () => {
    const { doc, input, key, trigger } = setup();
    expect(key('Tab')).toBe(false);
    expect(key('Tab', true)).toBe(false);
    expect(doc.activeElement).toBe(input);
    key('ArrowDown');
    const active = doc.getElementById(input.getAttribute('aria-activedescendant') || '');
    expect(active?.getAttribute('aria-selected')).toBe('true');
    expect(active?.textContent).toContain('Continue next step');
    input.value = 'no-such-destination';
    input.dispatchEvent(new Event('input'));
    expect(input.hasAttribute('aria-activedescendant')).toBe(false);
    key('Escape');
    expect(doc.activeElement).toBe(trigger);
    expect(doc.getElementById('palette')!.hidden).toBe(true);
  });
});
