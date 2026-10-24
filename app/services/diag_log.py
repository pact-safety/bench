from __future__ import annotations

import logging
import threading
from collections import deque


# Keep only the latest ~200 formatted events for quick in-app triage.
_RING_MAXLEN = 200
_RING: deque[str] = deque(maxlen=_RING_MAXLEN)
_RING_LOCK = threading.Lock()
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


class _RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            return

        with _RING_LOCK:
            _RING.append(line)


def install() -> None:
    """Attach the in-memory ring handler to the root logger once."""
    global _INSTALLED

    if _INSTALLED:
        return

    with _INSTALL_LOCK:
        if _INSTALLED:
            return

        root = logging.getLogger()
        for existing in root.handlers:
            if isinstance(existing, _RingHandler):
                _INSTALLED = True
                return

        handler = _RingHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(handler)
        _INSTALLED = True


def recent_events() -> list[str]:
    """Return ring contents newest-first for debugging recency."""
    with _RING_LOCK:
        # deque stores oldest→newest; reverse for UI so "what just broke"
        # is visible at the top of the page.
        return list(reversed(_RING))


def clear() -> None:
    """Test helper: reset in-memory ring contents."""
    with _RING_LOCK:
        _RING.clear()
