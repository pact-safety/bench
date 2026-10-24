---
slug: e10-spot-dedup-bug
kind: exercise
title: "Spot the dedup bug"
source: "pairs with The Pile / SemDeDup readings"
duration_min: 8
axes: [data_pipeline]
domain_tags: [dataset]
authored_by: claude_code_v1_build
authored_date: 2026-05-13
version: 1
---

**Setup.** A junior engineer writes a dedup pass for a streaming
ingestion job:

```python
def dedupe(records):
    """records: iterable of {text: str, ...}"""
    seen = set()
    out = []
    for r in records:
        if r["text"] in seen:
            continue
        seen.add(r["text"])
        out.append(r)
    return out
```

The dataset they're cleaning is web-scraped news articles.
After running on a 10M-record corpus, they report that the dedup
"removed about 1% of duplicates" — but a sample inspection shows
a much larger fraction of near-identical articles (different
timestamps, same body).

**Question.** Name the bug, the fix, and what production dedup
typically does instead.

<details>
<summary>reveal</summary>

**Bug.** The check is on *exact* string equality. Near-duplicates
differ on trivial fields (article timestamp, "Updated 4 mins ago"
banners, ad slot text) but are substantively the same content.
Exact-string matching catches *only* byte-perfect copies.

**Minimum fix.** Hash a normalized form of the text instead of the
raw text:

```python
import hashlib, re

def _normalize(t: str) -> str:
    t = t.lower()
    t = re.sub(r"\\s+", " ", t)
    t = re.sub(r"\\d{1,2}:\\d{2}\\s?(am|pm)", "", t)  # drop times
    return t.strip()

def dedupe(records):
    seen = set()
    out = []
    for r in records:
        h = hashlib.sha256(_normalize(r["text"]).encode()).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        out.append(r)
    return out
```

This catches the "same article with two different timestamps"
case. It will not catch a paraphrase or a longer/shorter version
of the same article.

**What production dedup looks like.** Two-stage:

1. **MinHash + LSH** to find candidate pairs in sub-O(n²) time. The
   Pile uses this at the document level — SHA-256 on shingled
   n-grams.
2. **Semantic dedup (SemDeDup)** to catch paraphrase-near-duplicates
   that survive lexical filtering: embed each document, K-means
   cluster, drop within-cluster pairs above a cosine threshold.

A from-scratch implementation of (1) is straightforward; (2)
requires an embedding model and significant compute. Most
research-engineering teams just use the data-juicer or
text-dedup libraries off the shelf.

</details>

**Key insight.** Dedup is a *spectrum* between byte-exact (cheap,
misses near-duplicates) and semantic (expensive, catches paraphrase).
The right point on the spectrum depends on how the resulting model
gets used — pretraining can tolerate lossy dedup; eval sets cannot.
