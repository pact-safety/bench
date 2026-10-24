# Li's Bench

A drill platform I built for myself while preparing for research-engineer interviews at frontier AI labs. Opinionated. Daily-driver.

Most of this site documents how *I* use it, surface by surface — a record of the shape I've grown into, both for future-me and for the agents that work this codebase with me. The bench is invite-only alpha.

**If you're using bench rather than building it,** four pages are written for you rather than for me:

- **[How practice works](using/how-practice-works.md)** — the pedagogy, and how confident to be in each part of it
- **[AI in the bench](using/ai-and-your-work.md)** — which models run where, what leaves your machine, what the model is bad at
- **[Your data](using/your-data.md)** — what's stored, who can read it, how to delete it
- **[Accessibility](using/accessibility.md)** — what's implemented, and what's still weak

## What it looks like in a day

```
Morning  →  /          drill picks for today (one reading, one problem, sometimes a writing prompt)
              ↓
            /problem/<slug>   submit, get a structured review (in Hamming's voice, or whoever)
              ↓
Mid-week  →  /focus     a glance at active initiatives: capstone, bench dev, content pipeline
              ↓
            /news       what landed overnight from Anthropic, Apollo, METR, Alignment Forum, the labs
              ↓
Saturday  →  /reflect   Hamming-mode prompts auto-generated against the week's actual data
              ↓
            /writings   draft something from what surfaced; sometimes ship to Substack
```

Every surface in that chain has a page in **[How I use it](using/problems.md)** explaining what I do there, why I built it that shape, and what I'd change if I were starting again.

## Why I built it (briefly)

I noticed I was thrashing — three browser tabs of practice problems, a journal in Notion, a separate doc of reading notes, half-remembered Substack threads about interpretability, a Linear board for the capstone. None of it connected. None of it remembered what I'd already worked on.

The bench is the consolidation. Practice and reading and reflection and decision-tracking all read from and write to the same store. The scheduler knows what I attempted yesterday and proposes the next thing accordingly. Reflect prompts cite specific numbers from my week ("you skipped Plan on 4 of 6 attempts — is that signal or noise?"). The MCP server lets a Claude chat see what initiative I'm pushing on and write its decision back to `/decisions` instead of being lost in a chat scroll.

## Map of the rest

<div class="grid cards" markdown>

- :material-target: **How I use it**

    Feature-by-feature tour. Drilling problems, picking voices, weekly reflections, reading library, JDs, readiness scoring.

    [→ Start with drilling problems](using/problems.md)

- :material-source-branch: **Architecture**

    Code tour, data model, services. For when I'm extending it (or when an agent needs context to extend it).

    [→ Code tour](architecture/code-tour.md)

- :material-tools: **Development**

    Setup, common tasks, deploy, autonomous coding agents. Skim if you're new to the repo; reference if you're touching infra.

    [→ Setup & tests](development/setup.md)

- :material-map: **Roadmap & decisions**

    What I've shipped, what's queued, what I rejected and why.

    [→ Roadmap](roadmap.md)

</div>

## One read

If you read one thing from this site, make it **[Drilling problems](using/problems.md)**. It's the surface I touch most often, and the shape everything else accommodates.
