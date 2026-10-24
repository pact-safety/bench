# Library and external readings

`/library` is the full catalog: curated content + problems + your own added external readings.

## What's there

| Section | Source |
|---|---|
| **Favorites** | Items you starred via the heart on the content detail page |
| **Content** | Curated readings/videos/podcasts + your `external_reading` adds. Filter by tag / kind. |
| **Core problems** | The 30-something authored problems with EM scaffolding. |
| **Warmups** | Short problems that don't enter the scheduler. `/warmup` picks one at random. |

Filter chips at the top let you cross-cut by type (reading/video/exercise/code_compose/theory) and by tag.

## Adding external readings

Use `+ Add external content` on `/library`. The form takes URL → fetches → Claude-parses (Haiku) → returns `{title, source, suggested axes, summary_md}` → pre-fills the form. You then add your own notes (plus optional rating after you mark complete).

Pasted items enter the daily rotation if they match the user's active axes, with the same content_progress + rating + reflection tracking as curated items.

### Example flow

1. You're reading [a LessWrong piece](https://www.lesswrong.com/posts/QzQQvGJYDeaDE4Cfg/talent-needs-of-technical-ai-safety-teams) externally.
2. `/library/add` → paste URL → click **`Parse with Claude →`**.
3. Form pre-fills: title `"Talent Needs of Technical AI Safety Teams"`, source `"LessWrong"`, axes (suggested), notes textarea seeded with a 2-3 sentence summary.
4. Edit notes to capture your own thoughts. Save.
5. Item now lives in `/library` with an "external · LessWrong" badge.
6. Mark it complete when you're done. Rate 1–5. Add a reflection.
7. The reflect prompt-generator picks up substantive notes from external readings as the highest-signal context for the next weekly reflection.

## How the catalog is loaded

- Curated content lives in `content/*.toml` (one file per item). Loaded at startup; cached.
- Problems live in `content/r*.toml` (rust) / `content/*.toml` with `[problem]` blocks. Same loader.
- External readings live in `content_items` table with `source_kind = 'user'` and `created_by_user_id = <your-uuid>`.

`hashes_by_slug()` lets the startup loader skip unchanged items (per-slug content hash), so restarts are ~1s when nothing changed.

## Tag taxonomy

A known limitation: problem tags (e.g. `attention`) and content_item axes (e.g. `transformer_internals`) don't share a vocabulary, so filtering Library by `attention` returns problems but not the obviously-relevant Vaswani reading. Tracked separately (LIS-284).

## See also

- [Weekly Hamming reflections](reflect.md)
- [Drilling problems](problems.md)
