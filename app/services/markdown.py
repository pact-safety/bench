"""Markdown rendering with Slack-style soft syntax highlighting.

Design constraint: not-blinding. We use Pygments to tokenize, but emit
the smallest set of token classes the CSS in static/css/main.css cares
about: keywords, strings, comments, numbers. Everything else falls back
to body text. The result reads like Slack's tinted-block style — a
touch of color, no IDE rainbow.

Code fences with no language hint default to Python, which is the
overwhelming majority of code in the problem corpus.
"""

from __future__ import annotations

import mistune
from markupsafe import Markup
from pygments import highlight
from pygments.formatters.html import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound


_FORMATTER = HtmlFormatter(nowrap=True, classprefix="hl-")
_DEFAULT_LANG = "python"


def _highlight(code: str, lang: str | None) -> str:
    name = (lang or _DEFAULT_LANG).strip().lower() or _DEFAULT_LANG
    try:
        lexer = get_lexer_by_name(name, stripall=False)
    except ClassNotFound:
        lexer = get_lexer_by_name(_DEFAULT_LANG)
    body = highlight(code, lexer, _FORMATTER).rstrip("\n")
    return f'<pre class="code-block"><code class="lang-{name}">{body}</code></pre>'


class _SoftRenderer(mistune.HTMLRenderer):
    def block_code(self, code: str, info: str | None = None, **kwargs) -> str:
        return _highlight(code, info)


# escape=False so authored content (readings, exercises, problem
# prompts) can include inline HTML — specifically <details>/<summary>
# blocks for "reveal answer" affordances on exercises. All markdown
# rendered here comes from author-controlled files, never user input.
_md = mistune.create_markdown(
    renderer=_SoftRenderer(escape=False),
    plugins=["strikethrough", "table"],
)


def render_markdown(text: str | None) -> Markup:
    if not text:
        return Markup("")
    return Markup(_md(text))


def render_code(text: str | None, lang: str = "python") -> Markup:
    if not text:
        return Markup("")
    return Markup(_highlight(text, lang))
