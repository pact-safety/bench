# Hints and mentor voices

Two related systems: the **3-tier hint ladder** (phase-aware) and the **mentor voice registry** (named-thinker review personas).

## Hint ladder

Each phase on a problem has a `Stuck? Get a nudge` button. Three tiers:

| Tier | Label | What it does |
|---|---|---|
| 1 | **NUDGE** | Asks a question or names a concept. Doesn't reveal the technique. |
| 2 | **DIRECTION** | Names the technique or invariant explicitly. Says WHAT to do but not HOW to write it. |
| 3 | **SCAFFOLDING** | 1–3 named structural steps. Still no code expressions or backticked snippets — the reference solution disclosure is the escape hatch for the literal answer. |

After tier 3, the platform refuses further hints on that phase and explicitly tells you to look at the reference solution and *trace why*. The reference disclosure is logged as a lookup, which affects the scheduler's recall scoring (the platform rewards solving without lookup).

### Implementation

- **Service**: `app/services/hints.py`
- **System prompt**: `_SYSTEM_PROMPT` in that file. Explicit anti-spoiler rules: tier 3 must be structural, no method-call snippets.
- **Fallback**: when `ANTHROPIC_API_KEY` isn't set, ships a deterministic per-phase tier-1 fallback. Tier 2/3 require Claude.
- **Endpoint**: `POST /hint/<slug>` with `phase`, `count_so_far`, `current_notes`, `code`, `prior_hints_json`.

The endpoint returns an HTMX-friendly HTML fragment that gets swapped into a per-phase hint slot.

## Voices

The review path (`POST /submit/<slug>`) accepts a `voice_key`. Default is the platform's house style. You can route any submission through a named-thinker persona — same structured per-phase JSON output, but the **emphasis** shifts.

### The roster

Nine voices in `app/services/voices.py`:

| Key | Voice | Lens |
|---|---|---|
| `default` | House voice | Phase-by-phase rigor against the EM. Anti-sycophancy. |
| `hamming` | Richard Hamming | Are you working on the central problem, or a comfortable side track? |
| `feynman` | Richard Feynman | Physical intuition. Do you understand *why* this works, or pattern-match? |
| `petroski` | Henry Petroski | Failure modes. Which past collapse is this attempt vulnerable to? |
| `meadows` | Donella Meadows | Leverage points. Symptom or structure? |
| `franklin` | Ursula Franklin | What does this tool do to its practitioner? Could you debug it at 3 am? |
| `russell` | Stuart Russell | Specification gaps. What if it succeeds *exactly* as written? |
| `johnson` | Ayana Elizabeth Johnson | Capacity × joy × need. Why did you queue this problem? |
| `wade` | Jess Wade | Whose work is being drawn on — and whose is missing? |

### Picking a voice

Three ways:

- **Per-submission**: the dropdown on `/problem/<slug>` above the `run tests` button. The lens preview updates live as you change the dropdown.
- **Set a default**: `/voices → Make this my default` (also reachable from `/settings → Review voice → Browse mentor voices →`).
- **Programmatically** (if you're writing tests): `review_attempt(problem, attempt, voice_key="hamming")` in `app/services/review.py`.

### How a voice changes the review

The voice's `persona` string is prepended to the existing structured review system prompt — the JSON output shape and anti-sycophancy rules are preserved; only the *style and emphasis* shift. Picking the Petroski voice means the review will identify the specific failure mode this attempt is vulnerable to. Picking Hamming means it'll flag courage gaps as readily as technical ones.

### Adding a voice

12-line append in `app/services/voices.py` — copy an existing `Voice(...)` block, fill in `key`, `name`, `era`, `works`, `persona`, `review_lens`, `provocation`. See [Adding a voice](../development/contributing.md#adding-a-voice).

## See also

- [Problems and the EM](problems.md)
- [Reflect](reflect.md) — has its own Hamming-flavored voice (not yet routed through this registry — follow-on)
