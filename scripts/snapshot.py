"""Visual snapshot harness — headless Chromium via Playwright.

Captures key pages at light + dark theme, viewport sizes, and persona
states. Use during dev for "did the visual change look the way I
think?" verification, and as a regression gate before shipping.

Workflow:
    .venv/bin/python scripts/snapshot.py --persona grinder --reset
    # writes PNGs to data/snapshots/<run-id>/<page>--<theme>.png
    # prints the paths so you can open / Read them

Implementation notes:
- We spawn uvicorn in a subprocess on an ephemeral port so the script
  is self-contained.
- After seeding the DB with the chosen persona, we navigate to each
  URL twice (one screenshot per theme) and write a PNG per
  (page, theme).
- Theme switch is done by setting localStorage before nav (the same
  mechanism the in-page toggle uses), so the document loads in the
  right state without a flash.
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


PAGES = [
    # (slug, url-path, viewport_height)
    ("home",             "/",                                         1200),
    ("skills",           "/skills",                                   1200),
    ("library",          "/library",                                  1400),
    ("onboarding",       "/onboarding",                               900),
    ("assess-question",  None,                                        900),  # filled per-run
    ("assess-result",    None,                                        1100),
    ("problem-compose",  "/problem/scaled-dot-product-attention",     1400),
    ("problem-debug",    "/problem/debug-causal-mask",                1400),
    ("problem-algo",     "/problem/algo-validation-window",           1400),
    ("warmup",           "/problem/warmup-heapq-top-k?warmup=1",      1100),
    ("settings",         "/settings",                                 900),
    ("credentials",      "/credentials",                              900),
    ("credentials-gap",  None,                                        1300),  # filled per-run
]


def free_port() -> int:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def reset_db() -> None:
    """DESTRUCTIVE: wipes the SQLite file. Also clears the
    feedback inbox markdown mirror so /feedback/inbox stays consistent
    with the (now-empty) DB. Be loud about it — past mistakes lost
    user feedback that lived only in DB rows."""
    data_dir = REPO_ROOT / "data"
    db = data_dir / "prep.db"
    if db.exists():
        print(f"[snapshot] !! DESTRUCTIVE: wiping {db}")
    for name in ("prep.db", "prep.db-shm", "prep.db-wal"):
        p = data_dir / name
        if p.exists():
            p.unlink()
    # Also clear the markdown mirrors so they don't pretend rows
    # still exist.
    for name in ("inbox.md", "archive.md"):
        p = data_dir / "feedback" / name
        if p.exists():
            p.unlink()


def seed_persona(persona: str) -> dict:
    """Run mock_user.py in-process to populate the DB."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import mock_user
    return mock_user.run_persona(persona, reset=False, seed=42)


def seed_completed_reading() -> None:
    """Mark one reading complete so the scheduler shows content-aligned
    boost components on the why-surfaced expander."""
    from app.main import content_repo
    r = content_repo.get_by_slug("r01-attention-is-all-you-need")
    if r is not None:
        content_repo.mark_completed(1, r.id)


def seed_credentials() -> int | None:
    """Upload the sample CV + analyze it so the credentials pages have
    real content to snapshot."""
    cv_path = REPO_ROOT / "scripts" / "sample_cv.txt"
    if not cv_path.exists():
        return None
    from fastapi.testclient import TestClient
    from app.main import app, credentials_repo
    client = TestClient(app, follow_redirects=False)
    r = client.post(
        "/credentials",
        files={"file": ("sample_cv.txt", cv_path.read_bytes(), "text/plain")},
    )
    if r.status_code != 303:
        return None
    run_id = int(r.headers["location"].split("/")[-1])
    client.post(f"/credentials/{run_id}/analyze")
    return run_id


