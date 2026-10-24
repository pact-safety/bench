# AI in the bench — what it does with your work

Bench uses large language models in several places. This page says which ones,
what leaves your browser, what the model can and cannot be trusted with, and
how to turn it off. It is written to be checkable: every claim here points at
the code that implements it.

If you only read one thing: **the model is a sparring partner, not an
authority.** It is wrong sometimes, and the app is built on the assumption that
you will catch it.

## Where a model is actually invoked

| Surface | What it does | Model | Where |
|---|---|---|---|
| Attempt review | Structured critique of a submitted attempt, in a chosen voice | Sonnet 4.5 | `services/review.py` |
| Mira (`/mira`) | Open-ended research advising | Sonnet 4.5 | `services/llm_provider.py` |
| Recitation grading | Compares what you said back against the source | Sonnet 4.5 | `services/recitation.py` |
| JD parsing | Extracts structure from a pasted job description | Sonnet 4.5 | `services/jds.py` |
| Credential analysis | Reads a CV / profile against a target role | Sonnet 4.5 | `services/credentials.py` |
| `/problem/<slug>` hints | Tiered nudges scoped to the phase you're in | Haiku 4.5 | `services/hints.py` |
| IAC fit scoring | Cheap relevance pass over a JD | Haiku 4.5 | `services/jds.py` |
| `/library/add` URL capture | Fetches a link, guesses title / kind / axes | Haiku 4.5 | `services/external_capture.py` |
| Weekly reflection prompts | Generates Hamming-mode questions from your week | Haiku 4.5 | `services/hamming.py` |
| Read-aloud (text-to-speech) | Speaks content back to you | OpenAI `gpt-4o-mini-tts` | `services/tts.py` |
| Speak-and-grade | Turns your spoken answer into text | OpenAI `whisper-1` | `services/transcription.py` |

The Anthropic model is overridable per deployment with `ANTHROPIC_MODEL` and
`ANTHROPIC_HAIKU_MODEL`, so treat the table as the shipped default rather than
a guarantee. The "Where" column is the file to check if you want the current
truth.

Everything else — scheduling, scoring, the skill profile, readiness, the daily
pick — is ordinary deterministic code. No model decides what you practise
next.

## What leaves your machine

When you use one of the surfaces above, the relevant text is sent to that
provider's API over TLS:

- **Anthropic** receives the problem, your attempt, your notes for that
  attempt, or your Mira message — whatever that specific call needs.
- **OpenAI** receives the text to be spoken, or the audio you recorded, and
  nothing else.

**Audio, specifically.** The recording you make for speak-and-grade is sent for
transcription and **not stored** — no row, no file, no bucket. Generated
speech *is* cached (`tts_cache`), so a chapter is synthesised once instead of
on every page view; those rows carry your `user_id`, are filtered by it on the
serve route, and cascade away when your account is deleted.

Nothing is sent anywhere on a page that doesn't invoke a model. Your attempt
history, skill scores, reflections, and writing drafts are not shipped
wholesale to a provider; each call carries only its own inputs.

Bench does not train any model on your work, because bench does not train
models at all. What each provider does with API traffic is governed by their
terms, not by bench — read
[Anthropic's](https://www.anthropic.com/legal/commercial-terms) and
[OpenAI's](https://openai.com/policies/) if that matters to you, and assume it
does.

## Turning it off

Every LLM-touching service has a deterministic fallback and the app stays
usable without a key:

- No `ANTHROPIC_API_KEY` → hints fall back to canned phase-scoped nudges,
  reviews are skipped, JD parsing uses keyword matching.
- No `OPENAI_API_KEY` → read-aloud and speak-and-grade degrade gracefully;
  you type your recitation instead of speaking it.

This is not a courtesy path. It is the path CI runs on, which is why it keeps
working.

## The spend cap

Every model call is metered per user per day (`app/services/security.py`,
`app/services/spend_cap.py`). Past the cap, LLM paths take the same offline
fallback as a missing key — the app does not stop working, it stops spending.

The default ceiling is 200,000 tokens per user per day, overridable with
`ANTHROPIC_DAILY_TOKEN_CAP`. The window resets at midnight in the time zone you
set in `/settings`, and the reset instant is pinned when the window opens, so
changing your time zone mid-day cannot reopen a window you already closed.

## What the model is bad at

Stated plainly, because a learning tool that oversells its AI is teaching you
to trust the wrong thing:

- **It will state wrong things confidently.** Especially numerical claims,
  library APIs, and anything where the plausible answer and the correct answer
  differ. Check before you believe.
- **It cannot see your code run.** Reviews read your submission; the test
  result comes from actually executing your code in a sandbox, which is
  separate and trustworthy in a way the prose is not.
- **It is not measuring you.** A review is one model's read of one attempt. It
  is not a score, it does not feed your skill profile, and nothing in the app
  ranks you by it.
- **Recitation grading is a comparison, not a verdict.** It tells you which
  ideas were covered, missing, misstated, or open. It deliberately cannot emit
  a score — the allowed output shape has no field for one, and any number the
  model tries to produce is stripped before you see it.

## Mira pushes back on purpose

Mira is prompted to be short, specific and honest, and to disagree with you.
That is a deliberate counterweight: a model that agrees with whatever
experiment design you propose is worse than no mentor, because it launders your
own assumptions back to you with apparent authority.

If Mira tells you your eval is measuring the wrong thing, that is the feature
working. It is still sometimes wrong about which thing.

## Prompt injection

Content you ingest — a pasted URL, a paper, a job description — is *data*, not
instructions. Bench treats it that way, and text inside ingested content that
tries to issue instructions to the model is not honoured as a command. If you
ever see the app behave as though a document told it to, that is a bug worth
reporting through the feedback widget.

## Related

- [Your data](your-data.md) — what is stored, who can read it, how to delete it
- [How practice works](how-practice-works.md) — the parts that are deliberately not AI
- [Settings](settings.md) — voices, time zone, accessibility
