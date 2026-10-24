<script lang="ts">
  // FRONTEND-1e: the Compose editor as a bundled island.
  //
  // Port of the inline esm.sh CodeMirror script in problem.html — same
  // behaviors (textarea stays the form field and is synced on submit;
  // language radios swap the mode; theme toggle re-themes; the Plan
  // gate holds the editor read-only) — but the dependencies now ship
  // in OUR bundle: no CDN at runtime, so self-hosted and offline
  // installs get the editor too. The island mounts next to the
  // existing #code textarea, which remains the no-JS fallback.
  import { basicSetup, EditorView } from "codemirror";
  import { Compartment, EditorState } from "@codemirror/state";
  import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
  import { python } from "@codemirror/lang-python";
  import { rust } from "@codemirror/lang-rust";
  import { tags as t } from "@lezer/highlight";

  let mountEl: HTMLElement;

  const css = () => getComputedStyle(document.documentElement);
  const v = (name: string) => css().getPropertyValue(name).trim();
  const themeName = () =>
    document.documentElement.getAttribute("data-theme") ?? "dark";
  const isDark = () => themeName() === "dark";

  function colors() {
    // Dark keeps the shipped palette; every light-background theme
    // (light, hyperbolic's pearl) uses the deeper set — on the pearl
    // work-surface (--code-bg stays opaque by DS rule) these clear AA.
    return isDark()
      ? { keyword: "#a99cf4", string: "#a4c98a", number: "#d99c5a",
          comment: v("--text-alt-color"), builtin: "#b8a8f0" }
      : { keyword: "#5b3fe0", string: "#4a7d4a", number: "#b06b00",
          comment: v("--text-alt-color"), builtin: "#7860d0" };
  }
  function buildHighlight() {
    const c = colors();
    return HighlightStyle.define([
      { tag: t.keyword, color: c.keyword, fontWeight: "500" },
      { tag: [t.string, t.special(t.string)], color: c.string },
      { tag: [t.comment, t.lineComment, t.blockComment, t.docComment], color: c.comment, fontStyle: "italic" },
      { tag: [t.number, t.integer, t.float], color: c.number },
      { tag: t.atom, color: c.keyword },
      { tag: t.bool, color: c.keyword },
      { tag: t.standard(t.variableName), color: c.builtin },
    ]);
  }
  function buildTheme() {
    return EditorView.theme(
      {
        "&": { fontSize: "0.9375rem", backgroundColor: v("--code-bg"), color: v("--text-color"), border: "1px solid " + v("--border-color"), borderRadius: v("--radius-input") },
        "&.cm-focused": { outline: "none", borderColor: v("--brand-color") },
        ".cm-content": { caretColor: v("--brand-color"), fontFamily: v("--font-mono"), padding: "12px" },
        ".cm-gutters": { backgroundColor: v("--code-bg"), color: v("--text-alt-color"), border: "none", borderRight: "1px solid " + v("--border-color") },
        ".cm-activeLineGutter, .cm-activeLine": { backgroundColor: "transparent" },
        ".cm-selectionBackground, ::selection": { backgroundColor: v("--brand-color") + "33" },
      },
      { dark: isDark() },
    );
  }

  $effect(() => {
    const ta = document.getElementById("code") as HTMLTextAreaElement | null;
    if (!ta || !mountEl) return;

    const langC = new Compartment();
    const themeC = new Compartment();
    const hlC = new Compartment();

    const view = new EditorView({
      state: EditorState.create({
        doc: ta.value,
        extensions: [
          basicSetup,
          EditorView.updateListener.of((update) => {
            if (!update.docChanged) return;
            ta.value = update.state.doc.toString();
            ta.dispatchEvent(new Event("input", { bubbles: true }));
          }),
          langC.of(python()),
          themeC.of(buildTheme()),
          hlC.of(syntaxHighlighting(buildHighlight())),
        ],
      }),
      parent: mountEl,
    });
    ta.style.display = "none";
    mountEl.dataset.active = "1";

    const form = document.getElementById("solve-form");
    const onSubmit = () => { ta.value = view.state.doc.toString(); };
    form?.addEventListener("submit", onSubmit);
    form?.addEventListener("bench:freeze", onSubmit);
    // Recovery is an explicit user choice; mirror it into the visible editor.
    const onRecovery = () => {
      if (ta.value !== view.state.doc.toString()) {
        view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: ta.value } });
      }
    };
    ta.addEventListener("input", onRecovery);

    const radios = document.querySelectorAll<HTMLInputElement>('input[name="language"]');
    const onLang = (e: Event) => {
      const lang = (e.currentTarget as HTMLInputElement).value === "rust" ? rust() : python();
      view.dispatch({ effects: langC.reconfigure(lang) });
    };
    radios.forEach((el) => el.addEventListener("change", onLang));

    // Retheme when data-theme changes (the settings island / mirror
    // script mutate the attribute — observe it rather than a button).
    const mo = new MutationObserver(() => {
      view.dispatch({
        effects: [
          themeC.reconfigure(buildTheme()),
          hlC.reconfigure(syntaxHighlighting(buildHighlight())),
        ],
      });
    });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

    // Plan gate parity.
    const gate = document.getElementById("plan-gate");
    const applyGate = () => {
      const open = form?.dataset.cutoffLocked !== "1" && (!gate || gate.style.display === "none");
      view.contentDOM.contentEditable = open ? "true" : "false";
      view.dom.classList.toggle("cm-readonly", !open);
    };
    const cutoffMo = new MutationObserver(applyGate);
    if (form) cutoffMo.observe(form, { attributes: true, attributeFilter: ["data-cutoff-locked"] });
    let gateMo: MutationObserver | null = null;
    if (gate) {
      gateMo = new MutationObserver(applyGate);
      gateMo.observe(gate, { attributes: true, attributeFilter: ["style"] });
      applyGate();
    }

    return () => {
      form?.removeEventListener("submit", onSubmit);
      form?.removeEventListener("bench:freeze", onSubmit);
      ta.removeEventListener("input", onRecovery);
      cutoffMo.disconnect();
      radios.forEach((el) => el.removeEventListener("change", onLang));
      mo.disconnect();
      gateMo?.disconnect();
      view.destroy();
      ta.style.display = "";
    };
  });
</script>

<div bind:this={mountEl} class="compose-editor"></div>