def find_in_progress_run() -> int | None:
    """Return an in-progress assessment run id if one exists (used to
    snapshot the question page mid-flow)."""
    import sqlite3
    db = REPO_ROOT / "data" / "prep.db"
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    r = conn.execute(
        "SELECT id FROM assessment_runs WHERE completed_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return r[0] if r else None


def find_any_completed_run() -> int | None:
    import sqlite3
    db = REPO_ROOT / "data" / "prep.db"
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    r = conn.execute(
        "SELECT id FROM assessment_runs WHERE completed_at IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return r[0] if r else None


def snapshot(persona: str, reset: bool, only: str | None) -> Path:
    if reset:
        reset_db()
    cred_run_id = None
    if persona != "skip":
        seed_persona(persona)
        seed_completed_reading()
        cred_run_id = seed_credentials()

    out_root = REPO_ROOT / "data" / "snapshots"
    out_root.mkdir(parents=True, exist_ok=True)
    run_dir = out_root / datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir()
    print(f"[snapshot] writing to {run_dir}")

    # For the in-progress assessment page: start a fresh assessment run
    # so we can hit /assess/<id> while it still has questions to ask.
    completed_run = find_any_completed_run()
    pending_run = find_in_progress_run()
    if pending_run is None:
        # Create one
        import urllib.request
        # We need the server up first; do this after spawning uvicorn.
        pending_run = None  # fill later if persona != cold_start

    port = free_port()
    proc = subprocess.Popen(
        [
            str(REPO_ROOT / ".venv" / "bin" / "uvicorn"),
            "app.main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", "warning",
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Wait for the server to be ready
        import urllib.request
        for _ in range(30):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/onboarding", timeout=0.5)
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("uvicorn never came up")

        # If we need an in-progress run for the question snapshot, start one.
        if pending_run is None:
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/onboarding/start", method="POST")
                with urllib.request.urlopen(req, timeout=2) as r:
                    pass
            except Exception:
                pass
            pending_run = find_in_progress_run()

        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for theme in ("light", "dark"):
                    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
                    # Pre-seed localStorage with the theme so the document
                    # loads in the right mode (matches the inline script
                    # in base.html).
                    ctx.add_init_script(f'window.localStorage.setItem("theme", "{theme}");')
                    page = ctx.new_page()
                    for slug, path, vh in PAGES:
                        if only and only not in slug:
                            continue
                        # Build URL
                        if slug == "assess-question":
                            if pending_run is None:
                                print(f"[snapshot] skipping {slug}: no pending run")
                                continue
                            url = f"http://127.0.0.1:{port}/assess/{pending_run}"
                        elif slug == "assess-result":
                            if completed_run is None:
                                print(f"[snapshot] skipping {slug}: no completed run")
                                continue
                            url = f"http://127.0.0.1:{port}/assess/{completed_run}/result"
                        elif slug == "credentials-gap":
                            if cred_run_id is None:
                                print(f"[snapshot] skipping {slug}: no credentials run")
                                continue
                            url = f"http://127.0.0.1:{port}/credentials/{cred_run_id}/gap"
                        else:
                            url = f"http://127.0.0.1:{port}{path}"

                        page.set_viewport_size({"width": 1280, "height": vh})
                        try:
                            page.goto(url, wait_until="networkidle", timeout=8000)
                        except Exception as e:
                            print(f"[snapshot] {slug} ({theme}) failed to load: {e}")
                            continue
                        # Small wait for fonts / SVG layout
                        page.wait_for_timeout(400)
                        out = run_dir / f"{slug}--{theme}.png"
                        page.screenshot(path=str(out), full_page=True)
                        print(f"  - {out.name}")
                    ctx.close()
            finally:
                browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    return run_dir


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--persona", default="grinder", help="mock_user persona to seed; 'skip' for current DB state")
    p.add_argument("--reset", action="store_true", help="wipe DB before seeding")
    p.add_argument("--only", default=None, help="substring filter to limit which pages get snapshotted")
    args = p.parse_args()
    out = snapshot(args.persona, reset=args.reset, only=args.only)
    print(f"\nSnapshots in: {out}")


if __name__ == "__main__":
    main()
