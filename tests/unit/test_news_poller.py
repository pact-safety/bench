"""Tests for app.services.news_poller (rss-news-feed Phase 1).

No live network — the ``feedparser_module`` parameter lets tests pass
a stub that returns canned entry objects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from time import struct_time
from unittest.mock import MagicMock

import pytest

from app.services import news_poller


_NOW = datetime(2026, 5, 27, 12, 0, 0)


def _entry(
    *,
    title: str,
    link: str,
    summary: str | None = "<p>Some <b>html</b> summary.</p>",
    published_struct: struct_time | None = None,
) -> SimpleNamespace:
    """Mimic the shape feedparser returns for an entry."""
    e = SimpleNamespace(title=title, link=link)
    if summary is not None:
        e.summary = summary
    if published_struct is not None:
        e.published_parsed = published_struct
    return e


def _struct_time_from_dt(dt: datetime) -> struct_time:
    """Convert datetime → struct_time the way feedparser does (UTC)."""
    return dt.replace(tzinfo=timezone.utc).utctimetuple()


def _fake_feedparser(*, entries=None, bozo=False, bozo_exception=None, raise_on_parse=None):
    """Build a stub ``feedparser`` module with a ``.parse`` callable."""
    if raise_on_parse is not None:
        def _parse(url, **kwargs):
            raise raise_on_parse
    else:
        def _parse(url, **kwargs):
            return SimpleNamespace(
                entries=list(entries or []),
                bozo=bozo,
                bozo_exception=bozo_exception,
            )
    return SimpleNamespace(parse=_parse)


def _feed(slug: str = "anthropic", url: str = "https://example.test/feed"):
    return news_poller.FeedConfig(slug=slug, name="Test", url=url, tier=1)


# ---------------------------------------------------------------------------
# Happy-path ingest
# ---------------------------------------------------------------------------


def test_poll_one_feed_inserts_each_entry_once():
    """Every non-duplicate entry triggers a repo.insert_if_new(item).
    Outcome carries items_seen + items_inserted counters."""
    repo = MagicMock()
    repo.insert_if_new.return_value = True
    feed = _feed()
    fake = _fake_feedparser(
        entries=[
            _entry(title="T1", link="https://x/a", published_struct=_struct_time_from_dt(_NOW)),
            _entry(title="T2", link="https://x/b", published_struct=_struct_time_from_dt(_NOW)),
        ],
    )

    outcome = news_poller.poll_one_feed(
        feed, repo=repo, now=_NOW, feedparser_module=fake
    )

    assert outcome.status == "ok"
    assert outcome.items_seen == 2
    assert outcome.items_inserted == 2
    assert repo.insert_if_new.call_count == 2
    repo.record_feed_success.assert_called_once()


def test_dedup_does_not_count_existing_as_inserted():
    """When repo.insert_if_new returns False (URL already present),
    items_inserted stays at zero while items_seen counts the feed
    entry. This is the key idempotency property — re-running the same
    feed in the same hour creates no churn."""
    repo = MagicMock()
    repo.insert_if_new.return_value = False  # everything's a dupe
    feed = _feed()
    fake = _fake_feedparser(
        entries=[
            _entry(title="T1", link="https://x/a", published_struct=_struct_time_from_dt(_NOW)),
            _entry(title="T2", link="https://x/b", published_struct=_struct_time_from_dt(_NOW)),
        ],
    )

    outcome = news_poller.poll_one_feed(
        feed, repo=repo, now=_NOW, feedparser_module=fake
    )

    assert outcome.items_seen == 2
    assert outcome.items_inserted == 0


def test_summary_html_is_stripped():
    """Item summaries get HTML stripped + whitespace collapsed before
    persistence. Operator reads them as plain text in /news cards."""
    repo = MagicMock()
    repo.insert_if_new.return_value = True
    feed = _feed()
    captured: list = []

    def capture(item):
        captured.append(item)
        return True

    repo.insert_if_new.side_effect = capture

    fake = _fake_feedparser(
        entries=[
            _entry(
                title="T",
                link="https://x/a",
                summary="<p>A <a href=\"x\">linked</a>   summary.</p>",
                published_struct=_struct_time_from_dt(_NOW),
            ),
        ],
    )

    news_poller.poll_one_feed(feed, repo=repo, now=_NOW, feedparser_module=fake)

    assert len(captured) == 1
    assert captured[0].summary == "A linked summary."


def test_missing_pubdate_falls_back_to_now():
    """Entries without published_parsed get the bench's ``now`` as
    published_at — never crashes, never inserts NULL."""
    repo = MagicMock()
    repo.insert_if_new.return_value = True
    feed = _feed()
    captured: list = []

    def capture(item):
        captured.append(item)
        return True

    repo.insert_if_new.side_effect = capture

    fake = _fake_feedparser(
        entries=[_entry(title="T", link="https://x/a", published_struct=None)],
    )

    news_poller.poll_one_feed(feed, repo=repo, now=_NOW, feedparser_module=fake)

    assert captured[0].published_at == _NOW


def test_entries_missing_title_or_link_are_skipped():
    """Malformed entries don't crash the poll."""
    repo = MagicMock()
    repo.insert_if_new.return_value = True
    feed = _feed()
    fake = _fake_feedparser(
        entries=[
            _entry(title="Good", link="https://x/a", published_struct=_struct_time_from_dt(_NOW)),
            _entry(title="", link="https://x/b", published_struct=_struct_time_from_dt(_NOW)),
            _entry(title="No link", link="", published_struct=_struct_time_from_dt(_NOW)),
        ],
    )

    outcome = news_poller.poll_one_feed(
        feed, repo=repo, now=_NOW, feedparser_module=fake
    )

    # Only the good one calls insert.
    assert repo.insert_if_new.call_count == 1
    # Still counts as a successful tick.
    assert outcome.status == "ok"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_fetch_exception_records_failure_and_does_not_raise():
    repo = MagicMock()
    feed = _feed()
    fake = _fake_feedparser(raise_on_parse=ConnectionError("DNS resolution failed"))

    outcome = news_poller.poll_one_feed(
        feed, repo=repo, now=_NOW, feedparser_module=fake
    )

    assert outcome.status == "error"
    assert "ConnectionError" in outcome.error_message
    assert "DNS resolution failed" in outcome.error_message
    repo.record_feed_failure.assert_called_once()
    repo.insert_if_new.assert_not_called()
    repo.record_feed_success.assert_not_called()


