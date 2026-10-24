// Island registry — the single Vite entry chunk (FRONTEND-1a).
//
// One `mount()` call per island. Components are dynamic imports, so
// each island is its own code-split chunk and only downloads when its
// mount point is present on the page. Later phases append here:
//   mount("glass-slider", () => import("./GlassSlider.svelte"));  // 1b
//   mount("mcq-flow",     () => import("./McqFlow.svelte"));      // 1c
//   mount("mira-chat",    () => import("./MiraChat.svelte"));     // 1d
import { mount } from "./mount";

mount("theme-preview", () => import("./ThemePreview.svelte"));
mount("glass-slider", () => import("./GlassSlider.svelte")); // 1b
mount("mcq-flow", () => import("./McqFlow.svelte")); // 1c
mount("mira-chat", () => import("./MiraChat.svelte")); // 1d
mount("compose-editor", () => import("./ComposeEditor.svelte")); // 1e
