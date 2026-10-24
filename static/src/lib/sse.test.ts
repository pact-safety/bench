// The SSE reader's frame contract (FRONTEND-1d) — same behaviors the
// inline mira.html reader had, now testable.
import { describe, expect, it, vi } from "vitest";
import { readSseStream } from "./sse";
import { renderMarkdown } from "./markdown";

function respFrom(frames: string[]): Response {
  const enc = new TextEncoder();
  const stream = new ReadableStream({
    start(c) {
      frames.forEach((f) => c.enqueue(enc.encode(f)));
      c.close();
    },
  });
  return { body: stream } as unknown as Response;
}

function handlers() {
  return { onDelta: vi.fn(), onError: vi.fn(), onDone: vi.fn() };
}

describe("readSseStream", () => {
  it("parses JSON deltas and terminates on done", async () => {
    const h = handlers();
    await readSseStream(
      respFrom(['data: "Hel"\n\n', 'data: "lo"\n\nevent: done\ndata: \n\n']),
      h,
    );
    expect(h.onDelta.mock.calls.map((c) => c[0])).toEqual(["Hel", "lo"]);
    expect(h.onDone).toHaveBeenCalledOnce();
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("routes error frames and stops", async () => {
    const h = handlers();
    await readSseStream(
      respFrom(["event: error\ndata: Conversation not found.\n\n"]),
      h,
    );
    expect(h.onError).toHaveBeenCalledWith("Conversation not found.");
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it("handles frames split across network chunks", async () => {
    const h = handlers();
    await readSseStream(respFrom(['data: "spl', 'it"\n\nevent: done\ndata: \n\n']), h);
    expect(h.onDelta).toHaveBeenCalledWith("split");
  });

  it("skips malformed frames without dying", async () => {
    const h = handlers();
    await readSseStream(
      respFrom(["data: {not json\n\n", 'data: "ok"\n\nevent: done\ndata: \n\n']),
      h,
    );
    expect(h.onDelta.mock.calls.map((c) => c[0])).toEqual(["ok"]);
  });

  it("signals done when the stream closes without a done frame", async () => {
    const h = handlers();
    await readSseStream(respFrom(['data: "x"\n\n']), h);
    expect(h.onDone).toHaveBeenCalledOnce();
  });
});

describe("renderMarkdown", () => {
  it("escapes raw HTML (the XSS boundary)", () => {
    const out = renderMarkdown('<script>alert(1)</script>');
    expect(out).not.toContain("<script>");
    expect(out).toContain("&lt;script&gt;");
  });

  it("renders [cite:doc_id] as a source chip", () => {
    const out = renderMarkdown("See [cite:sharma-2023] for the setup.");
    expect(out).toContain('class="tag mira-cite"');
    expect(out).toContain('data-doc="sharma-2023"');
  });

  it("renders markdown structure", () => {
    const out = renderMarkdown("**bold** and `code`");
    expect(out).toContain("<strong>bold</strong>");
    expect(out).toContain("<code>code</code>");
  });
});