def test_bozo_with_zero_entries_is_a_failure():
    """Bozo flag set AND no entries → record as failure (the feed
    XML is unparseable). Bozo with entries is tolerated (minor XML
    quirks)."""
    repo = MagicMock()
    feed = _feed()
    fake = _fake_feedparser(
        entries=[],
        bozo=True,
        bozo_exception=Exception("malformed xml"),
    )

    outcome = news_poller.poll_one_feed(
        feed, repo=repo, now=_NOW, feedparser_module=fake
    )

    assert outcome.status == "error"
    repo.record_feed_failure.assert_called_once()


def test_bozo_with_entries_is_tolerated():
    """Bozo with at least one entry → keep going, treat as success."""
    repo = MagicMock()
    repo.insert_if_new.return_value = True
    feed = _feed()
    fake = _fake_feedparser(
        entries=[_entry(title="T", link="https://x/a", published_struct=_struct_time_from_dt(_NOW))],
        bozo=True,
        bozo_exception=Exception("warn: nonfatal"),
    )

    outcome = news_poller.poll_one_feed(
        feed, repo=repo, now=_NOW, feedparser_module=fake
    )
    assert outcome.status == "ok"
    assert outcome.items_inserted == 1


def test_one_feeds_failure_does_not_block_others():
    """Per-feed isolation — the poll_feeds wrapper keeps iterating."""
    repo = MagicMock()
    repo.insert_if_new.return_value = True

    feed_a = _feed(slug="a", url="https://a.test/feed")
    feed_b = _feed(slug="b", url="https://b.test/feed")

    # Track which feed's parse was called and respond accordingly.
    parse_log: list = []

    def parse(url, **kwargs):
        parse_log.append(url)
        if url == "https://a.test/feed":
            raise RuntimeError("a failed")
        return SimpleNamespace(
            entries=[
                _entry(title="T", link="https://b/1", published_struct=_struct_time_from_dt(_NOW))
            ],
            bozo=False,
            bozo_exception=None,
        )

    fake = SimpleNamespace(parse=parse)

    outcomes = news_poller.poll_feeds(
        [feed_a, feed_b], repo=repo, now=_NOW, feedparser_module=fake
    )

    assert len(outcomes) == 2
    assert outcomes[0].status == "error"
    assert outcomes[1].status == "ok"
    assert outcomes[1].items_inserted == 1


