import logging
import os
from datetime import datetime
from typing import Optional

from assignment_providers import get_workload_config, get_assignment_provider
from data_store import allow_live_fetch, load_match_schedule, save_match_schedule
from database import RefereeDbCockroach

logger = logging.getLogger(__name__)


class UIData:
    """
    Singleton cache for season match schedule data, keyed by organization_id.
    Fetches through the assignment provider layer (MSL for VYS, etc.).
    """
    _instance: Optional['UIData'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(UIData, cls).__new__(cls)
        return cls._instance

    def __init__(self, ttl_hours: int = 2):
        if not self._initialized:
            # org_id -> {'data': dict, 'fetched_at': datetime}
            self._cache: dict[int, dict] = {}
            self._ttl_seconds: int = ttl_hours * 3600
            self._process_id: int = os.getpid()
            self._initialized = True

            web_concurrency = os.environ.get('WEB_CONCURRENCY')
            if web_concurrency and int(web_concurrency) > 1:
                logger.warning(
                    f"WEB_CONCURRENCY={web_concurrency} detected. "
                    f"Each uvicorn worker process (PID: {self._process_id}) will have its own singleton instance. "
                    f"Consider using a shared cache (Redis/file-based) for multi-worker deployments."
                )
            else:
                logger.info(f"UIData singleton initialized in process PID: {self._process_id}")

    def _is_stale(self, organization_id: int) -> bool:
        entry = self._cache.get(organization_id)
        if not entry or entry.get('fetched_at') is None:
            return True
        elapsed = (datetime.now() - entry['fetched_at']).total_seconds()
        return elapsed >= self._ttl_seconds

    def _fetch_data(self, organization_id: int) -> dict:
        db = RefereeDbCockroach()
        org = db.getOrganizationById(organization_id)
        if not org:
            raise ValueError(f'Organization id {organization_id} not found')

        config = get_workload_config(org)
        provider = get_assignment_provider(config)
        if provider is None:
            logger.warning(
                'No assignment provider for org %s (%s); returning empty match schedule',
                organization_id,
                org.get('name'),
            )
            empty = {}
            self._cache[organization_id] = {'data': empty, 'fetched_at': datetime.now()}
            return empty

        logger.info(
            'Fetching season match schedule for org %s (%s) via provider=%s',
            organization_id,
            org.get('name'),
            config.provider,
        )
        try:
            data = provider.get_season_match_schedule()
            self._cache[organization_id] = {'data': data, 'fetched_at': datetime.now()}
            logger.info(
                'Fetched match schedule for org %s: %s dates',
                organization_id,
                len(data) if data else 0,
            )
            return data
        except RuntimeError:
            raise
        except Exception as e:
            logger.error('Failed to fetch match schedule for org %s: %s', organization_id, e, exc_info=True)
            raise RuntimeError(
                f"Failed to retrieve match data for organization {org.get('name')}: {e}"
            ) from e

    def getAllData(self, organization_id: int, force_refresh: bool = False) -> dict:
        """
        Get season match schedule for an organization.

        Reads from the filesystem cache when available. Live provider fetch only when
        ALLOW_LIVE_FETCH=true (local dev without a worker).
        """
        if not force_refresh:
            cached = load_match_schedule(organization_id)
            if cached is not None:
                self._cache[organization_id] = {'data': cached, 'fetched_at': datetime.now()}
                return cached

        if not allow_live_fetch():
            if organization_id in self._cache:
                return self._cache[organization_id]['data']
            raise RuntimeError(
                'Match schedule is not available yet. '
                'The sync worker will populate the cache shortly.'
            )

        if force_refresh or self._is_stale(organization_id):
            data = self._fetch_data(organization_id)
            save_match_schedule(organization_id, data)
            return data
        return self._cache[organization_id]['data']

    def refresh(self, organization_id: int) -> dict:
        return self.getAllData(organization_id, force_refresh=True)

    def get_last_fetch_time(self, organization_id: int = None) -> Optional[datetime]:
        if organization_id is None:
            if not self._cache:
                return None
            return max(
                (e['fetched_at'] for e in self._cache.values() if e.get('fetched_at')),
                default=None,
            )
        entry = self._cache.get(organization_id)
        return entry['fetched_at'] if entry else None

    def clear_cache(self, organization_id: int = None) -> None:
        if organization_id is None:
            self._cache.clear()
        else:
            self._cache.pop(organization_id, None)

    def get_process_info(self) -> dict:
        web_concurrency = os.environ.get('WEB_CONCURRENCY')
        return {
            'process_id': self._process_id,
            'web_concurrency_env': web_concurrency,
            'estimated_workers': int(web_concurrency) if web_concurrency else 1,
            'cached_orgs': list(self._cache.keys()),
            'note': 'Each uvicorn worker is a separate process with its own singleton instance',
        }


def getAllData(organization_id: int = None, force_refresh: bool = False) -> dict:
    """
    Convenience wrapper. If organization_id is omitted, uses the default org
    (ORGANIZATION_ID env / Default / first org) for background startup.
    """
    if organization_id is None:
        organization_id = RefereeDbCockroach().getDefaultOrganizationId()
    return UIData().getAllData(organization_id, force_refresh=force_refresh)
