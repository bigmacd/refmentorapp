import os
import certifi
import datetime
import re
import time
import logging

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log

logger = logging.getLogger(__name__)

class RefereeWebSite(object):

    def __init__(self, br):
        self._browser = br
        self._baseUrl = None
        self._loginPage = None
        self._loginFormInput = None

    def baseUrl(self):
        return self._baseUrl

    def loginPage(self):
        return self._loginPage

    def loginFormInput(self):
        return self._loginFormInput

    def getLocationDetails(self, assignmentData):
        return None


class MySoccerLeague(RefereeWebSite):

    def __init__(self, br):
        super(MySoccerLeague, self).__init__(br)
        self._browser.session.verify = self._getCertChain()
        self._baseUrl = self._loginPage = "https://mysoccerleague.com/YSLmobile.jsp"
        self._loginFormInput = { 'userName': os.environ['mslUsername'],
                                'password': os.environ['mslPassword'] }

        self._login()

        logger.info("[MySoccerLeague.__init__] Calculating future dates")
        self._getFutureDates(datetime.date.today())
        self.emails = []
        logger.info("[MySoccerLeague.__init__] Initialization complete")


    def _getCertChain(self):
        certifi_bundle = certifi.where()
        with open(certifi_bundle, 'rb') as f:
            default_certs = f.read()

        with open('mysoccerleague.com.chained.crt', 'rb') as f:
            custom_certs = f.read()

        full_bundle = default_certs + b'\n' + custom_certs

        with open('full-ca-bundle.pem', 'wb') as f:
            f.write(full_bundle)

        return 'full-ca-bundle.pem'


    @retry(
        stop=stop_after_attempt(20),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type(Exception),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _login(self):
        # The site we will navigate into, handling it's session
        logger.info(f"[_login] Step 1: Opening login page: {self._baseUrl}")
        try:
            login_page = self._browser.open(self._baseUrl)
            logger.info(f"[_login] Step 1: Successfully opened login page (status: {login_page.status_code if hasattr(login_page, 'status_code') else 'N/A'})")
        except Exception as e:
            logger.error(f"[_login] Step 1 FAILED: Error opening login page: {e}", exc_info=True)
            raise

        logger.info("[_login] Step 2: Selecting login form")
        try:
            self._browser.select_form('form')
            logger.info("[_login] Step 2: Form selected successfully")
        except Exception as e:
            logger.error(f"[_login] Step 2 FAILED: Error selecting form: {e}", exc_info=True)
            raise

        logger.info("[_login] Step 3: Filling in credentials")
        try:
            self._browser['userName'] = self._loginFormInput['userName']
            self._browser['password'] = self._loginFormInput['password']
            logger.info("[_login] Step 3: Credentials filled in")
        except Exception as e:
            logger.error(f"[_login] Step 3 FAILED: Error filling credentials: {e}", exc_info=True)
            raise

        logger.info("[_login] Step 4: Submitting login form")
        try:
            self._loginResponse = self._browser.submit_selected()
            logger.info(f"[_login] Step 4: Form submitted (status: {self._loginResponse.status_code if hasattr(self._loginResponse, 'status_code') else 'N/A'})")
        except Exception as e:
            logger.error(f"[_login] Step 4 FAILED: Error submitting form: {e}", exc_info=True)
            raise

        logger.info("[_login] Step 5: Extracting login key from response")
        try:
            links = self._loginResponse.soup.find_all('a')
            logger.debug(f"[_login] Found {len(links)} links in response")
            if len(links) < 14:
                raise IndexError(f"Expected at least 14 links, found {len(links)}")
            self._loginKey = links[13]['href'].split('?')[1].split('&')[0].split('=')[1]
            logger.info(f"[_login] Step 5: Login key extracted successfully: {self._loginKey[:10]}...")
        except Exception as e:
            logger.error(f"[_login] Step 5 FAILED: Error extracting login key: {e}", exc_info=True)
            raise


    def _getFutureDates(self, d: datetime.date):
        """
        Get the dates for the url for Friday, Saturday, and Sunday.
        """
        while d.weekday() != 4:  # Friday
            d += datetime.timedelta(1)

        self._friday = d.strftime('%m/%d/%Y')
        d += datetime.timedelta(1)
        self._saturday = d.strftime('%m/%d/%Y')
        d += datetime.timedelta(1)
        self._sunday = d.strftime('%m/%d/%Y')


    def setSpecificDate(self, d: datetime.date) -> None:
        # Allows us to go back in time and produce the mentor workload report
        self._getFutureDates(d)


    def _parseAssignments(self, assignments: list, results: dict, date: str) -> None:
        for a in assignments:
            elements = a.find_all('td')
            ref1 = elements[9].text
            ref2 = elements[10].text
            ref3 = elements[11].text
            field = elements[1].text
            level = elements[3].text
            gameTime = elements[2].text
            age = elements[4].text
            gameId = elements[0].text

            if ref1 in (' ', '\xa0', 'Not Used\n'):
                ref1 = 'None'
            if ref2 in (' ', '\xa0', 'Not Used\n'):
                ref2 = 'None'
            if ref3 in (' ', '\xa0', 'Not Used\n'):
                ref3 = 'None'
            if field not in results:
                results[field] = {}
            results[field][gameId] = {
                'Center': ref1,
                'AR1': ref2,
                'AR2': ref3,
                'date': date,
                'gameTime': gameTime,
                'age': age,
                'level': level
            }
            # if ref1 not in (' ', '\xa0', 'Not Used\n'):
            #     if ref1 not in results:
            #         results[ref1] = {}
            #     results[ref1][gameId] = { 'field': field, 'date': date, 'gameTime': gameTime, 'age': age, 'position': 'Center' }
            # if ref2 not in (' ', '\xa0', 'Not Used\n'):
            #     if ref2 not in results:
            #         results[ref2] = {}
            #     results[ref2][gameId] = { 'field': field, 'date': date, 'gameTime': gameTime, 'age': age, 'position': 'AR1' }
            # if ref3 not in (' ', '\xa0', 'Not Used\n'):
            #     if ref3 not in results:
            #         results[ref3] = {}
            #     results[ref3][gameId] = { 'field': field, 'date': date, 'gameTime': gameTime, 'age': age, 'position': 'AR2' }


    def getAllDatesForSeason(self) -> list:
        url = "https://mysoccerleague.com/ViewRefAssignments.jsp?YSLkey={0}&seasonId=0&leagueId=91&dateMode=allDates".format(self._loginKey)
        logger.info(f"[getAllDatesForSeason] Opening URL: {url}")

        try:
            start_time = time.time()
            page = self._browser.open(url)
            elapsed = time.time() - start_time
            logger.info(f"[getAllDatesForSeason] URL opened successfully in {elapsed:.2f}s (status: {page.status_code if hasattr(page, 'status_code') else 'N/A'})")
        except Exception as e:
            logger.error(f"[getAllDatesForSeason] FAILED to open URL after waiting: {e}", exc_info=True)
            raise

        logger.info("[getAllDatesForSeason] Parsing response HTML")
        try:
            box = page.soup.find("td", { "class" : 'tblborderforms', 'align' : 'center' })
            if box is None:
                raise ValueError("Could not find date box in HTML response")
            dates = box.find_all("a")
            logger.info(f"[getAllDatesForSeason] Found {len(dates)} date links")
        except Exception as e:
            logger.error(f"[getAllDatesForSeason] FAILED to parse dates from HTML: {e}", exc_info=True)
            raise

        results = []
        # skip the first two entries
        for i in range(2, len(dates)):
            results.append(dates[i].text.strip())
        logger.info(f"[getAllDatesForSeason] Returning {len(results)} dates")
        return results


    def getMatches(self, dateInfo: str) -> dict:

        def getGameId(text: str) -> str:
            # Some MSL gameId fields look like "798732FORFEIT" (digits + extra text).
            # Using word-boundaries ("\b...\b") fails when the digits are immediately
            # followed by letters. Instead, just extract the first 6-digit sequence.
            if text is None:
                return ""
            match = re.search(r"\d{6}", str(text))
            if not match:
                return ""
            return match.group(0)


        url_template = 'https://www.mysoccerleague.com/ViewRefAssignments.jsp?YSLkey={0}&seasonId=0&leagueId=91&dateMode=allDates&date={1}'

        logger.info(f"[getMatches] Processing date: {dateInfo}")
        # convert from 'Day, Month Date, Year' i.e. (Saturday, September 24, 2022)
        # to m/d/year
        try:
            parts = dateInfo.split(',')
            year = parts[2]
            month, day = parts[1].lstrip().split(' ')

            # fix month
            dateObject = datetime.datetime.strptime(f'{month} {day} {year}', '%B %d %Y')
            convertedDate = f'{dateObject.month}/{dateObject.day}/{dateObject.year}'
            logger.debug(f"[getMatches] Converted date: {convertedDate}")
        except Exception as e:
            logger.error(f"[getMatches] FAILED to parse date {dateInfo}: {e}", exc_info=True)
            raise

        url = url_template.format(self._loginKey, convertedDate)
        logger.info(f"[getMatches] Opening URL: {url}")

        try:
            start_time = time.time()
            page = self._browser.open(url)
            elapsed = time.time() - start_time
            logger.info(f"[getMatches] URL opened successfully in {elapsed:.2f}s for {dateInfo} (status: {page.status_code if hasattr(page, 'status_code') else 'N/A'})")
        except Exception as e:
            logger.error(f"[getMatches] FAILED to open URL for {dateInfo} after waiting: {e}", exc_info=True)
            raise

        entries1 = page.soup.find_all("tr", { "class" : 'trstyle1' })
        entries2 = page.soup.find_all("tr", { "class" : 'trstyle2' })

        entries = entries1 + entries2

        '''
        Each entry is like this:  Organize by venue.

        <tr class="trstyle1">
        <td align="center">748590<br/><font color="green"></font></td>
        <td><a href="javascript:directWindow('Ken Lawrence #2','No directions available','No comments')">Ken Lawrence #2</a></td>
        <td>8:00 AM</td>
        <td>U12G House</td>
        <td>U-12</td>
        <td>Girls</td>
        <td>Rec</td>
        <td>Bill Chappell</td>
        <td>Katie Cohen</td>
        <td align="left">Danika Pfleghardt</td>
        <td align="left">Mitra Tafreshi</td>
        <td align="left">Kate Curby</td>
        </tr>'''

        retVal = {}

        for entry in entries:
            elements = entry.find_all('td')
            ref1 = elements[9].text.strip('\n').strip('\r')
            ref2 = elements[10].text.strip('\n').strip('\r')
            ref3 = elements[11].text.strip('\n').strip('\r')

            # clean up the ref data as MSL can make a mess of it
            if ref1 in (' ', '\xa0', 'Not Used\n'):
                ref1 = 'None'
            if ref2 in (' ', '\xa0', 'Not Used\n'):
                ref2 = 'None'
            if ref3 in (' ', '\xa0', 'Not Used\n'):
                ref3 = 'None'

            field = elements[1].text.strip().strip('\n').strip('\r')
            level = elements[3].text
            gameTime = elements[2].text
            age = elements[4].text
            gameId = elements[0].text

            # Dianne sometimes puts extra text in the gameId field, so we need to extract the number
            gameId = getGameId(gameId)


            if field not in retVal:
                retVal[field] = []

            data = {
                'Center': ref1.replace('[VYS]', ''),
                'AR1': ref2.replace('[VYS]', ''),
                'AR2': ref3.replace('[VYS]', ''),
                'Time': gameTime,
                'Level' :level,
                'Age': age,
                'GameID' :gameId
            }
            retVal[field].append(data)

        return retVal


    def getAssignments(self):
        for _ in range(3):
            try:
                results = {}

                # MSL url for current assignments
                # need to extract the key fom the login_result first
                url = "https://www.mysoccerleague.com/ViewRefAssignments.jsp?YSLkey={0}&seasonId=0&leagueId=91&dateMode=futureDates&date={1}&startDate=9/8/21&endDate=11/19/21".format(self._loginKey, self._friday)
                assignments_page = self._browser.open(url)
                rowtype1 = assignments_page.soup.find_all("tr", { "class" : 'trstyle1'})
                rowtype2 = assignments_page.soup.find_all("tr", { "class" : 'trstyle2'})
                assignments = rowtype1 + rowtype2

                self._parseAssignments(assignments, results, self._friday)

                url = "https://www.mysoccerleague.com/ViewRefAssignments.jsp?YSLkey={0}&seasonId=0&leagueId=91&dateMode=futureDates&date={1}&startDate=9/8/21&endDate=11/19/21".format(self._loginKey, self._saturday)
                assignments_page = self._browser.open(url)
                rowtype1 = assignments_page.soup.find_all("tr", { "class" : 'trstyle1'})
                rowtype2 = assignments_page.soup.find_all("tr", { "class" : 'trstyle2'})
                assignments = rowtype1 + rowtype2

                self._parseAssignments(assignments, results, self._saturday)

                url = "https://www.mysoccerleague.com/ViewRefAssignments.jsp?YSLkey={0}&seasonId=0&leagueId=91&dateMode=futureDates&date={1}&startDate=9/8/21&endDate=11/19/21".format(self._loginKey, self._sunday)
                assignments_page = self._browser.open(url)
                rowtype1 = assignments_page.soup.find_all("tr", { "class" : 'trstyle1'})
                rowtype2 = assignments_page.soup.find_all("tr", { "class" : 'trstyle2'})
                assignments = rowtype1 + rowtype2

                self._parseAssignments(assignments, results, self._sunday)

            except Exception:
                time.sleep(3)
            else:
                break

        return results

    def getAllReferees(self) -> list:
        emails = None
        retVal = None
        for _ in range(3):
            try:
                url = 'https://www.mysoccerleague.com/AddRef.jsp?YSLkey={0}&actionName=Referees&showAll=true'.format(self._loginKey)
                page = self._browser.open(url)

                entries1 = page.soup.find_all("tr", { "class" : 'trstyle1' })
                entries2 = page.soup.find_all("tr", { "class" : 'trstyle2' })

                entries = entries1 + entries2

                retVal = []
                emails = []
                for entry in entries:
                    elements = entry.find_all('td')
                    refereeFullName = elements[4].text
                    emails.append(elements[7].text)
                    try:
                        firstName, lastName = refereeFullName.split(' ')
                    except ValueError:
                        f, l, x = refereeFullName.split(' ')
                        # handle weirdness in MSL (three part names, extra spaces, etc.)

                        last = None

                        if f == 'Russell':
                            if x == 'Bower':
                                last = x
                        elif f == 'Alexandre':
                            if l == 'de':
                                last = l + ' ' + x
                        elif f == 'Will':
                            if l == 'Covey' and x == 'III':
                                last = l + ' ' + x
                        elif f == 'Gabriella':
                            if l == '(Brie)':
                                last = l + ' ' + x
                        elif f == 'Sophie':
                            if x == 'Hinton':
                                last = x
                        elif f == 'Vivienne':
                            if x == 'Huang':
                                last = x
                        elif f == 'Andrew':
                            if x == 'Teale':
                                last = x
                        elif f == 'Gabi':
                            if x == 'Konde':
                                last = x
                        elif f == 'James':
                            if x == 'Horn':
                                last = f"{l} {x}"
                        elif f == 'Joseph':
                            if x == 'Sandoval':
                                last = f"{l} {x}"
                            elif x == 'Howe':
                                last = f"{l} {x}"
                        elif f == 'Mohamed':
                            if l == 'Nour':
                                last = f"{l} {x}"
                        elif f == 'Jack':
                            if x == 'Raaphorst':
                                last = f"{l} {x}"
                        elif f == 'Laith':
                            if x == 'Habri':
                                last = f"{l} {x}"
                        elif f == 'William':
                            if l == 'Covey,':
                                if x == 'Jr':
                                    l = l.strip(',')
                                    last = f"{l} {x}"
                        elif f == 'Sofia':
                            if l == 'Velasquez':
                                last = f"{l} {x}"
                        elif f == 'Martiel':
                            if l == 'Ruiz':
                                last = f"{l} {x}"
                        elif f == 'Michael':
                            if l == 'Aguilera':
                                if x == 'Jr.':
                                    last = f"{l} {x}"
                        elif f == 'Mary':
                            if l == 'Kate':
                                f = f"{f} {l}"
                                last = x
                        elif f == "Tyler":
                            if x == "Pechenik":
                                last = x
                        elif f == 'Rayan':
                            if x == 'Hababi':
                                last = f"{l} {x}"
                        else:
                            print(f'Error parsing: {refereeFullName}: f: {f} l: {l} x:{x}')

                        if last is None:
                            print(f'Error parsing: {refereeFullName}: f: {f} l: {l}, x:{x}')
                        else:
                            retVal.append((f.lower().strip(), last.lower().strip()))


                    retVal.append((firstName.lower().strip(), lastName.lower().strip()))

            except Exception:
                time.sleep(3)
            else:
                break
        self.emails = emails
        return retVal


    def getReportData(self, startDate: str, endDate: str):
        url = f'https://mysoccerleague.com/GamesReportChoice.jsp?YSLkey={self._loginKey}&actionName=Game%20Reports'

        # what is data and data2 for?
        data = f'YSLkey={self._loginKey}&returnJsp=ShowGameReports.jsp&dateMode=allDates&startDate=2023-11-17&endDate=2023-11-17&ageGroupFilter=all&genderFilter=all&classFilter=all&grSelect=1&grSelect=2&grSelect=3&filterButton=View+Reports'
        data2 = {
            'YSLkey': self._loginKey,
            'returnJsp': 'ShowGameReports.jsp',
            'dateMode': 'allDates',
            'startDate': '2023-11-17',
            'endDate': '2023-11-17',
            'ageGroupFilter': 'all',
            'genderFilter': 'all',
            'classFilter': 'all',
            'grSelect': 1,
            'grSelect': 2,
            'grSelect': 3,
            'filterButton': 'View+Reports'
        }
        #response = requests.post(url, json = data2)
        self._browser.open(url)
        self._browser.select_form('form')
        self._browser['YSLkey'] = self._loginKey
        self._browser['returnJsp'] = 'ShowGameReports.jsp'
        self._browser['dateMode'] = 'selectDates'
        self._browser['startDate'] = startDate
        self._browser['endDate'] = endDate
        response = self._browser.submit_selected()
        return response


    def getReportForSeason(self, startDate: str, endDate: str) -> dict:
        reportData = self.getReportData(startDate, endDate)

        metrics = {
            "gamesPlayed": 0,
            "totalRefAssignments": 0,
            "refsAssigned": 0,
            "refsMissing": 0,
            "missingCenters": 0,
            "missingARs": 0
        }

        entries = reportData.soup.find_all("tr", { "class" : 'trstyle2' })

        metrics['gamesPlayed'] = len(entries)

        for entry in entries:
            elements = entry.find_all('td')

            refsNeeded = 3
            if elements[3].text == 'U-9' or elements[3].text == 'U-10':
                refsNeeded = 1
            metrics['totalRefAssignments'] += refsNeeded

            refsAssigned = 0
            ref1 = elements[8].text.strip('\xa0')
            ref2 = elements[9].text.strip('\xa0')
            ref3 = elements[10].text.strip('\xa0')

            if len(ref1) != 0:
                refsAssigned += 1
            else:
                metrics['missingCenters'] += 1

            if len(ref2) != 0:
                refsAssigned += 1
            else:
                if refsNeeded == 3:
                    metrics['missingARs'] += 1

            if len(ref3) != 0:
                refsAssigned += 1
            else:
                if refsNeeded == 3:
                    metrics['missingARs'] += 1

            metrics['refsAssigned'] += refsAssigned
            metrics['refsMissing'] += refsNeeded - refsAssigned


                #  0 <td>9/8/2023 - 9:30 PM</td>
                #  1 <td>764395 (confirmed)</td>
                #  2 <td><a href="javascript:directWindow('Oakton HS 3 - both sides','No directions available','No comments')">Oakton HS 3 Full field</a></td>
                #  3 <td>O-30</td>
                #  4 <td>Co-ed</td>
                #  5 <td>Rec</td>
                #  6 <td align="center">Team 4</td>
                #  7 <td align="center">Team 3</td>
                #  8 <td align="center">Jaime Villamarin</td>
                #  9 <td align="center">Martin Cooley</td>
                # 10 <td align="center">Jason Allen</td>

                #ref1 = elements[9].text.strip('\n').strip('\r')
                #ref2 = elements[10].text.strip('\n').strip('\r')
                #ref3 = elements[11].text.strip('\n').strip('\r')

        return metrics


