"""External-reading capture helpers.

When the user pastes a URL into /library/add, this module:
  1. Fetches the page (reusing the same UA + httpx pattern as the JD
     ingest, since LessWrong / arxiv / substack tend to gate naive
     fetchers).
  2. Strips it to plain text.
  3. Asks Claude Haiku to derive: a tight title, the best-fitting
     subset of the scheduler's axes, and a 2-3 sentence summary the
     user can keep or replace in the notes field.

Why a separate module from jds.py: JD parse fits a domain-specific
shape (axis weights as numerics, org extraction). External readings
need the same up-front fetch but a simpler downstream parse — just
axes + summary, no scoring vector. Sharing the HTML strip but
splitting the LLM call keeps each prompt focused.

Fallback is graceful: on any failure (network, parse, JSON error),
return None and the caller renders the empty form. The user can
still fill it in manually.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
from typing import Any

# Reuse the HTML→text helper from jds. It's already battle-tested
# against the same set of pathological career-page renderers.
from .jds import _strip_tags_to_text


_DEFAULT_MODEL = os.environ.get(
    "ANTHROPIC_PARSE_MODEL", os.environ.get("ANTHROPIC_MODEL_HAIKU", "claude-haiku-4-5")
)


_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 5


def _public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast or "%" in value:
        return False
    # Translation/tunnel addresses can conceal a private IPv4 destination.
    if isinstance(address, ipaddress.IPv6Address):
        return not (
            address.ipv4_mapped or address.sixtofour or address.teredo
            or address in ipaddress.ip_network("64:ff9b::/96")
            or address in ipaddress.ip_network("64:ff9b:1::/48")
        )
    return True


async def _fetch_html(url: str, timeout: float) -> str | None:
    import httpx

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; LisBench/1.0; +https://github.com/libearden)",
        "Accept": "text/html,application/xhtml+xml,text/plain",
        # Reject unexpected encodings below so decompression cannot evade the cap.
        "Accept-Encoding": "identity",
    }
    for hop in range(_MAX_REDIRECTS + 1):
        if len(url) > 8192 or any(ord(char) < 32 or ord(char) == 127 for char in url):
            return None
        target = httpx.URL(url)
        if target.scheme not in {"http", "https"} or not target.host or target.userinfo:
            return None
        host = target.host
        if "%" in host:
            return None
        port = target.port or (443 if target.scheme == "https" else 80)
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            answers = await asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM,
            )
            addresses = [answer[4][0] for answer in answers]
        else:
            addresses = [str(literal)]
        if not addresses or not all(_public_ip(address) for address in addresses):
            return None
        # Connect to the validated numeric address, never resolve the hostname
        # again. Host and TLS SNI/certificate verification still use its name.
        pinned = target.copy_with(host=addresses[0])
        authority = target.netloc.decode("ascii")
        # A fresh client per hop also prevents cookie/connection reuse across
        # different hostnames that happen to share the same pinned address.
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, trust_env=False, headers=headers,
        ) as client:
            async with client.stream(
                "GET", pinned, headers={"Host": authority},
                extensions={"sni_hostname": host},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location or hop == _MAX_REDIRECTS:
                        return None
                    url = str(target.join(location))
                    continue
                if not 200 <= response.status_code < 300:
                    return None
                encoding = response.headers.get("content-encoding", "identity").strip().lower()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if encoding != "identity" or content_type not in {
                    "", "text/html", "application/xhtml+xml", "text/plain",
                }:
                    return None
                length = response.headers.get("content-length")
                if length is not None and not 0 <= int(length) <= _MAX_RESPONSE_BYTES:
                    return None
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                        return None
                    body.extend(chunk)
                return httpx.Response(200, headers=response.headers, content=bytes(body)).text
    return None


async def fetch_body(url: str, *, timeout: float = 8.0) -> dict[str, Any] | None:
    """Fetch URL → return {title, source_text, page_title, meta} or None.

    Only public HTTP(S) destinations are fetched. The total network
    deadline includes DNS, every redirect, headers, and streamed content.
    """
    try:
        html = await asyncio.wait_for(_fetch_html(url, timeout), timeout=timeout)
        if not html:
            return None
        body_text, meta, page_title = _strip_tags_to_text(html)
    except Exception:
        return None
    if len(body_text) < 200:
        return None
    return {
        "page_title": page_title,
        "meta": meta,
        "source_text": body_text[:30000],
    }


_SYSTEM_PROMPT = """You categorize external readings/videos for an
interview-prep platform that schedules content by competency axis.

You will receive: the page title, the URL, and the first ~30k chars
of the page body. You return JSON ONLY, no preface.

Shape (every key is required):

{
  "title":   "tight 2-8 word display title — usually a cleaned-up
              version of the page title with marketing chrome removed",
  "source":  "the publication / author / org if obvious from the page
              (LessWrong, arXiv, Anthropic, etc.); empty string if
              ambiguous — never invent",
  "axes":    ["axis_key_1", "axis_key_2", ...] — pick 1-4 axes from
             the list provided in the user message. Match conservatively:
             a piece about transformer internals tags
             ["transformer_internals"], not also ["evaluation"].
  "summary_md": "2-3 sentence summary in plain prose. Should
                 contextualize what the piece argues, NOT just describe
                 its topic. The user will read this to remember why
                 they queued it."
}

Hard rules:
- Use ONLY axes from the provided list — don't invent new ones.
- Never include a JSON wrapper, markdown fence, or commentary.
- If the content is too thin to summarize honestly, return summary_md = "" rather than fabricating.
"""


def parse_with_claude(
    url: str,
    fetched: dict[str, Any],
    valid_axes: list[str],
    *,
    model: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any] | None:
    """Call Haiku with the fetched body. Returns the parsed JSON dict
    or None on any error (including a spend-cap hit, which surfaces as
    just another None so the caller's existing fallback runs)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        return None

    from . import spend_cap
    if spend_cap.over_cap_for(user_id, "parse_url"):
        return None

    from . import llm_keys
    client = llm_keys.client_for(user_id)
    user_msg = (
        f"URL: {url}\n\n"
        f"Page title: {fetched.get('page_title') or ''}\n\n"
        f"Allowed axes (use only these): {', '.join(valid_axes)}\n\n"
        f"Body:\n{fetched.get('source_text') or ''}"
    )
    try:
        resp = client.messages.create(
            model=model or _DEFAULT_MODEL,
            max_tokens=600,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        spend_cap.record_usage_for(user_id, resp, service="parse_url")
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        # The prompt asks for JSON only, but Haiku sometimes wraps in
        # a code fence. Strip if present.
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        parsed = json.loads(text)
    except Exception:
        return None

    # Defensive: filter axes against the allowed list, cap length.
    raw_axes = parsed.get("axes") or []
    if not isinstance(raw_axes, list):
        raw_axes = []
    parsed["axes"] = [a for a in raw_axes if isinstance(a, str) and a in valid_axes][:4]
    parsed["title"] = str(parsed.get("title") or "").strip()[:200]
    parsed["source"] = str(parsed.get("source") or "").strip()[:80]
    parsed["summary_md"] = str(parsed.get("summary_md") or "").strip()[:1200]
    return parsed
