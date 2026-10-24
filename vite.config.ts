// FRONTEND-1a build seam. One entry (the island registry); hashed
// output + manifest into static/dist/ for the Jinja `asset()` helper.
// Islands code-split themselves via dynamic import in the registry.
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [svelte()],
  build: {
    manifest: true,
    outDir: "static/dist",
    rollupOptions: {
      input: "static/src/islands/index.ts",
    },
  },
  test: {
    environment: "jsdom",
    include: ["static/src/**/*.test.ts"],
  },
});
