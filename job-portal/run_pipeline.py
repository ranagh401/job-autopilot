"""One pipeline pass, for a scheduler outside the web app.

GitHub Actions runs this hourly. It does everything except drive a real
browser (form filling needs Chromium and your review anyway), so:
fetch -> enrich -> score -> filter -> contacts -> tailor -> draft ->
approve -> send -> replies -> follow-ups -> prepare applications.

    python run_pipeline.py            # the full pass
    python run_pipeline.py fetch score send   # only these steps
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime

from app import emailer, scheduler
from app.db import SessionLocal, init_db
from app.profile import load_profile

STEPS = {
    "fetch": lambda s, p: scheduler.run_fetch(s, p),
    "enrich": lambda s, p: scheduler.run_enrich(s),
    "score": lambda s, p: scheduler.run_score(s, p),
    "cleanup": lambda s, p: scheduler.run_cleanup(s, p),
    "contacts": lambda s, p: scheduler.run_contacts(s),
    "tailor": lambda s, p: scheduler.run_tailor(s, p),
    "draft": lambda s, p: scheduler.run_draft(s, p),
    "autosend": lambda s, p: scheduler.run_autosend(s),
    "send": lambda s, p: scheduler.run_send(
        s, limit=20, gap=int(__import__("os").getenv("SEND_GAP_SECONDS", "30"))),
    "replies": lambda s, p: scheduler.run_replies(s),
    "followups": lambda s, p: scheduler.run_followups(s, p),
    "apply": lambda s, p: scheduler.run_apply(s, p),
}
DEFAULT_ORDER = ["fetch", "enrich", "score", "cleanup", "contacts",
                 "tailor", "draft", "autosend", "send", "replies",
                 "followups", "apply"]


def main(argv: list[str]) -> int:
    steps = [a for a in argv[1:] if a in STEPS] or DEFAULT_ORDER
    init_db()
    profile = load_profile()
    session = SessionLocal()
    failed = []
    print(f"pipeline start {datetime.now():%Y-%m-%d %H:%M} "
          f"({len(steps)} steps)", flush=True)
    try:
        for name in steps:
            try:
                print(f"[{name}] {STEPS[name](session, profile)}", flush=True)
            except Exception as e:
                failed.append(name)
                print(f"[{name}] FAILED {type(e).__name__}: {e}", flush=True)
                traceback.print_exc()
                session.rollback()
        print(f"\nsent today: {emailer.count_sent_today(session)}", flush=True)
    finally:
        session.close()
    if failed:
        print(f"steps that failed: {', '.join(failed)}", flush=True)
    # A failed step should not fail the whole run - the next hour retries.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
