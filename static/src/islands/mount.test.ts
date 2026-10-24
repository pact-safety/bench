// Vitest coverage for the island mount runtime (FRONTEND-1a).
// jsdom environment (configured in vite.config.ts).
import { beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "./mount";

// A minimal stand-in for a compiled Svelte component: the runtime only
// needs something svelte's `mount()` accepts — we fake at the loader
// boundary instead and assert on DOM effects.
vi.mock("svelte", () => ({
  mount: vi.fn((component: unknown, opts: { target: HTMLElement }) => {
    opts.target.appendChild(document.createTextNode("HYDRATED"));
  }),
}));

const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("mount()", () => {
  it("does not import the island when no mount point exists", () => {
    const loader = vi.fn();
    mount("absent", loader);
    expect(loader).not.toHaveBeenCalled();
  });

  it("hydrates a mount point, replacing the fallback", async () => {
    document.body.innerHTML =
      `<div data-island="x" data-props='{"n": 1}'>fallback</div>`;
    const loader = vi.fn().mockResolvedValue({ default: {} });

    mount("x", loader);
    await flush();

    const host = document.querySelector<HTMLElement>("[data-island=x]")!;
    expect(loader).toHaveBeenCalledOnce();
    expect(host.textContent).toBe("HYDRATED");
    expect(host.dataset.hydrated).toBe("1");
  });

  it("keeps the fallback when data-props is malformed JSON", async () => {
    document.body.innerHTML =
      `<div data-island="x" data-props='{broken'>fallback</div>`;
    const loader = vi.fn().mockResolvedValue({ default: {} });

    mount("x", loader);
    await flush();

    const host = document.querySelector<HTMLElement>("[data-island=x]")!;
    expect(host.textContent).toBe("fallback");
    expect(host.dataset.hydrated).toBeUndefined();
  });

  it("keeps the fallback when the island chunk fails to load", async () => {
    document.body.innerHTML = `<div data-island="x">fallback</div>`;
    const loader = vi.fn().mockRejectedValue(new Error("chunk 404"));

    mount("x", loader);
    await flush();

    const host = document.querySelector<HTMLElement>("[data-island=x]")!;
    expect(host.textContent).toBe("fallback");
    expect(host.dataset.hydrated).toBeUndefined();
  });

  it("hydrates every instance of the same island on a page", async () => {
    document.body.innerHTML =
      `<div data-island="x">a</div><div data-island="x">b</div>`;
    const loader = vi.fn().mockResolvedValue({ default: {} });

    mount("x", loader);
    await flush();

    const hosts = document.querySelectorAll<HTMLElement>("[data-island=x]");
    expect(hosts[0].textContent).toBe("HYDRATED");
    expect(hosts[1].textContent).toBe("HYDRATED");
  });
});
