#!/usr/bin/env python3
"""
Standalone sync worker: scrapes assignment providers and writes results to DATA_CACHE_DIR.

Run on a schedule (Fly.io worker process) or once for local testing:

    python sync_worker.py --once
    python sync_worker.py --once --org-id 123
    python sync_worker.py   # loop every SYNC_INTERVAL_HOURS (default 2)
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time

import rmaLogging  # noqa: F401 — configures logging

from data_store import get_cache_dir
from sync_service import list_organization_ids, sync_all_organizations, sync_organization

logger = logging.getLogger(__name__)

_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    logger.info('Received signal %s, shutting down after current sync...', signum)
    _shutdown = True


def _interval_seconds() -> int:
    hours = float(os.environ.get('SYNC_INTERVAL_HOURS', '2'))
    return max(60, int(hours * 3600))


def run_once(org_id: int | None = None) -> None:
    cache_dir = get_cache_dir()
    logger.info('Sync worker using cache dir: %s', cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if org_id is not None:
        sync_organization(org_id)
    else:
        sync_all_organizations()


def run_loop(org_id: int | None = None) -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    interval = _interval_seconds()
    logger.info('Sync worker starting (interval=%ss, org_id=%s)', interval, org_id or 'all')

    while not _shutdown:
        started = time.monotonic()
        try:
            run_once(org_id=org_id)
        except Exception as exc:
            logger.error('Sync cycle failed: %s', exc, exc_info=True)

        if _shutdown:
            break

        elapsed = time.monotonic() - started
        sleep_for = max(0, interval - elapsed)
        logger.info('Next sync in %.0f seconds', sleep_for)
        # Sleep in small chunks so SIGTERM is handled promptly
        deadline = time.monotonic() + sleep_for
        while not _shutdown and time.monotonic() < deadline:
            time.sleep(min(5, deadline - time.monotonic()))

    logger.info('Sync worker stopped')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='RefMentor assignment data sync worker')
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run a single sync cycle and exit (default: loop forever)',
    )
    parser.add_argument(
        '--org-id',
        type=int,
        default=None,
        help='Sync only this organization id (default: all organizations)',
    )
    parser.add_argument(
        '--list-orgs',
        action='store_true',
        help='Print organization ids and exit',
    )
    args = parser.parse_args(argv)

    if args.list_orgs:
        for oid in list_organization_ids():
            print(oid)
        return 0

    if args.once:
        run_once(org_id=args.org_id)
        return 0

    run_loop(org_id=args.org_id)
    return 0


if __name__ == '__main__':
    sys.exit(main())
