# Code tour

A walking tour of the repo for anyone extending the platform.

## Top-level shape

```
app/                          # FastAPI app
  main.py                       # All routes; ~2700 lines, organized by surface
  auth.py                       # GitHub-OAuth-via-Supabase PKCE flow
  cache.py                      # In-process read-through cache
  db.py                         # psycopg connect + autocommit
  env.py                        # .env.local loader
  models.py                     # Dataclasses for every entity
  config.py                     # config.toml loader
  observability.py              # Sentry setup
  repositories/                 # One file per entity, thin SQL
  runners/                      # python_runner.py, rust_runner.py
  services/                     # Business logic
templates/                    # Jinja2; one file per surface
static/                       # CSS + small JS
content/                      # Authored content TOML files
migrations_pg/                # Postgres schema migrations
scripts/                      # One-off init/migration tooling
tests/                        # Unit + integration
docs/                         # This documentation site
```

## Routes (app/main.py)

The file is organized into thematic sections (separator comments demarcate each):

| Section | Surfaces |
|---|---|
| Home / Today | `/`, `/today/next` |
| Onboarding | `/onboarding/*`, `/assess/*` |
| Skills + readiness | `/skills`, `/readiness` |
| Content | `/content/<slug>`, `/content/<id>/check`, `/content/<id>/favorite` |
| Problems + warmup | `/problem/<slug>`, `/warmup`, `/submit/<slug>`, `/hint/<slug>` |
| Voices | `/voices`, `/voices/prefer` |
| Library | `/library`, `/library/add`, `/library/add/parse-url` |
| Writings | `/writings/*` |
| Reflect | `/reflect`, `/reflect/generate`, `/reflect/<id>` |
| JDs | `/jds`, `/jds/<id>`, `/jds/<id>/activate`, `/jds/<id>/archive` |
| Credentials | `/credentials`, `/credentials/<id>/{analyze,gap}` |
| Settings | `/settings`, `/settings/*` |
| Reset | `/settings/reset` |
| Feedback | `/feedback`, `/feedback/inbox`, `/feedback/<id>/{archive,backlog,reopen,dismiss}` |
| Auth | `/login`, `/auth/*` |

## Services (`app/services/`)

Each service is a single-purpose pure-functional module. Most are LLM-flavored; all have an offline fallback.

| File | Purpose |
|---|---|
| `assessment.py` | The 12-question quiz + axis scoring + `AXES`/`AXIS_LABELS` |
| `content.py` | Daily content picker (`pick_daily()`) |
| `credentials.py` | CV parse → skill-gap + IAC profile |
| `crosslink.py` | Crosslink content ↔ attempts |
| `daily_flow.py` | `compute_next()` for `/today/next` |
| `em.py` | EM-mode resolution per problem |
| `external_capture.py` | URL fetch + Claude parse for `/library/add` |
| `feedback_inbox.py` | Markdown regeneration from the DB |
| `hamming.py` | Weekly reflect prompt generation |
| `hints.py` | 3-tier hint ladder |
| `jds.py` | JD parse + IAC profile + URL fetcher |
| `markdown.py` | Mistune + Pygments wrapper for the `markdown` filter |
| `readiness.py` | Gap-to-hours math |
| `references.py` | Per-phase reference grouping |
| `review.py` | Attempt review (per-phase JSON, optional voice persona) |
| `scheduler.py` | Problem-scoring + `easy_first_bias` ramp |
| `skill_stats.py` | Aggregate per-axis pass rates |
| `voices.py` | Mentor voice registry |

## Repositories (`app/repositories/`)

One file per entity. Thin SQL wrappers around `psycopg`. Shared helpers in `_pg.py`: `jsonb()`, `uuid_str()`, `naive_utc()`.

Every repo is single-method-per-query, no ORM. Cache layer is per-repository — invalidate by prefix when writes happen.

## See also

- [Data model](data-model.md)
- [Services](services.md)
- [Templates and frontend](frontend.md)
