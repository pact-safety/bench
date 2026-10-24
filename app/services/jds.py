"""JD parsing: text → {axis_weights, signal_tags, summary}.

Claude is preferred when ANTHROPIC_API_KEY is set. The keyword
fallback is deterministic and always available — useful for offline
testing and as a fallback path.

The output feeds two pieces of scheduler behavior:
- axis_weights bias the suggestion of next problems toward axes the
  JD emphasizes (works alongside the existing weak-axis logic);
- signal_tags overlap with problem.jd_signal_tags for a finer-grained
  alignment boost.

Stable signal taxonomy below. New signals can be added safely; old
ones must not be removed (problems reference them by string).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from . import assessment as assess_svc


_DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")


# Curated signal vocabulary. Multi-token keys are checked as substrings;
# single-word keys are checked as whole words. All comparisons are
# case-insensitive.
_SIGNAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "interpretability":      ("interpretability", "mechanistic interp", "feature visualization", "circuits"),
    "evals":                 ("evaluation", "eval suite", "benchmark", "calibration", "robustness eval", "red team"),
    "sycophancy":            ("sycophancy",),
    "rlhf":                  ("rlhf", "human feedback", "preference data", "reward model"),
    "alignment":             ("alignment", "safety", "ai safety", "honest", "harmless"),
    "transformer":           ("transformer", "attention", "self-attention"),
    "training":              ("pretrain", "fine-tun", "training run", "scaling"),
    "data_pipeline":         ("data pipeline", "preprocess", "ingestion", "dataloader"),
    "tokenization":          ("tokeniz", "bpe", "sentencepiece"),
    "rust":                  ("rust", "borrow", "cargo"),
    "inference":             ("inference", "throughput", "latency", "serving"),
    "interpretability_tools": ("activation patching", "probing", "saes"),
    "agents":                ("agent", "tool use", "scratchpad"),
    "robustness":            ("robustness", "adversarial", "out of distribution"),
    "research_engineering":  ("research engineer", "applied research"),
}


_AXIS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "transformer_internals":       ("transformer", "attention", "kv cache", "layernorm"),
    "training_mechanics":          ("training loop", "optimizer", "scheduler", "fine-tun", "checkpoint"),
    "sampling_decoding":           ("sampling", "decoding", "beam", "temperature", "top-k", "top-p"),
    "eval_design":                 ("eval", "benchmark", "metric", "calibration", "robustness"),
    "numerical_stability":         ("numerical", "fp16", "bf16", "overflow"),
    "debugging":                   ("debug", "regression", "incident", "root cause"),
    "tokenization":                ("tokeniz", "bpe", "sentencepiece"),
    "data_pipeline":               ("data pipeline", "preprocess", "ingestion"),
    "algorithmic":                 ("algorithm", "data structures", "complexity"),
    "rust_fluency":                ("rust", "cargo", "borrow"),
    # AI-safety axes. The Claude path will dominate when API key is
    # set, but the keyword fallback should still distinguish a
    # safety/alignment JD from a generic ML role.
    "ai_safety_fundamentals":      ("ai safety", "alignment", "rlhf", "constitutional ai",
                                    "harmlessness", "honest", "deceptive alignment",
                                    "sycophancy", "scalable oversight"),
    "mechanistic_interpretability": ("interpretability", "mechanistic interp", "feature visualization",
                                    "circuits", "sparse autoencoder", "saes", "activation patching",
                                    "probing"),
    "ai_governance_strategy":      ("governance", "policy", "agi strategy", "race-to-the-top",
                                    "risk landscape", "deployment policy", "responsible scaling",
                                    "compute governance"),
}


def _scan(text: str, table: dict[str, tuple[str, ...]]) -> dict[str, int]:
    """Return tag -> match count via substring scan (case-insensitive)."""
    lower = (text or "").lower()
    out: dict[str, int] = {}
    for tag, keys in table.items():
        count = 0
        for k in keys:
            count += lower.count(k.lower())
        if count > 0:
            out[tag] = count
    return out


def parse_keyword(source_text: str) -> dict[str, Any]:
    sig_matches = _scan(source_text, _SIGNAL_KEYWORDS)
    axis_matches = _scan(source_text, _AXIS_KEYWORDS)
    # Normalize axis counts to weights in [0, 1]: 1 mention → 0.4, 2 → 0.6, 3+ → 1.0.
    def _w(n: int) -> float:
        if n <= 0: return 0.0
        if n == 1: return 0.4
        if n == 2: return 0.6
        return 1.0
    axis_weights = {a: _w(axis_matches.get(a, 0)) for a in assess_svc.AXES}
    signal_tags = sorted(sig_matches.keys())
    strong = [a for a, w in axis_weights.items() if w >= 0.6]
    summary = (
        f"Keyword fallback. Emphasis on {', '.join(assess_svc.AXIS_LABELS.get(a, a) for a in strong[:3]) or '—'}. "
        f"Signal tags: {', '.join(signal_tags[:6]) or '—'}."
    )
    return {
        "axis_weights": axis_weights,
        "signal_tags": signal_tags,
        "summary": summary,
        # No keyword heuristic for iac yet — leave None so the
        # template can hide the block rather than show invented data.
        "iac_profile": None,
        "iac_evidence_md": None,
        "method": "keyword_fallback",
        "model_used": None,
    }


_SYSTEM_PROMPT = """You are reading a job description for a
research-engineering role (frontier lab, safety org, or fellowship)
and producing a structured competency profile.

