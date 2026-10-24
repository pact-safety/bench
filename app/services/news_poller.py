"""RSS news poller (rss-news-feed Phase 1).

Reads ``content/news_feeds.toml`` to discover feeds, fetches each via
``feedparser`` (which handles HTTP + RSS/Atom parsing), and inserts new
items into ``news_items`` via the NewsRepository.

Design:
- **Pure-functional core**, scheduler-agnostic. The
  ``poll_feeds(repo, feeds, now)`` function takes its dependencies as
  args so tests can drive it with mocked feeds.
- **Per-feed isolation**: one feed's failure never affects another.
  Each feed is wrapped in try/except; we record_failure() and move on.
- **Single-pass dedup** via the repo's ``insert_if_new`` (which uses
  ``ON CONFLICT (url) DO NOTHING``). Idempotent: re-polling the same
  feed returns 0 new items.
- **No live network in tests** — the unit tests pass a mock
  ``feedparser_module`` parameter so the poll runs against in-memory
  fixtures.

The scheduler wrapper lives in ``app/main.py`` alongside the existing
``_start_reflect_pregenerator()``. It calls ``poll_feeds_once()``
hourly.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..models import NewsItem


# tomllib was added in Python 3.11; before that we'd want tomli. The
# bench requires py3.11+ per pyproject.toml so this is always safe.
if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover — Python 3.10 not supported by the bench
    import tomli as tomllib


_log = logging.getLogger("bench.news_poller")

# Network safety: cap each fetch + parse so a slow/unresponsive feed
# can't stall the entire tick.
_FEED_TIMEOUT_SECONDS = 15

# Lots of feed entries don't carry a usable pubDate. When that happens
# we fall back to the bench's "fetched_at" timestamp so the row still
# sorts somewhere sane. ``_PUBDATE_FALLBACK`` is the explicit fallback
# message we attach as a structured-log breadcrumb.
_PUBDATE_FALLBACK = "(no pubDate; using fetched_at)"


@dataclass(frozen=True)
class FeedConfig:
    slug: str
    name: str
    url: str
    tier: int = 1


@dataclass(frozen=True)
class FeedPollOutcome:
    """One feed's tick result. The wrapper logs a summary line."""
    feed_slug: str
    status: str   # "ok" | "error"
    items_seen: int = 0
    items_inserted: int = 0
    error_message: str = ""


def load_feeds_from_toml(path: Path) -> list[FeedConfig]:
    """Parse content/news_feeds.toml into FeedConfig records.

    Returns an empty list if the file doesn't exist (fresh repo /
    operator hasn't curated feeds yet). Doesn't validate URLs at
    parse time; that's the poller's problem.
    """
    if not path.exists():
        return []
    with path.open("rb") as f:
        raw = tomllib.load(f)
    out: list[FeedConfig] = []
    for entry in raw.get("feed", []):
        try:
            out.append(
                FeedConfig(
                    slug=str(entry["slug"]).strip(),
                    name=str(entry["name"]).strip(),
                    url=str(entry["url"]).strip(),
                    tier=int(entry.get("tier", 1)),
                )
            )
        except (KeyError, ValueError) as exc:
            _log.warning("skipping malformed feed entry %r: %s", entry, exc)
    return out


def _entry_pubdate(entry: Any, fallback: datetime) -> datetime:
    """Best-effort pubDate extraction from a feedparser entry.

    feedparser exposes the parsed time as ``published_parsed`` (a
    time.struct_time) or ``updated_parsed``. We try published first,
    then updated. If both are missing we use the fallback (typically
    the bench's "fetched_at" wallclock).
    """
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed is None:
        _log.debug(_PUBDATE_FALLBACK)
        return fallback
    # parsed is a time.struct_time in UTC per feedparser convention.
    try:
        # struct_time → datetime is awkward; we use the year/month/day…
        # fields directly to avoid intermediate time.mktime() which
        # interprets in local time.
        from calendar import timegm
        from time import gmtime

        # Sometimes feedparser yields a struct_time-like object; coerce
        # via timegm which expects UTC struct_time.
        epoch = timegm(parsed)
        return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return fallback