def test_repo_insert_failure_does_not_abort_remaining_entries():
    """One bad row shouldn't kill the whole feed."""
    repo = MagicMock()
    feed = _feed()
    # First insert raises, second succeeds.
    repo.insert_if_new.side_effect = [RuntimeError("db blip"), True]
    fake = _fake_feedparser(
        entries=[
            _entry(title="T1", link="https://x/a", published_struct=_struct_time_from_dt(_NOW)),
            _entry(title="T2", link="https://x/b", published_struct=_struct_time_from_dt(_NOW)),
        ],
    )

    outcome = news_poller.poll_one_feed(
        feed, repo=repo, now=_NOW, feedparser_module=fake
    )

    # The bad row gets logged + skipped; the good row inserts.
    assert repo.insert_if_new.call_count == 2
    assert outcome.items_inserted == 1
    assert outcome.status == "ok"


# ---------------------------------------------------------------------------
# Feed registry parsing
# ---------------------------------------------------------------------------


def test_load_feeds_from_toml_parses_minimal_file(tmp_path: Path):
    p = tmp_path / "news_feeds.toml"
    p.write_text(
        """
        [[feed]]
        slug = "a"
        name = "Alpha"
        url = "https://a.test/feed"
        tier = 1

        [[feed]]
        slug = "b"
        name = "Beta"
        url = "https://b.test/feed"
        tier = 2
        """
    )
    feeds = news_poller.load_feeds_from_toml(p)
    assert len(feeds) == 2
    assert feeds[0].slug == "a" and feeds[0].tier == 1
    assert feeds[1].slug == "b" and feeds[1].tier == 2


def test_load_feeds_from_toml_returns_empty_when_file_absent(tmp_path: Path):
    """A missing news_feeds.toml is the fresh-repo state — empty list,
    no exception."""
    feeds = news_poller.load_feeds_from_toml(tmp_path / "nope.toml")
    assert feeds == []


def test_load_feeds_skips_malformed_entries(tmp_path: Path, caplog):
    """Missing required keys → skip that entry, keep parsing rest."""
    p = tmp_path / "news_feeds.toml"
    p.write_text(
        """
        [[feed]]
        slug = "good"
        name = "Good"
        url = "https://x.test/feed"

        [[feed]]
        slug = "missing-url"
        name = "Bad"
        """
    )
    feeds = news_poller.load_feeds_from_toml(p)
    assert len(feeds) == 1
    assert feeds[0].slug == "good"


def test_real_feeds_toml_parses_cleanly():
    """The shipped content/news_feeds.toml must parse without errors."""
    from app.config import REPO_ROOT

    feeds = news_poller.load_feeds_from_toml(REPO_ROOT / "content" / "news_feeds.toml")
    assert len(feeds) > 0, "shipped news_feeds.toml has no feeds"
    # Sanity-check Tier 1 has the labs.
    slugs = {f.slug for f in feeds}
    assert "anthropic" in slugs
