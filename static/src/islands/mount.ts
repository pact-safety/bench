// Island mount runtime (FRONTEND-1a).
//
// Contract (see docs: Frontend Stack Spec, "Island mount convention"):
// the server renders `<div data-island="name" data-props='{...}'>` with
// real, legible fallback content inside. This module finds each mount
// point, lazy-loads the island's component (code-split per island —
// the loader is a dynamic import), and hydrates by REPLACING the
// fallback with the component. Props flow in via data-props JSON;
// mutations flow out through normal HTMX/fetch to server routes.
//
// Islands that fail to load or parse leave the fallback untouched —
// progressive enhancement means the server-rendered page is always the
// floor, never a blank div.

import { mount as svelteMount, type Component } from "svelte";

type Loader = () => Promise<{ default: Component }>;

export function mount(name: string, loader: Loader): void {
  const hosts = document.querySelectorAll<HTMLElement>(
    `[data-island="${name}"]`,
  );
  if (hosts.length === 0) return; // island not on this page — no import

  hosts.forEach(async (host) => {
    let props: Record<string, unknown> = {};
    const raw = host.dataset.props;
    if (raw) {
      try {
        props = JSON.parse(raw);
      } catch {
        console.warn(`[islands] bad data-props on ${name}; keeping fallback`);
        return;
      }
    }
    try {
      const mod = await loader();
      host.replaceChildren(); // drop the fallback only once we can hydrate
      svelteMount(mod.default, { target: host, props });
      host.dataset.hydrated = "1";
    } catch (err) {
      console.warn(`[islands] failed to hydrate ${name}:`, err);
    }
  });
}