Output JSON ONLY in this exact shape:

{
  "axis_weights": {
    "transformer_internals": 0.0..1.0,
    "training_mechanics": 0.0..1.0,
    "sampling_decoding": 0.0..1.0,
    "eval_design": 0.0..1.0,
    "numerical_stability": 0.0..1.0,
    "debugging": 0.0..1.0,
    "tokenization": 0.0..1.0,
    "data_pipeline": 0.0..1.0,
    "algorithmic": 0.0..1.0,
    "rust_fluency": 0.0..1.0,
    "ai_safety_fundamentals": 0.0..1.0,
    "mechanistic_interpretability": 0.0..1.0,
    "ai_governance_strategy": 0.0..1.0
  },
  "signal_tags": [string, ...],
  "summary": "two sentences describing what this role centrally wants",
  "iac_profile": {
    "iterator": 0.0..1.0,
    "amplifier": 0.0..1.0,
    "connector": 0.0..1.0
  },
  "iac_evidence_md": "short markdown citing the JD language that drove the iac_profile scores"
}

Guidance:
- axis_weights: 1.0 means "this is central to the role" — explicit
  mention, multiple references, or a literal job duty. 0.5 means
  "implied / nice to have." 0.0 means "not mentioned."
- signal_tags: pick from the curated vocabulary if applicable, but
  feel free to add new lowercased tokens for clearly-evidenced
  concepts. Examples of the vocabulary: interpretability, evals,
  sycophancy, rlhf, alignment, transformer, training, data_pipeline,
  tokenization, rust, inference, agents, robustness,
  research_engineering.
- summary: be concrete. "Wants someone who can build interpretability
  tooling and stand up eval pipelines" > "general ML engineering."
- Be calibrated: most axes for most JDs are 0.0 or 0.4. Reserve 1.0
  for axes the JD explicitly emphasizes.

Axis disambiguation (read carefully, these overlap):
- transformer_internals: architecture-level understanding (attention
  mechanics, KV cache, layer norm, residual streams). Engineering.
- mechanistic_interpretability: probing *trained* transformer
  internals (circuits, feature visualization, sparse autoencoders,
  activation patching). Distinct research domain — score it
  separately from transformer_internals even when the JD mentions
  both.
- ai_safety_fundamentals: alignment theory, RLHF, deceptive
  alignment, sycophancy, scalable oversight, honest/harmless
  framings. Conceptual depth.
- ai_governance_strategy: policy, deployment governance, race
  dynamics, responsible scaling policies, compute governance, AGI
  timelines/strategy framing. Strategic depth.

