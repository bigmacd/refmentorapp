import os
import mechanicalsoup
import time
import logging

from database import RefereeDbCockroach
from refWebSites import MySoccerLeague

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        br = mechanicalsoup.StatefulBrowser(soup_config={ 'features': 'lxml'})
        br.addheaders = [('User-agent', 'Chrome')]
        site = MySoccerLeague(br)
        metrics = site.getReportForSeason('2025-04-01', '2025-12-31')
    except RuntimeError as e:
        logger.error(f"Failed to connect to MySoccerLeague: {e}")
        print(f"ERROR: {e}")
        exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"ERROR: Failed to retrieve metrics - {e}")
        exit(1)

    # metrics
    # {'gamesPlayed': 452, 'totalRefAssignments': 944, 'refsAssigned': 908, 'refsMissing': 36, 'missingCenters': 0, 'missingARs': 36}

    reportMetrics = RefereeDbCockroach().getMentoringSessionMetrics(2025, 'fall')

    # reportMetrics
    # {'mentors': 5, 'referees': 31, 'reports': 52}
    print("MSL Metrics:")
    print(f"  Games Played: {metrics['gamesPlayed']}")
    print(f"  Total Ref Assignments: {metrics['totalRefAssignments']}")
    print(f"  Refs Assigned: {metrics['refsAssigned']}")
    print(f"  Refs Missing: {metrics['refsMissing']}")
    print(f"    Missing Centers: {metrics['missingCenters']}")
    print(f"    Missing ARs: {metrics['missingARs']}")
    print("Mentoring Metrics:")
    print(f"  Mentors: {reportMetrics['mentors']}")
    print(f"  Referees: {reportMetrics['referees']}")
    print(f"  Reports: {reportMetrics['reports']}")
