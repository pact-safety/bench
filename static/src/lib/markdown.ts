// Markdown rendering for Mira turns (FRONTEND-1d).
//
// html:false means raw HTML in model output is ESCAPED — that's the
// XSS boundary; keep it. The [cite:doc_id] plugin runs after render:
// because everything is escaped, any literal `[cite:...]` in the HTML
// can only have come from the model's plain text, so a regex swap for
// the source chip is safe.
import MarkdownIt from "markdown-it";

const md = new MarkdownIt({ html: false, linkify: true, breaks: true });

const CITE = /\[cite:([A-Za-z0-9_-]+)\]/g;

export function renderMarkdown(src: string): string {
  return md
    .render(src)
    .replace(
      CITE,
      '<span class="tag mira-cite" data-doc="$1" title="Source: $1">$1</span>',
    );
}