For roles like "Research Engineer, Interpretability" at frontier
safety labs: expect transformer_internals + mechanistic_interpretability
+ ai_safety_fundamentals to all be ≥0.7. For "Policy Lead" roles at
the same labs: expect ai_governance_strategy ≥ 0.8 and the engineering
axes lower.

iac_profile taxonomy (from the LessWrong piece "Talent Needs of
Technical AI Safety Teams"). The three roles are not mutually
exclusive — most roles want some blend. Score the *role*, not a
person; each value is "how much this role calls for this archetype":
- iterator: pushes an existing research agenda forward. Strong at
  executing experiments, debugging models, shipping incremental
  wins. Signals in a JD: "run experiments," "iterate on training
  runs," "debug model behavior," "ship results."
- amplifier: multiplies others' research output. Strong at tooling,
  infra, evals, internal codebases, knowledge management. Signals:
  "build internal tooling," "eval infrastructure," "developer
  experience for researchers," "shared infrastructure."
- connector: synthesizes across disciplines or people. Strong at
  setting new agendas, bridging fields, distillation. Signals:
  "propose new research directions," "cross-team collaboration,"
  "synthesize findings," "external communication."

The three iac_profile scores should sum to roughly 1.0 — they
represent role mix, not independent traits. If the JD is silent,
default to {0.5, 0.3, 0.2} (iterator-leaning research engineering).

iac_evidence_md: 2-4 short bullets quoting or paraphrasing the JD
language that justifies each non-trivial score. Keep under 300
characters.
"""


def parse_with_claude(source_text: str, user_id: str | None = None) -> dict[str, Any]:
    """`user_id` flows through to the spend-cap shim. Raises a
    `RuntimeError` (caught by the public `parse()`) when the user is
    over their daily Anthropic budget, so the keyword-fallback path
    kicks in transparently."""
    from . import llm_keys, spend_cap
    if spend_cap.over_cap_for(user_id, "jd_parse"):
        raise RuntimeError("daily Anthropic cap reached — falling back to keyword parse")
    client = llm_keys.client_for(user_id)
    truncated = source_text[:20000]
    resp = client.messages.create(
        model=_DEFAULT_MODEL,
        max_tokens=1500,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "JOB DESCRIPTION:\n\n" + truncated}],
    )
    spend_cap.record_usage_for(user_id, resp, service="jd_parse")
    body = "".join(b.text for b in resp.content if hasattr(b, "text"))
    m = re.search(r"\{.*\}", body, re.DOTALL)
    if not m:
        raise ValueError("no JSON in Claude response")
    parsed = json.loads(m.group(0))
    aw_raw = parsed.get("axis_weights", {})
    axis_weights = {a: max(0.0, min(1.0, float(aw_raw.get(a, 0.0)))) for a in assess_svc.AXES}
    signal_tags_raw = parsed.get("signal_tags", [])
    if isinstance(signal_tags_raw, list):
        signal_tags = sorted({str(t).strip().lower() for t in signal_tags_raw if t})
    else:
        signal_tags = []
    iac_profile = _coerce_iac_profile(parsed.get("iac_profile"))
    iac_evidence_md = str(parsed.get("iac_evidence_md", "")).strip() or None
    return {
        "axis_weights": axis_weights,
        "signal_tags": signal_tags,
        "summary": str(parsed.get("summary", "")).strip() or None,
        "iac_profile": iac_profile,
        "iac_evidence_md": iac_evidence_md,
        "method": "claude",
        "model_used": _DEFAULT_MODEL,
    }


# --- Iterator / Amplifier / Connector helpers ------------------------------

IAC_KEYS: tuple[str, ...] = ("iterator", "amplifier", "connector")
IAC_LABELS: dict[str, str] = {
    "iterator": "Iterator",
    "amplifier": "Amplifier",
    "connector": "Connector",
}


_IAC_FIT_MODEL = os.environ.get("ANTHROPIC_HAIKU_MODEL", "claude-haiku-4-5")


def interpret_iac_fit(
    jd_iac: dict[str, float],
    user_iac: dict[str, float],
    user_id: str | None = None,
) -> str | None:
    """Return a one-line "fit" interpretation comparing the JD's role
    profile against the candidate's. Uses Haiku (cheap). Returns None
    on any error so the caller can render the block without the line.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    from . import spend_cap
    if spend_cap.over_cap_for(user_id, "iac_fit"):
        return None
    try:
        from . import llm_keys
        client = llm_keys.client_for(user_id)
        system = (
            "You are advising a candidate on how to prep for a specific role. "
            "Given the role's iterator/amplifier/connector mix and the candidate's "
            "iterator/amplifier/connector mix, write ONE sentence (≤25 words) "
            "naming the dominant overlap and recommending what kind of prep "
            "(eval tooling, infra projects, paper distillation, etc.) to lean "
            "into. No preamble. No 'Fit:' prefix."
        )
        payload = (
            f"Role wants: iterator={jd_iac.get('iterator', 0):.2f}, "
            f"amplifier={jd_iac.get('amplifier', 0):.2f}, "
            f"connector={jd_iac.get('connector', 0):.2f}.\n"
            f"You bring: iterator={user_iac.get('iterator', 0):.2f}, "
            f"amplifier={user_iac.get('amplifier', 0):.2f}, "
            f"connector={user_iac.get('connector', 0):.2f}."
        )
        resp = client.messages.create(
            model=_IAC_FIT_MODEL,
            max_tokens=120,
            system=system,
            messages=[{"role": "user", "content": payload}],
        )
        spend_cap.record_usage_for(user_id, resp, service="iac_fit")
        body = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        return body or None
    except Exception:
        return None


def _coerce_iac_profile(raw: Any) -> dict[str, float] | None:
    """Coerce a raw iac_profile dict into clamped floats. Returns None
    if the input is missing or unrecognizable, so callers can decide
    whether to default."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, float] = {}
    saw_any = False
    for k in IAC_KEYS:
        try:
            v = float(raw.get(k, 0.0))
            saw_any = saw_any or (k in raw)
        except (TypeError, ValueError):
            v = 0.0
        out[k] = max(0.0, min(1.0, v))
    return out if saw_any else None


def parse(source_text: str, user_id: str | None = None) -> dict[str, Any]:
    """Public entry point. Prefer Claude when API key is set; otherwise
    fall back to keyword matching. On any LLM error (including a
    spend-cap hit raised by parse_with_claude), falls back."""
    text = source_text or ""
    if not text.strip():
        return {
            "axis_weights": {a: 0.0 for a in assess_svc.AXES},
            "signal_tags": [],
            "summary": "Empty JD.",
            "iac_profile": None,
            "iac_evidence_md": None,
            "method": "keyword_fallback",
            "model_used": None,
        }
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return parse_with_claude(text, user_id=user_id)
        except Exception:
            return parse_keyword(text)
    return parse_keyword(text)


def derive_title(source_text: str) -> tuple[str, str | None]:
    """Best-effort (title, org) extraction from the top of the text.
    Looks at the first few non-empty lines."""
    lines = [ln.strip() for ln in (source_text or "").splitlines() if ln.strip()]
    if not lines:
        return ("Untitled JD", None)
    title = lines[0][:120]
    org = None
    if len(lines) > 1:
        candidate = lines[1]
        if len(candidate) < 80 and not candidate.endswith("."):
            org = candidate
    return (title, org)


# --- URL paste support -----------------------------------------------------
#
# Many users (the author included) paste a job-listing URL into the
# textarea instead of the full description. We detect that, fetch the
# page, and extract a (title, org, body) tuple so the rest of the
# pipeline sees the same shape as a manual paste.

_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


# Acronyms that should render UPPER-cased, not Capitalized. The
# `capitalize()` helper produces "Ai" from "ai" because it only
# uppercases the first letter and lowercases the rest — fine for
# normal words, wrong for two/three-letter technical acronyms that
# show up frequently in AI-safety JD titles.
_TITLE_ACRONYMS: frozenset[str] = frozenset({
    "ai", "ml", "rl", "llm", "nlp", "cv", "iam", "api", "ux",
    "ui", "cto", "ceo", "vp", "sr", "jr", "ios", "qa", "sre",
    "ops", "ar", "vr", "ai/ml",
})


def _smart_title_word(word: str) -> str:
    """Title-case a single word, but upper-case it when it's a known
    acronym (AI, ML, RL, LLM, etc.). Fixes the long-standing 'Senior
    Engineer Ai Safety' rendering on the home page."""
    return word.upper() if word.lower() in _TITLE_ACRONYMS else word.capitalize()


def title_from_url(url: str) -> str:
    """Best-effort title from a URL slug. Used when fetching the JD page
    fails (offline, auth wall) so we don't store the raw URL as the
    title and end up rendering `Focused on https://...` on the home page.

    Strategy: take the last non-numeric path segment, strip leading
    "N-" numeric id prefix and chrome words (jobs, careers, positions),
    split on '-' or '_', title-case each word — except for known
    acronyms, which get upper-cased.

      /jobs/4569028008-research-engineer-interpretability
        → "Research Engineer Interpretability"

      /careers/positions/12345/senior-engineer-ai-safety
        → "Senior Engineer AI Safety"
    """
    from urllib.parse import urlparse
    try:
        path = urlparse(url).path or ""
    except Exception:
        return "Untitled JD"
    segments = [s for s in path.split("/") if s]
    for seg in reversed(segments):
        # Strip "12345-" or "12345_" id prefix.
        cleaned = re.sub(r"^\d+[-_]", "", seg)
        if cleaned.isdigit() or not cleaned:
            continue
        # Strip leading chrome words ("jobs", "careers", "positions", "roles")
        cleaned = re.sub(r"^(jobs?|careers?|positions?|roles?|openings?|listings?)[-_]?",
                         "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace("_", "-")
        words = [_smart_title_word(w) for w in cleaned.split("-") if w]
        if words:
            return " ".join(words)[:120]
    return "Untitled JD"


def is_url_title(title: str | None) -> bool:
    """True if `title` looks like a URL — used by the template filter
    to render a derived title in place of a URL stored in the DB."""
    if not title:
        return False
    t = title.strip().lower()
    return t.startswith("http://") or t.startswith("https://")


def looks_like_url(text: str) -> str | None:
    """Return the URL if `text` is *just* a URL (possibly with whitespace),
    otherwise None. We deliberately don't try to extract a URL from
    free-form text — if the user pasted a JD that happens to contain
    links, they meant the JD body."""
    t = (text or "").strip()
    if not t:
        return None
    if "\n" in t:
        return None
    if _URL_RE.match(t):
        return t
    return None


def _strip_tags_to_text(html: str) -> str:
    """Convert HTML to roughly-readable plaintext using stdlib only.
    Drops <script>/<style>; collapses runs of whitespace; preserves
    paragraph breaks via newlines after block tags."""
    from html.parser import HTMLParser

    class _Extractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.out: list[str] = []
            self._skip_depth = 0
            self._title_parts: list[str] = []
            self._in_title = False
            self.meta: dict[str, str] = {}
            self._block_tags = {
                "p", "div", "section", "article", "header", "footer",
                "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
                "br", "tr", "table",
            }

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in ("script", "style", "noscript", "svg"):
                self._skip_depth += 1
                return
            attrs_d = {k: (v or "") for k, v in attrs}
            if tag == "title":
                self._in_title = True
            elif tag == "meta":
                name = (attrs_d.get("property") or attrs_d.get("name") or "").lower()
                content = attrs_d.get("content") or ""
                if name and content and name not in self.meta:
                    self.meta[name] = content
            elif tag in self._block_tags and self._skip_depth == 0:
                self.out.append("\n")

        def handle_endtag(self, tag: str) -> None:
            if tag in ("script", "style", "noscript", "svg"):
                self._skip_depth = max(0, self._skip_depth - 1)
            if tag == "title":
                self._in_title = False
            if tag in self._block_tags and self._skip_depth == 0:
                self.out.append("\n")

        def handle_data(self, data: str) -> None:
            if self._skip_depth:
                return
            if self._in_title:
                self._title_parts.append(data)
            self.out.append(data)

    p = _Extractor()
    try:
        p.feed(html)
    except Exception:
        # Malformed HTML — return whatever we got so far.
        pass
    text = "".join(p.out)
    # Collapse whitespace within lines, keep paragraph breaks.
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    cleaned = "\n".join(ln for ln in lines if ln)
    # Stash meta for callers via attribute hack — return as tuple instead.
    return cleaned, p.meta, " ".join(p._title_parts).strip()


def _org_from_url_and_meta(url: str, meta: dict[str, str], page_title: str) -> str | None:
    """Heuristics, in order: og:site_name → known-host map → host root.
    The known-host map covers the listings boards the user is most
    likely to paste from."""
    site_name = meta.get("og:site_name") or meta.get("application-name")
    if site_name:
        return site_name.strip()[:100]
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    # Known greenhouse/lever/ashby/workday hosts: org is in the path,
    # not the hostname. Pull it from page_title or fall through to host.
    known_boards = ("greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "boards.greenhouse.io")
    if any(host.endswith(b) for b in known_boards):
        # Page title pattern: "Role · Org" or "Org - Role" or "Role at Org"
        for sep in (" at ", " · ", " — ", " - ", " | "):
            if sep in page_title:
                left, right = page_title.split(sep, 1)
                # heuristic: shorter side is usually the org
                candidate = right if len(right.strip()) < len(left.strip()) else left
                return candidate.strip()[:80] or None
        return None
    # First-party career pages — host root is a decent proxy.
    if host:
        root = host.replace("www.", "").split(".")[0]
        # Capitalize known orgs nicely.
        nicer = {
            "anthropic": "Anthropic", "openai": "OpenAI", "deepmind": "DeepMind",
            "google": "Google", "meta": "Meta", "metr": "METR", "apollo": "Apollo Research",
            "far": "FAR.AI", "aisi": "AISI", "governance": "GovAI",
        }
        return nicer.get(root, root.capitalize())
    return None


def _title_from_meta(meta: dict[str, str], page_title: str) -> str:
    """Prefer og:title, then <title>, then a fallback."""
    for k in ("og:title", "twitter:title"):
        v = meta.get(k)
        if v and v.strip():
            return v.strip()[:120]
    if page_title:
        # Strip the trailing " - Org" / " · Org" / " | Org" suffix that
        # career pages routinely append, so the stored title reads as
        # "Research Engineer, Interpretability" not
        # "Research Engineer, Interpretability — Anthropic".
        for sep in (" — ", " - ", " · ", " | "):
            if sep in page_title:
                left = page_title.split(sep, 1)[0].strip()
                if 4 <= len(left) <= 120:
                    return left
        return page_title.strip()[:120]
    return "Untitled JD"


def fetch_from_url(url: str, *, timeout: float = 8.0) -> dict[str, Any] | None:
    """Fetch a JD listing URL and return:

        {"title": str, "org": str | None, "source_text": str, "url": str}

    Returns None on any network / parse failure — callers should fall
    back to treating the URL as literal text in that case.
    """
    import httpx

    headers = {
        # Some career pages (Greenhouse, Workday) reject default Python UA.
        "User-Agent": "Mozilla/5.0 (compatible; LisBench/1.0; +https://github.com/libearden)",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            r = client.get(url)
            if r.status_code >= 400 or not r.text:
                return None
            html = r.text
    except Exception:
        return None
    body_text, meta, page_title = _strip_tags_to_text(html)
    # Some SPA-style career pages return ~empty bodies — bail so the
    # caller knows to treat the URL as opaque.
    if len(body_text) < 200:
        return None
    title = _title_from_meta(meta, page_title)
    org = _org_from_url_and_meta(url, meta, page_title)
    return {
        "title": title,
        "org": org,
        "source_text": body_text[:40000],  # generous cap; parse() truncates again
        "url": url,
    }
