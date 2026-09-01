import os
import logging
from typing import Optional
from io import StringIO
from contextlib import redirect_stdout

from database import RefereeDbCockroach
from assignment_providers import (
    get_workload_config,
    get_assignment_provider,
    sync_new_referees,
)

logger = logging.getLogger(__name__)


def getRefsAlreadyMentored(organization_id: int = None) -> dict:
    """Pull the names of all referees already mentored this season."""
    db = RefereeDbCockroach()
    return db.getMentoringSessions(organization_id)


def adjustDbNewRefs(inRefs: list) -> list:
    retVal = []
    for ref in inRefs:
        retVal.append(f'{ref[0]} {ref[1]}')
    return retVal


def getRiskyRefs(organization_id: int = None) -> list:
    retVal = []
    db = RefereeDbCockroach()
    refs = db.getRisky(organization_id)
    for ref in refs:
        retVal.append(f'{ref[1]} {ref[0]}')
    return retVal


def generateWorkload(currentu: list, newRefs: list, mentored: list, risky: list) -> dict:

    minimizeOutput = os.environ.get('MINIMIZE_OUTPUT', 'false').lower() == 'true'

    current = {}
    for c in sorted(currentu):
        current[c] = currentu[c]

    retVal = {}

    for field, details in current.items():
        fieldsOnce = False
        for game in details:

            center = details[game]['Center'].lower()
            ar1 = details[game]['AR1'].lower()
            ar2 = details[game]['AR2'].lower()

            if center not in newRefs and ar1 not in newRefs and ar2 not in newRefs:
                continue

            cmarker = ''
            if center in mentored and 'Center' in mentored[center]:
                cmarker = '**'
            a1marker = ''
            if ar1 in mentored and ('AR1' in mentored[ar1] or 'AR2' in mentored[ar1]):
                a1marker = '**'
            a2marker = ''
            if ar2 in mentored and ('AR2' in mentored[ar2] or 'AR1' in mentored[ar2]):
                a2marker = '**'

            crisky = '##' if center in risky else ''
            a1risky = '##' if ar1 in risky else ''
            a2risky = '##' if ar2 in risky else ''

            if not os.environ.get('showmentored', False):
                if center in newRefs:
                    if cmarker == '**' and crisky == '':
                        newRefs.remove(center)
                if ar1 in newRefs:
                    if a1marker == '**' and a1risky == '':
                        newRefs.remove(ar1)
                if ar2 in newRefs:
                    if a2marker == '**' and a2risky == '':
                        newRefs.remove(ar2)
                if center not in newRefs and ar1 not in newRefs and ar2 not in newRefs:
                    continue

            if not fieldsOnce:
                print("")
                print(f'Field: {field}')
                fieldsOnce = True

            date = details[game]['date']
            gameTime = details[game]['gameTime']
            age = details[game]['age']
            level = details[game]['level']

            if field not in retVal:
                retVal[field] = {}

            if game not in retVal[field]:
                retVal[field][game] = {}

            retVal[field][game]['center'] = center
            retVal[field][game]['ar1'] = ar1
            retVal[field][game]['ar2'] = ar2
            retVal[field][game]['date'] = date
            retVal[field][game]['gameTime'] = gameTime
            retVal[field][game]['age'] = age
            retVal[field][game]['level'] = level
            retVal[field][game]['cmarker'] = cmarker
            retVal[field][game]['a1marker'] = a1marker
            retVal[field][game]['a2marker'] = a2marker
            retVal[field][game]['crisky'] = crisky
            retVal[field][game]['a1risky'] = a1risky
            retVal[field][game]['a2risky'] = a2risky

            print(f'\tID: {game}, Date: {date}, Time: {gameTime}, Age: {age}, Level: {level}')

            if center in newRefs:
                print(f'\t\tNew Ref at Center: {center.title()}{cmarker} {crisky}')

            if ar1 in newRefs:
                print(f'\t\tNew Ref at AR1: {ar1.title()}{a1marker} {a1risky}')

            if ar2 in newRefs:
                print(f'\t\tNew Ref at AR2: {ar2.title()}{a2marker} {a2risky}')

    print("")
    print("** Referee has already had a mentor")
    print("## Referee has been flagged as needing additional help")
    print("")

    return retVal


