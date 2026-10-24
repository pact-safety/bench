# Connect & community — rounding the platform out

Status: proposal · 2026-07-20
Feeds: the H2 hosted-pilot strategy and the platform audit (both internal)
Absorbs: feedback #42 (LinkedIn ask), operator direction 2026-07-20
("connect section especially has room to grow… integrations into CEA
forum, linkedin, alignment forum, lesswrong (maybe under writings??)")

## The framing problem: "Connect" is three products

Today `/connecting` is a **personal networking CRM** — warmth-decay
scoring over contacts *you* log. That's one of three different surfaces
hiding under the word "connect," and they should be built (and
prioritized) separately:

| Surface | What it is | Depends on | Size |
|---|---|---|---|
| **1. Inbound community feed** | AF / LessWrong / EA Forum posts, axis-tagged into the daily rotation | nothing new (RSS plumbing exists) | M |
| **2. Outbound presence** | cross-post `/writings` to AF/LW/Substack; LinkedIn-formatted copy | `/writings` (exists) | M |
| **3. Peer network** | find other learners, cohorts, study partners, mentors | **multi-tenancy** | L |

### 1. Inbound — the community reads you (build first)

The Alignment Forum, LessWrong, and the EA Forum all run the same
codebase (**ForumMagnum**) and expose the same **public GraphQL API** —
one integration covers all three. v1:

- Poll each forum's GraphQL endpoint for recent/curated posts (model on
  `app/services/news_*` — the RSS poller already solved storage,
  dedupe, and surfacing).
- Axis-tag posts (keyword map v1, LLM tagging v2 — same ladder as
  content-engine-v2) so a learner weak on `eval_design` sees relevant
  AF posts in their rotation, not a raw firehose.
- Render in `/news` (or a `Community` tab there). **Link out; host
  nothing** — the IP-clean rule.

Why first: it's the highest value-per-effort, needs no tenancy, and
directly serves both audiences (novices get curated exposure to the
live field; pivoting engineers stay current).

### 2. Outbound — you write for the community (under /writings — yes)

The operator's instinct ("maybe under writings??") is right: these are
*publishing destinations*, not connections.

- **Alignment Forum / LessWrong:** same GraphQL API supports authenticated
  mutations — but the honest v1 is **"export as AF/LW-ready Markdown +
  open composer"**, not auto-posting (auth friction, and a fieldbuilding
  tool auto-posting to AF invites moderation trouble). The existing
  alignment-forum-readiness rubric idea (feedback #2, ROADMAP v2 §3)
  slots here.
- **Substack:** already planned (ROADMAP v2 §3).
- **LinkedIn (feedback #42: "so I never have to go back"):** the API
  reality — posting on behalf of a member requires LinkedIn partner-
  program approval; realistic v1 is **"format for LinkedIn + copy
  button"** (hook-first rewrite, line-break-heavy). Full auto-post only
  if partner access ever lands. Don't promise it.

### 3. Peer network — the community *is* the product (H2, after tenancy)

The genuinely new fieldbuilding value, and the multi-tenant payoff:

- Opt-in learner directory (role, axes-in-progress, cohort, timezone).
- Study-partner matching on assessment complements ("you're strong on
  transformer_internals, they're strong on eval_design").
- Cohort spaces for programs (BlueDot groups, university clubs) — this
  is what makes org self-hosting *and* the hosted pilot legible to
  funders.
- Mentor hooks: a mentor sees a mentee's skill pentagon + trend, not
  raw transcripts (privacy default).

Blocked on multi-tenancy; design it with the tenancy work, not before.
`/connecting` (the CRM) remains its own personal surface — it gets a
"met on the bench" import path from the peer network rather than being
replaced by it.

## Round-out gaps for the two audiences

**Novices (learning the tech behind AI safety):**
1. **Safety-content depth** — still the #1 audit gap (eval-design is
   started; mech-interp, training-mechanics, RL/safety are shells).
2. **One "from zero" spine** — a single linear on-ramp track that
   sequences fundamentals → transformers → interp/evals across the
   existing tracks; today three tracks exist but nothing orders them.
3. **Glossary / concept map** — jargon is the field's real gatekeeping;
   axis-tagged glossary entries crosslinked from content are cheap and
   compounding.

**Pivoting engineers:**
1. **Safety-org JD targeting** — the JD system exists; seed it with a
   curated set of live safety-org JDs (Anthropic/DeepMind/RSP-adjacent
   orgs, MATS/ARENA-style programs) so "readiness for a real role" is
   one click, not a paste.
2. **Paper→exercise pairing** — content-engine-v2 (proposed) is the
   pivotal feature for this audience; same-day exercises on what they
   read.
3. **Inbound feed (surface 1)** — staying current is their actual daily
   habit; meet it.

**Both:** Path/Remix daily modes (shipped), the retakable assessment
(exists) — the adaptive loop is the shared spine; everything above
feeds it.

## Sequencing recommendation

1. **Inbound community feed** (surface 1) — now-ish; M; no dependencies.
2. **Glossary + "from zero" spine track** — content-only; S–M each.
3. **Writings export pack** (AF/LW Markdown + LinkedIn formatter +
   Substack) — M; rides the planned /writings redux.
4. **Safety-org JD seed set** — S; editorial.
5. **Peer network** — with multi-tenancy in H2; design doc first.

Non-goals: hosting forum content (link only); LinkedIn auto-posting
without partner access; building a chat/social product (cohort spaces
link out to existing Slack/Discord rather than reimplementing them).
