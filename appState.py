
import threading

from database import RefereeDbCockroach
from auth_nicegui import AuthManager
from uiData import getAllData
from generateWorkload import WorkloadGenerator, resolve_workload_organization_id


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
        # Initialize workload data storage
        self.workload_output = None
        self.workload_error = None
        self.workload_loading = False
        self._workload_lock = threading.Lock()
        # Background loads have no browser session — use default org, not app.storage.user
        default_org_id = resolve_workload_organization_id(self.db)
        self._start_background_load(organization_id=default_org_id)
        self._start_background_workload_load(organization_id=default_org_id)
        # Start periodic provider reload scheduler
        self._start_periodic_reload_scheduler()

    def _data_org_id(self, organization_id=None) -> int:
        if organization_id is not None:
            return organization_id
        org_id = self.auth_manager.get_current_organization_id()
        if org_id is not None:
            return org_id
        return resolve_workload_organization_id(self.db)

    def _start_background_load(self, force_reload=False, organization_id=None):
        """Start loading match schedule data in a background thread without blocking."""

        def load_in_background():
            try:
                self.logger.info("Starting background match data load...")
                self.load_data(force_reload=force_reload, organization_id=organization_id)
                self.logger.info("Background match data load completed")
            except Exception as e:
                self.logger.error(f"Error in background data load: {e}", exc_info=True)

        thread = threading.Thread(target=load_in_background, daemon=True)
        thread.start()

    def load_data(self, force_reload=False, organization_id=None):
        """Load season match schedule for the given or current organization."""
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
        """Check if match data has been loaded for the requested (or current) org."""
        org_id = self._data_org_id(organization_id)
        result = (
            self.loaded
            and self.all_match_data is not None
            and self.match_data_org_id == org_id
        )
        self.logger.debug(
            "is_data_loaded: %s (loaded=%s, match_org=%s, want_org=%s, data_len=%s)",
            result,
            self.loaded,
            self.match_data_org_id,
            org_id,
            len(self.all_match_data) if self.all_match_data else 0,
        )
        return result

    def _start_background_workload_load(self, force_reload=False, organization_id=None):
        """Start loading workload data in a background thread without blocking"""

        def load_workload_in_background():
            try:
                self.logger.info("Starting background workload data load...")
                self.load_workload_data(force_reload=force_reload, organization_id=organization_id)
                self.logger.info("Background workload data load completed")
            except Exception as e:
                self.logger.error(f"Error in background workload data load: {e}", exc_info=True)

        thread = threading.Thread(target=load_workload_in_background, daemon=True)
        thread.start()

    def _workload_org_id(self, organization_id=None) -> int:
        return self._data_org_id(organization_id)

    def load_workload_data(self, force_reload=False, organization_id=None):
        """Load workload data for the given or current organization."""
        org_id = self._workload_org_id(organization_id)
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
                    raise
                finally:
                    self.workload_loading = False

    def is_loading(self) -> bool:
        """Check if match data is currently being loaded"""
        return self._loading

    # Interval between automatic full refetches from the assignment provider (and workload rebuild).
    RELOAD_INTERVAL_HOURS = 2

    def _schedule_periodic_reload(self):
        """Schedule the next full data reload after RELOAD_INTERVAL_HOURS."""
        seconds_until_reload = self.RELOAD_INTERVAL_HOURS * 3600

        self.logger.info(
            f"Scheduling next assignment-provider data reload in {self.RELOAD_INTERVAL_HOURS} hour(s) "
            f"({seconds_until_reload} seconds)"
        )

        def perform_periodic_reload():
            try:
                self.logger.info(
                    f"Starting scheduled data reload (every {self.RELOAD_INTERVAL_HOURS} hours)..."
                )
                default_org_id = resolve_workload_organization_id(self.db)
                self._start_background_load(force_reload=True, organization_id=default_org_id)
                self._start_background_workload_load(force_reload=True, organization_id=default_org_id)
                self.logger.info("Scheduled data reload completed")
            except Exception as e:
                self.logger.error(f"Error during scheduled data reload: {e}", exc_info=True)
            finally:
                self._schedule_periodic_reload()

        timer = threading.Timer(seconds_until_reload, perform_periodic_reload)
        timer.daemon = True
        timer.start()

    def _start_periodic_reload_scheduler(self):
        """Start the periodic reload scheduler (see RELOAD_INTERVAL_HOURS)."""
        self._schedule_periodic_reload()
