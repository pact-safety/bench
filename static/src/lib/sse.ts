// SSE fetch-reader (FRONTEND-1d) — lifted from the inline reader in
// templates/mira.html, not rewritten: same frame contract (`data:`
// deltas as JSON strings, `event: done` terminal, `event: error`
// with a plain message), same buffered double-newline framing.
export interface SseHandlers {
  onDelta(text: string): void;
  onError(message: string): void;
  onDone(): void;
}

export async function readSseStream(
  resp: Response,
  h: SseHandlers,
): Promise<void> {
  if (!resp.body) throw new Error("no stream");
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const res = await reader.read();
    if (res.done) {
      h.onDone();
      return;
    }
    buffer += decoder.decode(res.value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let ev = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) ev = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (ev === "done") {
        h.onDone();
        return;
      }
      if (ev === "error") {
        h.onError(data);
        return;
      }
      try {
        h.onDelta(JSON.parse(data));
      } catch {
        /* malformed frame — skip, matching the inline reader */
      }
    }
  }
}