class WorkloadGenerator:
    """
    Singleton class for generating workload data per organization.
    Prevents duplicate scrapes and caches output keyed by organization_id.
    """

    _instance: Optional['WorkloadGenerator'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WorkloadGenerator, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._cache: dict[int, tuple[str, dict]] = {}
            self._generating: set[int] = set()
            self._initialized = True

    def _generate_workload_data(self, organization_id: int) -> tuple[str, dict]:
        stdout_capture = StringIO()

        with redirect_stdout(stdout_capture):
            db = RefereeDbCockroach()
            org = db.getOrganizationById(organization_id)
            if not org:
                raise ValueError(f'Organization id {organization_id} not found')

            config = get_workload_config(org)
            print(
                f"Generating workload for organization: {org['name']} "
                f"(id={organization_id}, provider={config.provider})"
            )

            provider = get_assignment_provider(config)
            if provider is None:
                print(
                    f"No assignment provider is configured for {org['name']}. "
                    "Workload generation is not available for this organization yet."
                )
                return stdout_capture.getvalue(), {}

            sync_new_referees(db, config)

            all_refs_from_site = provider.get_all_referees()

            new_refs = db.getNewReferees(organization_id)
            for ref in new_refs:
                if ref not in all_refs_from_site:
                    print(f'Referee: {ref[0]} {ref[1]} not on assignment platform, check name spelling')

            current = provider.get_current_assignments()
            db.addGameDetails(current, organization_id)

            mentored = getRefsAlreadyMentored(organization_id)
            risky = getRiskyRefs(organization_id)
            new_refs = adjustDbNewRefs(new_refs)

            results_from_run = generateWorkload(current, new_refs, mentored, risky)

        return stdout_capture.getvalue(), results_from_run

    def get_workload_output(self, organization_id: int, force_refresh: bool = False) -> str:
        if force_refresh or organization_id not in self._cache:
            if organization_id in self._generating:
                logger.warning(
                    'Workload generation already in progress for org %s, returning cached data',
                    organization_id,
                )
                cached = self._cache.get(organization_id)
                return cached[0] if cached else 'Workload generation in progress...'

            self._generating.add(organization_id)
            try:
                logger.info('Generating workload data for organization_id=%s', organization_id)
                self._cache[organization_id] = self._generate_workload_data(organization_id)
                logger.info('Workload data generated successfully for organization_id=%s', organization_id)
            except Exception as e:
                logger.error('Error generating workload data: %s', e, exc_info=True)
                raise
            finally:
                self._generating.discard(organization_id)

        return self._cache[organization_id][0]

    def get_workload_results(self, organization_id: int, force_refresh: bool = False) -> dict:
        self.get_workload_output(organization_id, force_refresh=force_refresh)
        return self._cache.get(organization_id, ('', {}))[1]

    def clear_cache(self, organization_id: int = None):
        if organization_id is None:
            self._cache.clear()
            logger.info('Workload cache cleared for all organizations')
        else:
            self._cache.pop(organization_id, None)
            logger.info('Workload cache cleared for organization_id=%s', organization_id)


def resolve_workload_organization_id(db: RefereeDbCockroach, organization_id: int = None) -> int:
    if organization_id is not None:
        return organization_id
    return db.getDefaultOrganizationId()


def run(organization_id: int = None) -> dict:
    """Generate workload for an organization and return structured results."""
    db = RefereeDbCockroach()
    org_id = resolve_workload_organization_id(db, organization_id)
    generator = WorkloadGenerator()
    output = generator.get_workload_output(org_id)
    print(output, end='')
    return generator.get_workload_results(org_id)


def getEmails():
    import mechanicalsoup
    from refWebSites import MySoccerLeague

    try:
        br = mechanicalsoup.StatefulBrowser(soup_config={'features': 'lxml'})
        br.addheaders = [('User-agent', 'Chrome')]
        site = MySoccerLeague(br)
        _ = site.getAllReferees()
        return site.emails
    except RuntimeError as e:
        logger.error(f'Failed to get emails: {e}')
        raise
    except Exception as e:
        logger.error(f'Unexpected error getting emails: {e}')
        raise RuntimeError(f'Failed to retrieve emails from MySoccerLeague: {e}') from e


if __name__ == '__main__':
    run()
