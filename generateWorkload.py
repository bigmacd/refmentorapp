import argparse
import datetime
from datetime import timedelta, datetime
from typing import Optional
from io import StringIO
from contextlib import redirect_stdout
import mechanicalsoup
import os
import logging

from database import RefereeDbCockroach
from refWebSites import MySoccerLeague
from googleSheets import getRefsFromGoogleSignupSheet

logger = logging.getLogger(__name__)

def getRealTimeCurrentRefAssignments(br: mechanicalsoup.stateful_browser.StatefulBrowser) -> dict:
    """
    Log into the MySoccerLeague website and pull all assignments for the weekend"""
    try:
        site = MySoccerLeague(br)
        site.setSpecificDate(datetime.now() - timedelta(days=1))
        assignments = site.getAssignments()
        return assignments
    except RuntimeError as e:
        logger.error(f"Failed to get current assignments: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error getting assignments: {e}")
        raise RuntimeError(f"Failed to retrieve assignments from MySoccerLeague: {e}") from e


def getPastAssignments(br: mechanicalsoup.stateful_browser.StatefulBrowser, d: datetime.date) -> dict:
    try:
        site = MySoccerLeague(br)
        site.setSpecificDate(d)
        return site.getAssignments()
    except RuntimeError as e:
        logger.error(f"Failed to get past assignments for {d}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error getting past assignments: {e}")
        raise RuntimeError(f"Failed to retrieve past assignments from MySoccerLeague: {e}") from e


def getAllRefereesFromSite(br: mechanicalsoup.stateful_browser.StatefulBrowser) -> list:
    try:
        site = MySoccerLeague(br)
        return site.getAllReferees()
    except RuntimeError as e:
        logger.error(f"Failed to get referees from site: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error getting referees: {e}")
        raise RuntimeError(f"Failed to retrieve referees from MySoccerLeague: {e}") from e


def getRefsAlreadyMentored() -> dict:
    """
    Pull the names of all referees already mentored this season
    """
    db = RefereeDbCockroach()
    return db.getMentoringSessions()


def adjustDbNewRefs(inRefs: list) -> list:
    # convert from list of tuples to list of strings
    # [( 'martin', 'cooley')] -> [('martin cooley')]
    retVal = []
    for ref in inRefs:
        retVal.append(f'{ref[0]} {ref[1]}')
    return retVal


def getRiskyRefs() -> list:
    retVal = []
    db = RefereeDbCockroach()
    refs = db.getRisky()
    for ref in refs:
        retVal.append(f'{ref[1]} {ref[0]}')
    return retVal


def generateWorkload(currentu: list, newRefs: list, mentored: list, risky: list) -> dict:

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

            # trying to reduce output a bit
            # if the crew is new and has already been mentored (but not flagged as needed follow-up), skip
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

            # looking to return this data as well as "print"
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
    Singleton class for generating workload data.
    Prevents multiple data gathering operations and caches the output.
    """
    _instance: Optional['WorkloadGenerator'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WorkloadGenerator, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._output: Optional[str] = None
            self._is_generating: bool = False
            self._db: Optional[RefereeDbCockroach] = None
            self._initialized = True

    def _generate_workload_data(self) -> str:
        """
        Internal method to generate workload data.
        Returns the output as a string.
        """
        # Capture stdout
        stdout_capture = StringIO()

        with redirect_stdout(stdout_capture):
            # adding this line to try to fix the deployment on streamlit.app
            db = RefereeDbCockroach()

            """
            Make sure database is up-to-date with VYS new referee spreadsheet
            """
            latestRefsFromSpreadsheet = getRefsFromGoogleSignupSheet()
            # returns list of tuples (lastname, firstname, year_certified)

            for ref in latestRefsFromSpreadsheet:
                if not db.refExists(ref[0], ref[1]):
                    print(f"{ref[1].capitalize()} {ref[0].capitalize()} not in database, adding")
                    db.addReferee(ref[0], ref[1], ref[2])

            """
            Retrieve referees from MSL
            """
            br = mechanicalsoup.StatefulBrowser(soup_config={'features': 'lxml'})
            br.addheaders = [('User-agent', 'Chrome')]

            allRefsFromMSL = getAllRefereesFromSite(br)
            # return list of tuples (firstname, lastname)

            # This was a one-time thing?
            # """
            # Update database with MSL referee list
            # """
            # for ref in allRefs:
            #     if not db.refExists(ref[1], ref[0]):
            #         print(f"missing ref: {ref[1]} {ref[0]}") #db.addReferee(ref[1], ref[0], 2000)

            """
            Verify new referees have the same first and last name in MSL.
            """
            newRefs = db.getNewReferees()
            # returns list of tuples (firstname, lastname)

            for ref in newRefs:
                if ref not in allRefsFromMSL:
                    print(f'Referee: {ref[0]} {ref[1]} not in MSL, check name spelling')

            # get this week's current assignments
            current = getRealTimeCurrentRefAssignments(br)
            db.addGameDetails(current)

            # get list of already mentored referees
            mentored = getRefsAlreadyMentored()

            # get the list of risky refs (those needing to be seen again)
            risky = getRiskyRefs()

            # first adjust the format of data in newRefs from list of tuples
            # (firstname, lastname) to list of strings "firstname lastname"
            newRefs = adjustDbNewRefs(newRefs)

            resultsFromRun = generateWorkload(current, newRefs, mentored, risky)

        return stdout_capture.getvalue(), resultsFromRun

    def get_workload_output(self, force_refresh: bool = False) -> str:
        """
        Get the workload output. Generates data if not cached or if forced.

        Args:
            force_refresh: If True, regenerate data even if cached

        Returns:
            str: The workload output as a string
        """
        if force_refresh or self._output is None:
            if self._is_generating:
                # If already generating, wait a bit and return cached or empty
                logger.warning("Workload generation already in progress, returning cached data")
                return self._output or "Workload generation in progress..."

            self._is_generating = True
            try:
                logger.info("Generating workload data...")
                self._output, self.resultsFromRun = self._generate_workload_data()
                logger.info("Workload data generated successfully")
            except Exception as e:
                logger.error(f"Error generating workload data: {e}", exc_info=True)
                raise
            finally:
                self._is_generating = False

        return self._output

    def clear_cache(self):
        """Clear the cached workload output"""
        self._output = None
        logger.info("Workload cache cleared")


# Convenience function for backward compatibility
def run() -> dict:
    """
    Generate workload data and print to stdout.
    Maintains backward compatibility with existing code.
    """
    generator = WorkloadGenerator()
    output = generator.get_workload_output()
    print(output, end='')
    return generator.resultsFromRun

def getEmails():
    try:
        br = mechanicalsoup.StatefulBrowser(soup_config={ 'features': 'lxml'})
        br.addheaders = [('User-agent', 'Chrome')]
        site = MySoccerLeague(br)
        _ = site.getAllReferees()
        return site.emails
    except RuntimeError as e:
        logger.error(f"Failed to get emails: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error getting emails: {e}")
        raise RuntimeError(f"Failed to retrieve emails from MySoccerLeague: {e}") from e



if __name__ == "__main__":
    bademails = [
        os.environ.get('badmentor1'),
        os.environ.get('badmentor2'),
        os.environ.get('badmentor3')
    ]
    parser = argparse.ArgumentParser()
    parser.add_argument('-e', action="store_true")
    args = parser.parse_args()
    if args.e is True:
        emails = getEmails()
        emails = sorted(emails)
        print(f"Retrieved {len(emails)} email addresses from MSL")
        for x, email in enumerate(emails):
            if email in bademails:
                continue
            print(email)
    else:
        _ = run()
