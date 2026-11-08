"""Processes uploaded learning materials (ADR 0004): `python -m app.worker`.

Run one or more of these beside the API when `DOCUMENT_PROCESSING=worker`. It takes queued
versions from the database, so it needs only `DATABASE_URL` and the same storage settings as
the API. `--once` processes what's queued and stops (for a scheduled job instead of a service).
"""

import argparse
import logging
import time

from app.core.storage import get_storage
from app.db.session import SessionLocal
from app.documents.processing import process_queued, recover_stuck

logger = logging.getLogger("app.worker")


def run(once: bool = False, poll_seconds: float = 3.0) -> None:
    storage = get_storage()
    while True:
        with SessionLocal() as db:
            recover_stuck(db)
            done = process_queued(db, storage, limit=5)
        if done:
            logger.info("Processed %d upload(s)", done)
        elif once:
            return
        else:
            time.sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process uploaded learning materials.")
    parser.add_argument("--once", action="store_true", help="process what's queued, then stop")
    parser.add_argument("--poll", type=float, default=3.0, help="seconds between checks")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(once=args.once, poll_seconds=args.poll)


if __name__ == "__main__":
    main()
