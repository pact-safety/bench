# JDs and the IAC profile

Paste a URL or text; the platform extracts an axis-weighted skill profile + an iterator/amplifier/connector taxonomy + a 2-sentence summary. Use this to drive readiness, scheduling, and reflect context.

## What gets parsed

`app/services/jds.py` extracts three things via Claude (with a keyword fallback when no API key is available):

| Field | Type | Drives |
|---|---|---|
| `axis_weights` | `dict[axis, float]` (10 axes, each 0–1) | Scheduler bias + readiness math |
| `signal_tags` | `list[str]` from a curated vocabulary | Problem matching via `problems.jd_signal_tags` |
| `iac_profile` | `{iterator, amplifier, connector}` floats, ~sum to 1.0 | Fit alignment on the JD detail page |
| `iac_evidence_md` | Short markdown citing the JD language | Shown alongside the IAC scores |
| `summary` | 2-sentence English | JD detail page header |

## The iterator/amplifier/connector taxonomy

From the LessWrong piece [*Talent Needs of Technical AI Safety Teams*](https://www.lesswrong.com/posts/QzQQvGJYDeaDE4Cfg/talent-needs-of-technical-ai-safety-teams) (Larsen/Hubinger et al.). Three archetypes:

- **Iterator** — pushes an existing research agenda forward. Strong at: executing experiments, debugging models, shipping incremental wins. Signals in a JD: *"run experiments", "iterate on training runs", "debug model behavior", "ship results"*.
- **Amplifier** — multiplies others' research output. Strong at: tooling, infra, evals, internal codebases, knowledge management. Signals: *"build internal tooling", "eval infrastructure", "developer experience for researchers"*.
- **Connector** — synthesizes across disciplines / people. Strong at: setting new agendas, bridging fields, distillation. Signals: *"propose new research directions", "cross-team collaboration", "external communication"*.

Most roles want a blend. The three IAC scores roughly sum to 1.0 — they represent role mix, not independent traits. If the JD is silent on this, the parser defaults to `{0.5, 0.3, 0.2}` (iterator-leaning research engineering).

## Your own IAC profile

When you upload a CV via `/credentials`, the same `iac_profile` shape gets extracted and stored on `users.settings_json.iac_profile`. The JD detail page then renders a side-by-side **"this role wants / you bring"** block plus a 1-line fit interpretation from a small Claude call (cached on the JD row in `jds.iac_fit_md`).

If you don't have a CV uploaded, the alignment block prompts you to add one.

## Active JD

Only one JD is active at a time. Setting one active:

```
POST /jds/<id>/activate
```

is what the `Activate` button on the JD detail page does. The active id lives at `users.settings_json.active_jd_id`. The scheduler reads it, readiness reads it, and the home page's Today header references it.

## Adding a JD

Three ways:

- **Paste URL**: `/jds` → paste a job-board link. The server fetches the page, strips it to text, extracts metadata (`og:title`, organization), runs Claude. If the fetch fails (auth-walled boards, SPA-rendered pages), the URL-slug fallback kicks in to derive a clean title.
- **Paste text**: `/jds` → paste the full JD body. Same pipeline minus the fetch.
- **Manual title + text**: optional override fields on the form.

## Where the data goes

- `jds` table: `axis_weights` (JSONB), `signal_tags` (JSONB), `summary`, `iac_profile` + `iac_evidence_md` (JSONB), `iac_fit_md` (cache).
- The JD parsed_json drives `scheduler._score()` (in `app/services/scheduler.py`) when a JD is active — adds a small bonus for problems whose `domain_tags` and `jd_signal_tags` overlap with the JD.

## Title rendering

Stored titles that look like URLs (legacy data) are healed at render time by the `jd_title` Jinja filter. The filter detects a URL-shaped title and derives a clean form via `jds.title_from_url()`. Applied on `home.html`, `jd_detail.html`, `jds_index.html`, `readiness.html`.

## See also

- [Readiness](readiness.md)
- [Settings](settings.md) — reset, accessibility, profile
- [Architecture: services](../architecture/services.md#jd-parse)
