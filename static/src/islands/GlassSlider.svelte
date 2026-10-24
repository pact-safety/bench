<script lang="ts">
  // FRONTEND-1b: the glassiness control. Live-tunes the two glass vars
  // on <html> while dragging (input) and persists on release (change)
  // via fetch to /settings/glass. The Jinja fallback is a plain range
  // input inside a form with a Save button — identical persistence,
  // no live preview.
  //
  // Derivations mirror base.html's server-side inline style so first
  // paint and live tuning can never disagree:
  //   alpha = 0.25 + 0.006 * level   (0.25 … 0.85; 50 → 0.55)
  //   blur  = 4 + 0.28 * level  px   (4 … 32;      50 → 18)
  let { level = 50 }: { level: number } = $props();

  let value = $state(level);
  let status = $state("");

  function apply(): void {
    const s = document.documentElement.style;
    s.setProperty("--glass-alpha", (0.25 + 0.006 * value).toFixed(2));
    s.setProperty("--glass-blur", `${Math.round(4 + 0.28 * value)}px`);
  }

  async function persist(): Promise<void> {
    status = "saving…";
    try {
      const body = new URLSearchParams({ glass_level: String(value) });
      const r = await fetch("/settings/glass", {
        method: "POST",
        headers: { "X-Requested-With": "fetch" },
        body,
      });
      status = r.ok ? "saved" : "couldn't save — try again";
    } catch {
      status = "couldn't save — try again";
    }
  }
</script>

<input
  id="glass-level"
  type="range"
  name="glass_level"
  min="0"
  max="100"
  step="5"
  bind:value
  oninput={apply}
  onchange={persist}
  aria-describedby="glass-level-status"
/>
<span id="glass-level-status" class="muted" aria-live="polite">
  {status || `${value} / 100`}
</span>
