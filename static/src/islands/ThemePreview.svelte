<script lang="ts">
  // The FRONTEND-1a proving island: the /settings theme <select>,
  // enhanced with a live preview — changing the selection applies the
  // theme to <html> immediately so you see the chamber (or dark)
  // before committing. Saving still goes through the surrounding
  // server form; on abandon, the server-rendered truth wins on next
  // load. Fallback (pre-hydration / no-JS) is the identical plain
  // select — zero behavior lost.
  //
  // a11y: the label association is preserved via the same id the Jinja
  // fallback used; no motion introduced, so the reduce-motion toggle
  // has nothing to collapse here.
  type ThemeRow = [key: string, label: string, blurb: string];
  let { themes = [], current = "" }: { themes: ThemeRow[]; current: string } =
    $props();

  let selected = $state(current);

  function preview(): void {
    const d = document.documentElement;
    if (selected) d.setAttribute("data-theme", selected);
    else d.removeAttribute("data-theme"); // dark default = no attribute
  }
</script>

<select
  id="theme-select"
  name="theme"
  class="settings__input"
  bind:value={selected}
  onchange={preview}
>
  {#each themes as [key, label, blurb]}
    <option value={key}>{label} — {blurb}</option>
  {/each}
</select>
<span class="muted" aria-live="polite">
  {#if selected !== current}previewing — Save to keep it{/if}
</span>
