---
slug: example-getting-started
title: Getting Started
status: active
priority: 0
linear:
  team: "Your Team"
  ticket_prefix: EXA
  label: example
github:
  repos:
    - your-org/your-repo
bench:
  surface: /
target_date: null
notes: |
  Template initiative — copy this file to create your own.

  Initiatives are YOUR data: the goals you're routing practice, reading,
  and reflection toward. They are gitignored by default (see .gitignore)
  so your personal goals never land in a public repo or a fork. Only this
  example is tracked.

  To add one: copy this file to content/initiatives/<your-slug>.md, change
  the slug (must be unique) and the fields below, then restart the server.

  Fields:
    slug          unique id, matches the filename
    title         human label shown in the UI
    status        active | done | paused
    priority      0-4 (0 = highest)
    linear        Linear team/ticket_prefix/label (all required, non-empty)
    github.repos  list of "owner/repo" strings this initiative touches
    bench.surface the app route this initiative most relates to
    target_date   YYYY-MM-DD or null
    notes         free text — what this initiative is actually for
---