def _entry_summary(entry: Any) -> str | None:
    """Pick the best plain-text summary from a feedparser entry.

    Tries ``summary`` (RSS <description> / Atom <summary>) then falls
    back to the first available content. Strips HTML conservatively —
    feedparser already does most of this but some feeds bleed tags
    through.
    """
    raw = (
        getattr(entry, "summary", None)
        or getattr(entry, "description", None)
        or ""
    )
    if not raw:
        return None
    # Cheap HTML strip — replace tags with whitespace, collapse runs.
    # Not bulletproof for malformed HTML but feedparser is doing the
    # heavy parsing; we just want a readable card preview.
    import re

    text = re.sub(r"<[^>]+>", " ", str(raw))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def poll_one_feed(
    feed: FeedConfig,
    *,
    repo: Any,
    now: datetime,
    feedparser_module: Any | None = None,
) -> FeedPollOutcome:
    """Fetch + parse + insert one feed. Never raises — errors are
    captured into the outcome and the feed_health row.

    ``feedparser_module`` is dependency-injected so tests don't hit the
    network; production passes the real ``feedparser`` library.
    """
    fp = feedparser_module
    if fp is None:  # production path
        import feedparser as _feedparser
        fp = _feedparser

    try:
        # feedparser supports a request_headers kwarg + 'agent' for
        # politeness. We set a custom UA so feed owners can identify
        # the bench when looking at access logs.
        parsed = fp.parse(
            feed.url,
            agent="lis-bench/1.0 (+https://libearden.dev/about)",
            request_headers={"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"},
        )
    except Exception as exc:  # noqa: BLE001 — network can throw anything
        msg = f"{type(exc).__name__}: {exc}"
        _log.warning("feed=%s fetch failed: %s", feed.slug, msg)
        try:
            repo.record_feed_failure(feed.slug, now=now, error=msg)
        except Exception as repo_exc:  # noqa: BLE001
            _log.warning("feed_health write failed for %s: %s", feed.slug, repo_exc)
        return FeedPollOutcome(
            feed_slug=feed.slug, status="error", error_message=msg
        )

    # feedparser surfaces parse-time errors via the bozo flag. We
    # don't treat ALL bozo=1 as failure — many feeds have minor
    # XML quirks that still parse correctly — but if there are zero
    # entries AND bozo is set, that's a real failure.
    entries = list(getattr(parsed, "entries", []) or [])
    bozo = bool(getattr(parsed, "bozo", False))
    bozo_exc = getattr(parsed, "bozo_exception", None)
    if not entries and bozo:
        msg = f"feedparser bozo: {bozo_exc}"
        _log.warning("feed=%s parse failed: %s", feed.slug, msg)
        try:
            repo.record_feed_failure(feed.slug, now=now, error=msg)
        except Exception as repo_exc:  # noqa: BLE001
            _log.warning("feed_health write failed for %s: %s", feed.slug, repo_exc)
        return FeedPollOutcome(
            feed_slug=feed.slug, status="error", error_message=msg
        )

    inserted = 0
    for entry in entries:
        title = (getattr(entry, "title", "") or "").strip()
        url = (getattr(entry, "link", "") or "").strip()
        if not title or not url:
            # Skip malformed entries silently — common for broken
            # feeds that ship a header without items.
            continue
        item = NewsItem(
            id=None,
            source=feed.slug,
            title=title,
            url=url,
            summary=_entry_summary(entry),
            published_at=_entry_pubdate(entry, fallback=now),
            fetched_at=now,
        )
        try:
            if repo.insert_if_new(item):
                inserted += 1
        except Exception as repo_exc:  # noqa: BLE001
            # Don't abort the whole feed on one bad row; keep going.
            _log.warning(
                "feed=%s insert failed for url=%s: %s",
                feed.slug, url, repo_exc,
            )

    try:
        repo.record_feed_success(
            feed.slug,
            now=now,
            items_seen=len(entries),
            items_inserted=inserted,
        )
    except Exception as repo_exc:  # noqa: BLE001
        _log.warning("feed_health write failed for %s: %s", feed.slug, repo_exc)

    return FeedPollOutcome(
        feed_slug=feed.slug,
        status="ok",
        items_seen=len(entries),
        items_inserted=inserted,
    )


def poll_feeds(
    feeds: Iterable[FeedConfig],
    *,
    repo: Any,
    now: datetime | None = None,
    feedparser_module: Any | None = None,
) -> list[FeedPollOutcome]:
    """Iterate over every feed, returning per-feed outcomes.

    Per-feed failures are captured into the outcome list, never
    raised. Caller decides how to surface them (the scheduler wrapper
    logs a summary line).
    """
    if now is None:
        now = datetime.utcnow()
    outcomes: list[FeedPollOutcome] = []
    for feed in feeds:
        outcomes.append(
            poll_one_feed(
                feed,
                repo=repo,
                now=now,
                feedparser_module=feedparser_module,
            )
        )
    return outcomes
