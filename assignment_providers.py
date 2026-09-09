"""
Assignment source adapters for multi-tenant workload and UI match data.

Each organization can use a different scheduling platform (MySoccerLeague, Assignr,
Arbiter, etc.). Providers return two normalized shapes:

1) Workload assignments (generateWorkload):
    {
        venue_name: {
            game_id: {
                'Center': str, 'AR1': str, 'AR2': str,
                'date': str,       # m/d/YYYY
                'gameTime': str, 'age': str, 'level': str,
            },
            ...
        },
        ...
    }

2) Season match schedule (UI report / game selection):
    {
        'Saturday, March 1, 2026': {
            venue_name: [
                {
                    'Center': str, 'AR1': str, 'AR2': str,
                    'Time': str, 'Level': str, 'Age': str, 'GameID': str,
                },
                ...
            ],
            ...
        },
        ...
    }
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Protocol

import mechanicalsoup

from googleSheets import getRefsFromGoogleSignupSheet
from refWebSites import MySoccerLeague

logger = logging.getLogger(__name__)

# Provider identifiers (extend as new platforms are added).
PROVIDER_MYSOCCERLEAGUE = 'mysoccerleague'
PROVIDER_NONE = 'none'

NEW_REF_SOURCE_VYS_GOOGLE_SHEET = 'vys_google_sheet'
NEW_REF_SOURCE_DATABASE = 'database'


@dataclass(frozen=True)
class OrganizationWorkloadConfig:
    organization_id: int
    slug: str
    name: str
    provider: str
    new_ref_source: str


class AssignmentProvider(Protocol):
    """Fetches referee assignments, roster, and season schedule from an external platform."""

    def get_current_assignments(self) -> dict:
        ...

    def get_all_referees(self) -> list:
        """Return list of (firstname, lastname) tuples."""
        ...

    def get_season_match_schedule(self) -> dict:
        """Return date -> venue -> list of games for the UI."""
        ...


class MySoccerLeagueProvider:
    """VYS and other orgs on mysoccerleague.com."""

    def __init__(self, browser: Optional[mechanicalsoup.StatefulBrowser] = None):
        self._browser = browser or self._create_browser()
        self._site: Optional[MySoccerLeague] = None

    @staticmethod
    def _create_browser() -> mechanicalsoup.StatefulBrowser:
        br = mechanicalsoup.StatefulBrowser(soup_config={'features': 'lxml'})
        br.addheaders = [('User-agent', 'Chrome')]
        return br

    def _site_instance(self) -> MySoccerLeague:
        if self._site is None:
            self._site = MySoccerLeague(self._browser)
        return self._site

    def get_current_assignments(self) -> dict:
        try:
            site = self._site_instance()
            site.setSpecificDate(datetime.now() - timedelta(days=1))
            return site.getAssignments()
        except RuntimeError:
            raise
        except Exception as ex:
            logger.error('Unexpected error getting MSL assignments: %s', ex)
            raise RuntimeError(f'Failed to retrieve assignments from MySoccerLeague: {ex}') from ex

    def get_all_referees(self) -> list:
        try:
            return self._site_instance().getAllReferees()
        except RuntimeError:
            raise
        except Exception as ex:
            logger.error('Unexpected error getting MSL referees: %s', ex)
            raise RuntimeError(f'Failed to retrieve referees from MySoccerLeague: {ex}') from ex

    def get_season_match_schedule(self) -> dict:
        """Fetch all season dates and matches for the UI (report / game selection)."""
        try:
            site = self._site_instance()
            logger.info('[MSL] Fetching season dates')
            dates = site.getAllDatesForSeason()
            logger.info('[MSL] Retrieved %s season dates', len(dates) if dates else 0)

            all_match_data = {}
            total = len(dates) if dates else 0
            for idx, date_str in enumerate(dates or [], 1):
                logger.info('[MSL] Fetching matches %s/%s for %s', idx, total, date_str)
                try:
                    start = datetime.now()
                    all_match_data[date_str] = site.getMatches(date_str)
                    elapsed = (datetime.now() - start).total_seconds()
                    n = len(all_match_data[date_str]) if all_match_data[date_str] else 0
                    logger.info('[MSL] Got %s venues for %s (%.2fs)', n, date_str, elapsed)
                except Exception as e:
                    logger.error('[MSL] Failed matches for %s: %s', date_str, e, exc_info=True)
                    all_match_data[date_str] = {}
            return all_match_data
        except RuntimeError:
            raise
        except Exception as ex:
            logger.error('Unexpected error getting MSL season schedule: %s', ex)
            raise RuntimeError(f'Failed to retrieve match schedule from MySoccerLeague: {ex}') from ex


def _is_vys_org(org: dict) -> bool:
    slug = (org.get('slug') or '').lower()
    name = (org.get('name') or '').lower()
    return slug == 'vys' or name == 'vys' or 'vys' in name.split()


def get_workload_config(org: dict) -> OrganizationWorkloadConfig:
    """Map an organization record to its workload/assignment configuration."""
    org_id = org['id']
    slug = org.get('slug') or ''
    name = org.get('name') or ''

    if _is_vys_org(org):
        return OrganizationWorkloadConfig(
            organization_id=org_id,
            slug=slug,
            name=name,
            provider=PROVIDER_MYSOCCERLEAGUE,
            new_ref_source=NEW_REF_SOURCE_VYS_GOOGLE_SHEET,
        )

    return OrganizationWorkloadConfig(
        organization_id=org_id,
        slug=slug,
        name=name,
        provider=PROVIDER_NONE,
        new_ref_source=NEW_REF_SOURCE_DATABASE,
    )


def get_assignment_provider(config: OrganizationWorkloadConfig) -> Optional[AssignmentProvider]:
    if config.provider == PROVIDER_MYSOCCERLEAGUE:
        return MySoccerLeagueProvider()
    return None


def sync_new_referees(db, config: OrganizationWorkloadConfig) -> None:
    """Import new-referee rows for this org from configured sources into the DB."""
    if config.new_ref_source != NEW_REF_SOURCE_VYS_GOOGLE_SHEET:
        return

    latest_refs = getRefsFromGoogleSignupSheet()
    for ref in latest_refs:
        if not db.refExists(ref[0], ref[1], config.organization_id):
            print(f"{ref[1].capitalize()} {ref[0].capitalize()} not in database, adding")
            db.addReferee(ref[0], ref[1], ref[2], config.organization_id)
