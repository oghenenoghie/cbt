"""Background work: `python -m app.worker`.

It processes uploaded learning materials (ADR 0004) and requests for AI question drafts
(ADR 0005). Run one or more beside the API when `DOCUMENT_PROCESSING=worker` or
`AI_PROCESSING=worker`. It takes queued work from the database, so it needs `DATABASE_URL`, the
same storage settings as the API and, for drafting, the AI settings. `--once` processes what's
queued and stops (for a scheduled job instead of a service).
"""

import argparse
import logging
import time

from app.ai import processing as ai_processing
from app.core.storage import get_storage
from app.db.session import SessionLocal
from app.documents.processing import process_queued, recover_stuck

logger = logging.getLogger("app.worker")


def run(once: bool = False, poll_seconds: float = 3.0) -> None:
    storage = get_storage()
    while True:
        with SessionLocal() as db:
            recover_stuck(db)
            ai_processing.recover_stuck(db)
            uploads = process_queued(db, storage, limit=5)
            drafts = ai_processing.process_queued(db, limit=2)
        if uploads:
            logger.info("Processed %d upload(s)", uploads)
        if drafts:
            logger.info("Drafted %d request(s)", drafts)
        if uploads or drafts:
            continue
        if once:
            return
        else:
            time.sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process uploaded materials and AI draft requests."
    )
    parser.add_argument("--once", action="store_true", help="process what's queued, then stop")
    parser.add_argument("--poll", type=float, default=3.0, help="seconds between checks")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(once=args.once, poll_seconds=args.poll)


if __name__ == "__main__":
    main()
