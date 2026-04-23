
import threading
from contextlib import redirect_stdout
from io import StringIO

from database import RefereeDbCockroach
from auth_nicegui import AuthManager
from uiData import getAllData
from generateWorkload import run

# Global state
class AppState:
    def __init__(self, logger, ui):
        self.logger = logger
        self.ui = ui
        self.auth_manager = AuthManager()
        self.db = RefereeDbCockroach()
        self.all_match_data = None
        self.dates = []
        self.current_tab = "Enter a Mentor Report"
        self.loaded = False
        self._loading = False
        self._load_lock = threading.Lock()
        # Initialize workload data storage
        self.workload_output = None
        self.workload_error = None
        self.workload_loading = False
        self._workload_lock = threading.Lock()
        # Don't block on initialization - start loading in background
        self._start_background_load()
        self._start_background_workload_load()
        # Start periodic MySoccerLeague reload scheduler
        self._start_periodic_reload_scheduler()

    def _start_background_load(self, force_reload=False):
        """Start loading data in a background thread without blocking

        Args:
            force_reload: If True, reload data even if it's already loaded
        """
        def load_in_background():
            try:
                self.logger.info("Starting background data load...")
                self.load_data(force_reload=force_reload)
                self.logger.info("Background data load completed")
            except Exception as e:
                self.logger.error(f"Error in background data load: {e}", exc_info=True)

        thread = threading.Thread(target=load_in_background, daemon=True)
        thread.start()

    def load_data(self, force_reload=False):
        """Load data, with thread-safe check to avoid duplicate loads

        Args:
            force_reload: If True, reload data even if it's already loaded
        """
        with self._load_lock:
            if (force_reload or self.all_match_data is None) and not self._loading:
                self._loading = True
                try:
                    self.logger.info("Loading match data from MySoccerLeague...")
                    self.all_match_data = getAllData(force_refresh=force_reload)
                    self.dates = list(self.all_match_data.keys())
                    self.loaded = True
                    self.logger.info(f"Successfully loaded data for {len(self.dates)} dates")
                except Exception as e:
                    self.logger.error(f"Failed to load data: {e}", exc_info=True)
                    self._loading = False
                    raise
                finally:
                    self._loading = False

    def is_data_loaded(self) -> bool:
        """Check if data has been loaded"""
        result = self.loaded and self.all_match_data is not None
        self.logger.debug(f"is_data_loaded: {result} (loaded={self.loaded}, data_is_none={self.all_match_data is None}, data_len={len(self.all_match_data) if self.all_match_data else 0})")
        return result

    def _start_background_workload_load(self, force_reload=False):
        """Start loading workload data in a background thread without blocking

        Args:
            force_reload: If True, reload data even if it's already loaded
        """
        def load_workload_in_background():
            try:
                self.logger.info("Starting background workload data load...")
                self.load_workload_data(force_reload=force_reload)
                self.logger.info("Background workload data load completed")
            except Exception as e:
                self.logger.error(f"Error in background workload data load: {e}", exc_info=True)

        thread = threading.Thread(target=load_workload_in_background, daemon=True)
        thread.start()

    def load_workload_data(self, force_reload=False):
        """Load workload data, with thread-safe check to avoid duplicate loads

        Args:
            force_reload: If True, reload data even if it's already loaded
        """
        with self._workload_lock:
            # Reload if forced or if data doesn't exist
            should_load = force_reload or not hasattr(self.ui, 'resultsFromRun') or self.ui.resultsFromRun is None
            if should_load and not self.workload_loading:
                self.workload_loading = True
                try:
                    self.logger.info("Loading workload data from run()...")
                    # Capture stdout from the run() function
                    stdout_capture = StringIO()
                    with redirect_stdout(stdout_capture):
                        self.ui.resultsFromRun = run()
                    self.workload_output = stdout_capture.getvalue()
                    if not self.workload_output:
                        self.workload_output = 'No workload data available'
                    self.workload_error = None  # Clear any previous errors
                    self.logger.info("Successfully loaded workload data")
                except Exception as e:
                    self.logger.error(f"Failed to load workload data: {e}", exc_info=True)
                    self.workload_error = str(e)
                    raise
                finally:
                    self.workload_loading = False

    def is_loading(self) -> bool:
        """Check if data is currently being loaded"""
        return self._loading

    # Interval between automatic full refetches from MySoccerLeague (and workload rebuild).
    RELOAD_INTERVAL_HOURS = 2

    def _schedule_periodic_reload(self):
        """Schedule the next full data reload after RELOAD_INTERVAL_HOURS."""
        seconds_until_reload = self.RELOAD_INTERVAL_HOURS * 3600

        self.logger.info(
            f"Scheduling next MySoccerLeague data reload in {self.RELOAD_INTERVAL_HOURS} hour(s) "
            f"({seconds_until_reload} seconds)"
        )

        def perform_periodic_reload():
            try:
                self.logger.info(
                    f"Starting scheduled data reload (every {self.RELOAD_INTERVAL_HOURS} hours)..."
                )
                self._start_background_load(force_reload=True)
                self._start_background_workload_load(force_reload=True)
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
