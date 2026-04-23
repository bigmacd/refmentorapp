import mechanicalsoup
import logging
import os
from typing import Tuple, Optional
from datetime import datetime, timedelta

from refWebSites import MySoccerLeague

logger = logging.getLogger(__name__)


class UIData:
    """
    Singleton class for managing UI data from MySoccerLeague.
    Ensures data is only fetched once and reused across the application.
    Automatically refreshes data when it becomes stale (default: 2 hours).
    """
    _instance: Optional['UIData'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(UIData, cls).__new__(cls)
        return cls._instance

    def __init__(self, ttl_hours: int = 2):
        """
        Initialize the singleton instance.

        Args:
            ttl_hours: Time-to-live in hours before data is considered stale (default: 2)
        """
        if not self._initialized:
            self.allMatchData: Optional[dict] = None
            self.dates: Optional[list] = None
            self._last_fetch_time: Optional[datetime] = None
            self._ttl_seconds: int = ttl_hours * 3600
            self._process_id: int = os.getpid()
            self._initialized = True

            # Log process info and warn about multi-worker scenarios
            web_concurrency = os.environ.get('WEB_CONCURRENCY')
            if web_concurrency and int(web_concurrency) > 1:
                logger.warning(
                    f"WEB_CONCURRENCY={web_concurrency} detected. "
                    f"Each uvicorn worker process (PID: {self._process_id}) will have its own singleton instance. "
                    f"Consider using a shared cache (Redis/file-based) for multi-worker deployments."
                )
            else:
                logger.info(f"UIData singleton initialized in process PID: {self._process_id}")

    def _is_stale(self) -> bool:
        """Check if the cached data is stale based on TTL."""
        if self._last_fetch_time is None:
            return True
        elapsed = (datetime.now() - self._last_fetch_time).total_seconds()
        return elapsed >= self._ttl_seconds

    def _fetch_data(self) -> None:
        """Internal method to fetch data from MySoccerLeague."""
        try:
            logger.info("[FETCH_DATA] Starting data fetch from MySoccerLeague")
            logger.info("[FETCH_DATA] Step 1: Creating StatefulBrowser instance")
            br = mechanicalsoup.StatefulBrowser(soup_config={'features': 'lxml'})
            br.addheaders = [('User-agent', 'Chrome')]
            logger.info("[FETCH_DATA] Step 1: Browser instance created successfully")

            logger.info("[FETCH_DATA] Step 2: Initializing MySoccerLeague (this includes login)")
            try:
                site = MySoccerLeague(br)
                logger.info("[FETCH_DATA] Step 2: MySoccerLeague initialized successfully")
            except Exception as e:
                logger.error(f"[FETCH_DATA] Step 2 FAILED: Error initializing MySoccerLeague: {e}", exc_info=True)
                raise

            logger.info("[FETCH_DATA] Step 3: Calling getAllDatesForSeason()")
            try:
                self.dates = site.getAllDatesForSeason()
                logger.info(f"[FETCH_DATA] Step 3: Successfully retrieved {len(self.dates) if self.dates else 0} dates")
            except Exception as e:
                logger.error(f"[FETCH_DATA] Step 3 FAILED: Error in getAllDatesForSeason(): {e}", exc_info=True)
                raise

            logger.info("[FETCH_DATA] Step 4: Starting to fetch matches for each date")
            self.allMatchData = {}
            total_dates = len(self.dates) if self.dates else 0
            for idx, date_str in enumerate(self.dates or [], 1):
                logger.info(f"[FETCH_DATA] Step 4.{idx}/{total_dates}: Getting matches for date: {date_str}")
                try:
                    start_time = datetime.now()
                    self.allMatchData[date_str] = site.getMatches(date_str)
                    elapsed = (datetime.now() - start_time).total_seconds()
                    num_matches = len(self.allMatchData[date_str]) if self.allMatchData[date_str] else 0
                    logger.info(f"[FETCH_DATA] Step 4.{idx}/{total_dates}: Successfully got {num_matches} matches for {date_str} (took {elapsed:.2f}s)")
                except Exception as e:
                    logger.error(f"[FETCH_DATA] Step 4.{idx}/{total_dates} FAILED: Error getting matches for {date_str}: {e}", exc_info=True)
                    # Continue with other dates but log the error
                    self.allMatchData[date_str] = {}

            self._last_fetch_time = datetime.now()
            logger.info(f"[FETCH_DATA] COMPLETE: Successfully fetched match data at {self._last_fetch_time}")

        except RuntimeError as e:
            logger.error(f"[FETCH_DATA] FAILED: RuntimeError during data fetch: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"[FETCH_DATA] FAILED: Unexpected error during data fetch: {e}", exc_info=True)
            raise RuntimeError(f"Failed to retrieve match data from MySoccerLeague: {e}") from e

    def getAllData(self, force_refresh: bool = False) -> dict:
        """
        Get all match data. Initializes or refreshes data if stale or forced.

        Args:
            force_refresh: If True, bypass cache and fetch fresh data

        Returns:
            dict: Dictionary mapping dates to match data
        """
        if force_refresh or self.allMatchData is None or self._is_stale():
            self._fetch_data()
        return self.allMatchData

    def refresh(self) -> dict:
        """
        Explicitly refresh the data, bypassing the cache.
        Useful for scheduled refreshes or manual updates.

        Returns:
            dict: Freshly fetched dictionary mapping dates to match data
        """
        return self.getAllData(force_refresh=True)

    def get_last_fetch_time(self) -> Optional[datetime]:
        """
        Get the timestamp of when data was last fetched.

        Returns:
            datetime or None if data has never been fetched
        """
        return self._last_fetch_time

    def get_process_info(self) -> dict:
        """
        Get diagnostic information about the process running this singleton.
        Useful for debugging multi-worker scenarios.

        Returns:
            dict: Process information including PID and worker count hints
        """
        web_concurrency = os.environ.get('WEB_CONCURRENCY')
        return {
            'process_id': self._process_id,
            'web_concurrency_env': web_concurrency,
            'estimated_workers': int(web_concurrency) if web_concurrency else 1,
            'note': 'Each uvicorn worker is a separate process with its own singleton instance'
        }


# Convenience function for backward compatibility
def getAllData(force_refresh: bool = False) -> dict:
    """
    Convenience function that returns data from the singleton instance.
    Maintains backward compatibility with existing code.

    Args:
        force_refresh: If True, bypass cache and fetch fresh data
    """
    return UIData().getAllData(force_refresh=force_refresh)
