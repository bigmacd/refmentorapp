"""
Sync assignment-provider data to the filesystem cache (see data_store.py).

Used by sync_worker.py; not imported by the NiceGUI app at startup.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from assignment_providers import get_assignment_provider, get_workload_config
from data_store import (
    record_sync_error,
    save_match_schedule,
    save_meta,
    save_workload,
)
from database import RefereeDbCockroach
from generateWorkload import WorkloadGenerator

logger = logging.getLogger(__name__)


def list_organization_ids(db: Optional[RefereeDbCockroach] = None) -> list[int]:
    db = db or RefereeDbCockroach()
    return [org['id'] for org in db.getOrganizations()]


def sync_match_schedule(organization_id: int, db: Optional[RefereeDbCockroach] = None) -> dict:
    """Fetch season match schedule from the org's provider and write to disk."""
    db = db or RefereeDbCockroach()
    org = db.getOrganizationById(organization_id)
    if not org:
        raise ValueError(f'Organization id {organization_id} not found')

    config = get_workload_config(org)
    provider = get_assignment_provider(config)
    save_meta(
        organization_id,
        organization_name=org.get('name'),
        provider=config.provider,
    )

    if provider is None:
        logger.info(
            'No assignment provider for org %s (%s); writing empty match schedule',
            organization_id,
            org.get('name'),
        )
        save_match_schedule(organization_id, {})
        return {}

    logger.info(
        'Syncing match schedule for org %s (%s) via provider=%s',
        organization_id,
        org.get('name'),
        config.provider,
    )
    data = provider.get_season_match_schedule()
    save_match_schedule(organization_id, data)
    logger.info(
        'Saved match schedule for org %s: %s dates',
        organization_id,
        len(data) if data else 0,
    )
    return data


def sync_workload(organization_id: int) -> tuple[str, dict]:
    """Generate workload (includes live assignment scrape + DB updates) and write to disk."""
    logger.info('Syncing workload for organization_id=%s', organization_id)
    generator = WorkloadGenerator()
    output, results = generator.generate_and_persist(organization_id)
    save_workload(organization_id, output, results)
    logger.info('Saved workload for organization_id=%s', organization_id)
    return output, results


def sync_organization(organization_id: int, db: Optional[RefereeDbCockroach] = None) -> dict:
    """
    Full sync for one organization: match schedule then workload.
    Errors on one step are recorded in meta; the other step still runs.
    """
    db = db or RefereeDbCockroach()
    org = db.getOrganizationById(organization_id)
    if not org:
        raise ValueError(f'Organization id {organization_id} not found')

    logger.info('Starting sync for org %s (%s)', organization_id, org.get('name'))
    errors: list[str] = []

    try:
        sync_match_schedule(organization_id, db=db)
    except Exception as exc:
        msg = f'match schedule: {exc}'
        logger.error('Sync failed for org %s — %s', organization_id, msg, exc_info=True)
        record_sync_error(organization_id, match_error=str(exc))
        errors.append(msg)

    config = get_workload_config(org)
    if get_assignment_provider(config) is None:
        logger.info('Skipping workload sync for org %s (no provider)', organization_id)
        save_workload(organization_id, '', {})
    else:
        try:
            sync_workload(organization_id)
        except Exception as exc:
            msg = f'workload: {exc}'
            logger.error('Sync failed for org %s — %s', organization_id, msg, exc_info=True)
            record_sync_error(organization_id, workload_error=str(exc))
            errors.append(msg)

    meta = save_meta(
        organization_id,
        last_sync_completed_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
    if errors:
        save_meta(organization_id, last_sync_error='; '.join(errors))
    else:
        save_meta(organization_id, last_sync_error=None)

    logger.info('Finished sync for org %s (%s)', organization_id, org.get('name'))
    return meta


def sync_all_organizations(db: Optional[RefereeDbCockroach] = None) -> list[dict]:
    """Sync every organization in the database."""
    db = db or RefereeDbCockroach()
    results = []
    for org_id in list_organization_ids(db):
        try:
            results.append(sync_organization(org_id, db=db))
        except Exception as exc:
            logger.error('Failed to sync org %s: %s', org_id, exc, exc_info=True)
            record_sync_error(org_id, match_error=str(exc), workload_error=str(exc))
    return results
