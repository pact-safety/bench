import source from '../../js/mira-coach.js?raw';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const key = (user = 'learner-a', context = '{"kind":"track","slug":"ml4good","section":11}', stage = 'frame') =>
  'mira-coach-draft:v1:' + JSON.stringify([user, context, stage]);
const defaultContext = '{"kind":"track","slug":"ml4good","section":11}';

function page({ user = 'learner-a', context = defaultContext, stage = 'frame', draft = '', confirmed = [] as {stage: string, text: string}[], form = true } = {}) {
  document.body.innerHTML = `<article data-mira-draft-user="" data-mira-draft-context="">
    <script type="application/json" data-mira-confirmed-drafts></script>
    ${form ? '<form data-mira-draft-stage=""><textarea name="message"></textarea><p data-mira-draft-status role="status"></p></form>' : ''}
  </article>`;
  const article = document.querySelector<HTMLElement>('article')!;
  article.dataset.miraDraftUser = user;
  article.dataset.miraDraftContext = context;
  document.querySelector('[data-mira-confirmed-drafts]')!.textContent = JSON.stringify(confirmed);
  const textarea = document.querySelector<HTMLTextAreaElement>('textarea');
  if (textarea) {
    textarea.value = draft;
    document.querySelector<HTMLElement>('form')!.dataset.miraDraftStage = stage;
  }
  window.eval(source);
  return textarea;
}

beforeEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

describe('Mira tab drafts', () => {
  it('saves input and restores it when returning to an empty form', () => {
    const textarea = page()!;
    textarea.value = 'My prediction <script> is still mine';
    textarea.dispatchEvent(new Event('input'));
    expect(sessionStorage.getItem(key())).toBe(textarea.value);
    expect(page()!.value).toBe('My prediction <script> is still mine');
  });

  it('preserves drafts on submit and restores after a failed request', () => {
    const textarea = page()!;
    textarea.value = 'Keep this if the request fails';
    document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
    expect(sessionStorage.getItem(key())).toBe(textarea.value);
    expect(page()!.value).toBe('Keep this if the request fails');
  });

  it('does not overwrite a server-returned validation or stale-tab draft', () => {
    sessionStorage.setItem(key(), 'Older local thinking');
    expect(page({ draft: 'Server returned unsaved thinking' })!.value).toBe('Server returned unsaved thinking');
    expect(sessionStorage.getItem(key())).toBe('Older local thinking');
  });

  it('clears only exact persisted text, including after new-session creation', () => {
    sessionStorage.setItem(key(), 'Saved frame');
    sessionStorage.setItem(key('learner-a', defaultContext, 'attempt'), 'Unsent next move');
    const textarea = page({ stage: 'attempt', confirmed: [{ stage: 'frame', text: 'Saved frame' }] })!;
    expect(sessionStorage.getItem(key())).toBeNull();
    expect(textarea.value).toBe('Unsent next move');
  });

  it('keeps different unsent text when the server confirms an older note', () => {
    sessionStorage.setItem(key(), 'Newer unsent frame');
    expect(page({ confirmed: [{ stage: 'frame', text: 'Older saved frame' }] })!.value).toBe('Newer unsent frame');
  });

  it('does not leak drafts across users, exercises, or stages', () => {
    sessionStorage.setItem(key(), 'Private learner-a frame');
    expect(page({ user: 'learner-b' })!.value).toBe('');
    expect(page({ context: '{"kind":"problem","slug":"other"}' })!.value).toBe('');
    expect(page({ stage: 'reflect' })!.value).toBe('');
    expect(sessionStorage.getItem(key())).toBe('Private learner-a frame');
  });

  it('acknowledges the final persisted stage without needing another form', () => {
    sessionStorage.setItem(key('learner-a', defaultContext, 'reflect'), 'My reflection');
    page({ form: false, confirmed: [{ stage: 'reflect', text: 'My reflection' }] });
    expect(sessionStorage.getItem(key('learner-a', defaultContext, 'reflect'))).toBeNull();
  });

  it('degrades to the ordinary form when storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('full'); });
    expect(() => {
      const textarea = page({ draft: 'My note' })!;
      textarea.dispatchEvent(new Event('input'));
      expect(document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))).toBe(true);
      expect(textarea.value).toBe('My note');
    }).not.toThrow();
  });
});
