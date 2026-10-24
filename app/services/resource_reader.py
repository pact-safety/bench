"""Select reviewed external curriculum pages for the embedded reader."""

from __future__ import annotations

import re


# Keep the browser's destination unambiguous: these catalog links need no
# credentials, queries, percent encoding, or path normalization.
_ATLAS_READER_URL = re.compile(
    r"https://ai-safety-atlas\.com(?::443)?/chapters/v1/"
    r"(?:capabilities|risks|strategies|governance)/"
    r"(?:[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)*/?)?"
    r"(?:#[A-Za-z0-9_.:-]+)?"
)


def resource_reader_url(url: str) -> str | None:
    """Return a trusted catalog URL when its provider supports our reader."""
    if isinstance(url, str) and _ATLAS_READER_URL.fullmatch(url):
        return url
    return None
