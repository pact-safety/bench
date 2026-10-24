<script lang="ts">
  // FRONTEND-1d: Mira chat island — transcript + composer with the
  // lifted SSE reader and markdown-it (+[cite:] chips) for assistant
  // turns. The Jinja fallback is the previous server-rendered
  // transcript + inline vanilla reader, byte-for-byte behavior.
  //
  // a11y parity with the fallback: the transcript stays ONE polite
  // aria-live region; the composer keeps its label; send gets
  // aria-busy while streaming.
  import { renderMarkdown } from "../lib/markdown";
  import { readSseStream } from "../lib/sse";

  type Turn = { role: string; content: string };
  let { session_id, turns = [] }: { session_id: string; turns: Turn[] } =
    $props();

  let messages: Turn[] = $state(
    turns.filter((t) => t.role === "user" || t.role === "assistant"),
  );
  let draft = $state("");
  let streaming = $state(false);
  let transcript: HTMLElement;

  function scrollDown(): void {
    if (transcript) transcript.scrollTop = transcript.scrollHeight;
  }

  async function send(e: SubmitEvent): Promise<void> {
    e.preventDefault();
    const text = draft.trim();
    if (!text || streaming) return;

    messages.push({ role: "user", content: text });
    const reply: Turn = $state({ role: "assistant", content: "" });
    messages.push(reply);
    draft = "";
    streaming = true;
    scrollDown();

    const fd = new FormData();
    fd.append("session_id", session_id);
    fd.append("message", text);

    const finish = () => {
      streaming = false;
      scrollDown();
    };
    try {
      const resp = await fetch("/mira/turn", {
        method: "POST",
        body: fd,
        headers: { Accept: "text/event-stream" },
      });
      await readSseStream(resp, {
        onDelta: (t) => {
          reply.content += t;
          scrollDown();
        },
        onError: (msg) => {
          reply.content = msg;
          finish();
        },
        onDone: finish,
      });
    } catch {
      if (!reply.content) {
        reply.content =
          "Mira is unreachable right now. Your message was saved — try again in a moment.";
      }
      finish();
    }
  }
</script>

<div
  bind:this={transcript}
  class="mira-transcript"
  aria-live="polite"
  aria-label="Conversation with Mira"
  tabindex="0"
>
  {#each messages as turn}
    <div class="mira-msg mira-msg--{turn.role}">
      <span class="mira-msg__who">{turn.role === "user" ? "You" : "Mira"}</span>
      {#if turn.role === "assistant"}
        <!-- eslint-disable-next-line svelte/no-at-html-tags — renderMarkdown
             escapes raw HTML (html:false); this is the sanitize boundary -->
        <div class="mira-msg__body">{@html renderMarkdown(turn.content)}</div>
      {:else}
        <div class="mira-msg__body mira-msg__body--plain">{turn.content}</div>
      {/if}
    </div>
  {/each}
  {#if messages.length === 0}
    <p class="mira-empty">
      Ask Mira about an eval design, a paper, a research direction, or what
      to ship this week. They'll push back, ask the sharp question, and point
      at the specific thing that moves evidence.
    </p>
  {/if}
</div>

<form class="mira-composer" autocomplete="off" onsubmit={send}>
  <label class="visually-hidden" for="mira-message">Message to Mira</label>
  <textarea
    id="mira-message"
    name="message"
    rows="2"
    bind:value={draft}
    disabled={streaming}
    placeholder="What's the cheapest experiment that distinguishes this from the obvious alternative?"
  ></textarea>
  <div class="mira-composer__row">
    <span class="mira-composer__hint">they push back — that's the point</span>
    <button
      type="submit"
      class="btn btn--primary"
      disabled={streaming || !draft.trim()}
      aria-busy={streaming}
    >
      {streaming ? "Mira is thinking…" : "Send"}
    </button>
  </div>
</form>
