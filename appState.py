
import threading

from database import RefereeDbCockroach
from auth_nicegui import AuthManager
from uiData import getAllData
from generateWorkload import WorkloadGenerator, resolve_workload_organization_id
from data_store import has_match_schedule, has_workload, load_meta


# Global state
class AppState:
    def __init__(self, logger, ui):
        self.logger = logger
        self.ui = ui
        self.auth_manager = AuthManager()
        self.db = RefereeDbCockroach()
        self.all_match_data = None
        self.dates = []
        self.match_data_org_id = None
        self.current_tab = "Enter a Mentor Report"
        self.loaded = False
        self._loading = False
        self._load_lock = threading.Lock()
        # Workload data (loaded from filesystem cache written by sync_worker)
        self.workload_output = None
        self.workload_error = None
        self.workload_loading = False
        self._workload_lock = threading.Lock()

    def _data_org_id(self, organization_id=None) -> int:
        if organization_id is not None:
            return organization_id
        org_id = self.auth_manager.get_current_organization_id()
        if org_id is not None:
            return org_id
        return resolve_workload_organization_id(self.db)

    def load_data(self, force_reload=False, organization_id=None):
        """Load season match schedule for the given or current organization (from cache)."""
        org_id = self._data_org_id(organization_id)

        with self._load_lock:
            should_load = (
                force_reload
                or self.all_match_data is None
                or self.match_data_org_id != org_id
            )
            if should_load and not self._loading:
                self._loading = True
                try:
                    self.logger.info("Loading match data for organization_id=%s...", org_id)
                    self.all_match_data = getAllData(organization_id=org_id, force_refresh=force_reload)
                    self.dates = list(self.all_match_data.keys()) if self.all_match_data else []
                    self.match_data_org_id = org_id
                    self.loaded = True
                    self.logger.info(
                        "Successfully loaded %s dates for organization_id=%s",
                        len(self.dates),
                        org_id,
                    )
                except Exception as e:
                    self.logger.error(f"Failed to load data: {e}", exc_info=True)
                    self._loading = False
                    raise
                finally:
                    self._loading = False

    def is_data_loaded(self, organization_id=None) -> bool:
        """Check if match data is available for the requested (or current) org."""
        org_id = self._data_org_id(organization_id)
        if (
            self.loaded
            and self.all_match_data is not None
            and self.match_data_org_id == org_id
        ):
            return True
        # Cache on disk counts even before this process has loaded it into memory
        return has_match_schedule(org_id)

    def load_workload_data(self, force_reload=False, organization_id=None):
        """Load workload data for the given or current organization (from cache)."""
        org_id = self._data_org_id(organization_id)
        cached_org_id = getattr(self.ui, 'resultsFromRunOrgId', None)

        with self._workload_lock:
            should_load = (
                force_reload
                or cached_org_id != org_id
                or not hasattr(self.ui, 'resultsFromRun')
                or self.ui.resultsFromRun is None
            )
            if should_load and not self.workload_loading:
                self.workload_loading = True
                try:
                    self.logger.info("Loading workload data for organization_id=%s...", org_id)
                    generator = WorkloadGenerator()
                    self.workload_output = generator.get_workload_output(org_id, force_refresh=force_reload)
                    self.ui.resultsFromRun = generator.get_workload_results(org_id, force_refresh=False)
                    self.ui.resultsFromRunOrgId = org_id
                    if not self.workload_output:
                        self.workload_output = 'No workload data available'
                    self.workload_error = None
                    self.logger.info("Successfully loaded workload data for organization_id=%s", org_id)
                except Exception as e:
                    self.logger.error(f"Failed to load workload data: {e}", exc_info=True)
                    self.workload_error = str(e)
                    meta = load_meta(org_id) or {}
                    if meta.get('workload_error'):
                        self.workload_error = meta['workload_error']
                    raise
                finally:
                    self.workload_loading = False

    def is_loading(self) -> bool:
        """Disk reads are fast; no background scrape in the UI process."""
        return self._loading or self.workload_loading

    def sync_status_message(self, organization_id=None) -> str | None:
        """Human-readable message when cache is missing or last sync failed."""
        org_id = self._data_org_id(organization_id)
        meta = load_meta(org_id)
        if not meta:
            if not has_match_schedule(org_id) and not has_workload(org_id):
                return 'Waiting for the sync worker to populate data for this organization.'
            return None
        if meta.get('last_sync_error'):
            return f"Last sync had errors: {meta['last_sync_error']}"
        if meta.get('match_schedule_error'):
            return f"Match schedule sync error: {meta['match_schedule_error']}"
        if meta.get('workload_error'):
            return f"Workload sync error: {meta['workload_error']}"
        return None
