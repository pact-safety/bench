<script lang="ts">
  // FRONTEND-1c: progressive MCQ flow for the assessment route.
  //
  // Select → Commit → (brief locked-in beat) → reveal → submit. The
  // server contract is untouched: commit POSTs the same form fields
  // (question_id, answer_index) to /assess/{run}/answer and follows the
  // redirect, exactly like the Jinja fallback's radio form. What the
  // island adds is deliberate commitment — you pick, you confirm, you
  // can't twitch-click through the assessment — plus the 4a reveal
  // beat: scoring is axis-weighted (no right/wrong), so the honest
  // reveal is "what this answer feeds" — the axes the question touches.
  // Auto-advances after ~1.6s, or immediately on Continue.
  //
  // a11y: options are real radio inputs in a fieldset (label-associated,
  // arrow-key navigable); the reveal is announced via a persistent
  // aria-live region and Continue takes focus when it appears. Under
  // reduce-motion there is no auto-advance timer — Continue only.
  let {
    run_id,
    question_id,
    prompt,
    options = [],
    axes = [],
  }: {
    run_id: number;
    question_id: string;
    prompt: string;
    options: string[];
    axes: string[];
  } = $props();

  let selected: number | null = $state(null);
  let committing = $state(false);
  let revealed = $state(false);
  let submitted = false;
  let form: HTMLFormElement;
  let continueBtn: HTMLButtonElement | undefined = $state();

  $effect(() => {
    if (revealed) continueBtn?.focus();
  });

  function reducedMotion(): boolean {
    return (
      document.documentElement.hasAttribute("data-reduce-motion") ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function advance(): void {
    if (submitted) return;
    submitted = true;
    form.submit();
  }

  function commit(): void {
    if (selected === null || committing) return;
    committing = true; // locked-in beat, then the reveal
    setTimeout(() => {
      revealed = true;
      if (!reducedMotion()) setTimeout(advance, 1600);
    }, 250);
  }
</script>

<form
  bind:this={form}
  method="post"
  action="/assess/{run_id}/answer"
  class="assess__form"
>
  <input type="hidden" name="question_id" value={question_id} />

  <!-- progress lives in the page header (assess__head); rendering it
       here too duplicated the line for screen readers and sighted
       users alike (caught by the E2E's strict selector) -->

  <h2 class="assess__prompt">{prompt}</h2>

  <fieldset class="assess__options" style={committing ? "pointer-events: none; opacity: 0.7" : ""}>
    <legend class="screen-reader-text">Answer choices</legend>
    {#each options as text, i}
      <label class="assess__option" class:is-selected={selected === i}>
        <input
          type="radio"
          name="answer_index"
          value={i}
          bind:group={selected}
          required
        />
        <span class="assess__option-text">{text}</span>
      </label>
    {/each}
  </fieldset>

  <div class="assess__actions">
    <button
      type="button"
      class="primary"
      disabled={selected === null || committing}
      onclick={commit}
    >
      {committing ? "Locked in" : "Commit answer"}
    </button>
  </div>

  <!-- persistent aria-live region so the reveal is actually announced
       (regions injected at announce-time are unreliable in SRs) -->
  <div class="assess__reveal" aria-live="polite">
    {#if revealed}
      <p class="assess__reveal-line">
        Answer locked — this feeds your
        {#each axes as ax}<span class="tag">{ax}</span>{" "}{/each}signal.
      </p>
      <button
        bind:this={continueBtn}
        type="button"
        class="primary"
        onclick={advance}
      >
        Continue →
      </button>
    {/if}
  </div>
</form>
