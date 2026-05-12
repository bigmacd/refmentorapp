from datetime import datetime, timedelta
import os
import logging
import psycopg
from typing import Tuple, Optional, Any
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


class RefereeDbCockroach(object):

    def __init__(self):

        self._connectToDb()

        self.executeSql(" SELECT count(table_name) FROM information_schema.tables WHERE table_schema LIKE 'public' AND table_type LIKE 'BASE TABLE' AND table_name='referees'")
        if not self.cursor.fetchone()[0] == 1:
            self.createDb()
        else:
            self.executeSql(" SELECT count(table_name) FROM information_schema.tables WHERE table_schema LIKE 'public' AND table_type LIKE 'BASE TABLE' AND table_name='gamedetails'")
            if not self.cursor.fetchone()[0] == 1:
                self._createNewGameDetailTable()

            # for visitors, drop the old table and create the new one
            # old table is 'visitors'
            # new table is 'user_visits'
            self.executeSql(" SELECT count(table_name) FROM information_schema.tables WHERE table_schema LIKE 'public' AND table_type LIKE 'BASE TABLE' AND table_name='visitors'")
            if self.cursor.fetchone()[0] == 1:
                self.executeSql(" DROP TABLE visitors")

            self.executeSql(" SELECT count(table_name) FROM information_schema.tables WHERE table_schema LIKE 'public' AND table_type LIKE 'BASE TABLE' AND table_name='user_visits'")
            if not self.cursor.fetchone()[0] == 1:
                self._createUserVisitsTable()
            else:
                # Migrate existing table to add new columns if they don't exist
                self._migrateUserVisitsTable()

            self.executeSql(" SELECT count(table_name) FROM information_schema.tables WHERE table_schema LIKE 'public' AND table_type LIKE 'BASE TABLE' AND table_name='users'")
            if not self.cursor.fetchone()[0] == 1:
                self._createUsersTable()

            self.executeSql(" SELECT count(table_name) FROM information_schema.tables WHERE table_schema LIKE 'public' AND table_type LIKE 'BASE TABLE' AND table_name='organizations'")
            if not self.cursor.fetchone()[0] == 1:
                self._createOrganizationsTable()

            self.executeSql(" SELECT count(table_name) FROM information_schema.tables WHERE table_schema LIKE 'public' AND table_type LIKE 'BASE TABLE' AND table_name='user_organizations'")
            if not self.cursor.fetchone()[0] == 1:
                self._createUserOrganizationsTable()

            self.executeSql(" SELECT count(table_name) FROM information_schema.tables WHERE table_schema LIKE 'public' AND table_type LIKE 'BASE TABLE' AND table_name='password_reset_tokens'")
            if not self.cursor.fetchone()[0] == 1:
                self._createPasswordResetTokensTable()

            self.executeSql(" SELECT count(table_name) FROM information_schema.tables WHERE table_schema LIKE 'public' AND table_type LIKE 'BASE TABLE' AND table_name='logs'")
            if not self.cursor.fetchone()[0] == 1:
                self._createLogsTable()

            self.executeSql(" SELECT count(table_name) FROM information_schema.tables WHERE table_schema LIKE 'public' AND table_type LIKE 'BASE TABLE' AND table_name='calendar_events'")
            if not self.cursor.fetchone()[0] == 1:
                self._createCalendarEventsTable()

            self.executeSql(" SELECT count(table_name) FROM information_schema.tables WHERE table_schema LIKE 'public' AND table_type LIKE 'BASE TABLE' AND table_name='mentor_game_selections'")
            if not self.cursor.fetchone()[0] == 1:
                self._createMentorGameSelectionsTable()


    def _connectToDb(self):
        self.connection = psycopg.connect(os.environ['db_url'])
        self.connection.autocommit = True
        self.cursor = self.connection.cursor()


    def executeSql(self, sql: str, params: Optional[Any] = None):
        return self._executeSql(sql, params)


    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((psycopg.OperationalError, psycopg.InterfaceError, psycopg.DatabaseError)),
        reraise=True
    )
    def _executeSql(self, sql: str, params: Optional[Any] = None):
        """
        Execute SQL query with retry logic and automatic reconnection on errors.
        Does not fetch results - caller should use cursor.fetchone() or cursor.fetchall().

        Args:
            sql: SQL query string
            params: Optional parameters for parameterized queries (tuple, list, or dict)
        """
        retVal = None
        try:
            if params:
                retVal = self.cursor.execute(sql, params)
            else:
                retVal = self.cursor.execute(sql)
        except (psycopg.OperationalError, psycopg.InterfaceError) as e:
            # Connection error - reconnect and let retry handle the retry
            logging.warning(f"Database connection error: {e}. Reconnecting...")
            try:
                if hasattr(self, 'connection') and self.connection:
                    try:
                        self.connection.close()
                    except:
                        pass
            except:
                pass
            self._connectToDb()
            # Re-raise to trigger retry
            raise
        except psycopg.DatabaseError as e:
            # Other database errors - log and let retry handle it
            logging.warning(f"Database error: {e}. Will retry...")
            raise
        return retVal



    def createDb(self) -> bool:

        sql = """CREATE TABLE referees (id SERIAL PRIMARY KEY,
                                        lastname TEXT NOT NULL,
                                        firstname TEXT NOT NULL,
                                        year_certified INTEGER)"""
        self.executeSql(sql)

        sql = """CREATE TABLE mentors (id SERIAL PRIMARY KEY,
                                        mentor_last_name TEXT NOT NULL,
                                        mentor_first_name TEXT NOT NULL)"""
        self.executeSql(sql)

        sql = """CREATE TABLE mentor_sessions (id SERIAL PRIMARY KEY,
                                                mentor INTEGER NOT NULL,
                                                mentee INTEGER NOT NULL,
                                                position TEXT NOT NULL,
                                                date TIMESTAMP NOT NULL,
                                                comments TEXT NOT NULL)"""
        self.executeSql(sql)

        sql = """CREATE TABLE risky (id SERIAL PRIMARY KEY,
                                     mentee INTEGER NOT NULL,
                                     mentor_session INTEGER NOT NULL,
                                     date TIMESTAMP NOT NULL DEFAULT NOW())"""
        self.executeSql(sql)

        self._createNewGameDetailTable()
        self._createUserVisitsTable()
        self._createUsersTable()
        self._createPasswordResetTokensTable()
        self._createLogsTable()
        self._createCalendarEventsTable()
        self._createMentorGameSelectionsTable()


    def _createNewGameDetailTable(self):
            sql = """CREATE TABLE gamedetails ( id SERIAL PRIMARY KEY,
                                                venue TEXT NOT NULL,
                                                gameId TEXT NOT NULL,
                                                center TEXT NOT NULL,
                                                ar1 TEXT NOT NULL,
                                                ar2 TEXT NOT NULL,
                                                date text NOT NULL,
                                                time TEXT NOT NULL,
                                                age TEXT NOT NULL,
                                                level TEXT NOT NULL)"""
            self.executeSql(sql)


    def _createUserVisitsTable(self):
        sql = """CREATE TABLE user_visits (username TEXT NOT NULL,
                                           role TEXT NOT NULL,
                                           email TEXT NOT NULL,
                                           date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                           ip_address TEXT,
                                           user_agent TEXT)"""
        self.executeSql(sql)

    def _migrateUserVisitsTable(self):
        """Add new columns to existing user_visits table if they don't exist and migrate date to TIMESTAMPTZ"""
        try:
            # Check if ip_address column exists
            self.executeSql("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='user_visits' AND column_name='ip_address'
            """)
            if not self.cursor.fetchone():
                self.executeSql("ALTER TABLE user_visits ADD COLUMN ip_address TEXT")
                logging.info("Added ip_address column to user_visits table")

            # Check if user_agent column exists
            self.executeSql("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='user_visits' AND column_name='user_agent'
            """)
            if not self.cursor.fetchone():
                self.executeSql("ALTER TABLE user_visits ADD COLUMN user_agent TEXT")
                logging.info("Added user_agent column to user_visits table")

            # Check if date column is TIMESTAMP (without timezone) and convert to TIMESTAMPTZ
            self.executeSql("""
                SELECT data_type
                FROM information_schema.columns
                WHERE table_name='user_visits' AND column_name='date'
            """)
            result = self.cursor.fetchone()
            if result and result[0] == 'timestamp without time zone':
                # Convert TIMESTAMP to TIMESTAMPTZ
                self.executeSql("ALTER TABLE user_visits ALTER COLUMN date TYPE TIMESTAMPTZ USING date AT TIME ZONE 'UTC'")
                logging.info("Converted date column from TIMESTAMP to TIMESTAMPTZ in user_visits table")

            self.connection.commit()
        except Exception as e:
            logging.error(f"Error migrating user_visits table: {e}")
            self.connection.rollback()


    def _createUsersTable(self):
        sql = """CREATE TABLE users (id SERIAL PRIMARY KEY,
                                     username TEXT UNIQUE NOT NULL,
                                     password_hash TEXT NOT NULL,
                                     salt TEXT NOT NULL,
                                     email TEXT UNIQUE NOT NULL,
                                     role TEXT NOT NULL DEFAULT 'user',
                                     created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                                     last_login TIMESTAMP)"""
        self.executeSql(sql)

    def _createOrganizationsTable(self):
        sql = """CREATE TABLE organizations (id SERIAL PRIMARY KEY,
                                            name TEXT NOT NULL UNIQUE,
                                            slug TEXT,
                                            created_at TIMESTAMP NOT NULL DEFAULT NOW())"""
        self.executeSql(sql)

    def _createUserOrganizationsTable(self):
        sql = """CREATE TABLE user_organizations (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                                                 organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                                                 PRIMARY KEY (user_id, organization_id))"""
        self.executeSql(sql)
        self.connection.commit()


    def _createPasswordResetTokensTable(self):
        sql = """CREATE TABLE password_reset_tokens (id SERIAL PRIMARY KEY,
                                                     user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                                                     token TEXT UNIQUE NOT NULL,
                                                     expires_at TIMESTAMP NOT NULL,
                                                     created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                                                     used BOOLEAN NOT NULL DEFAULT FALSE)"""
        self.executeSql(sql)


    def _createLogsTable(self):
        sql = """CREATE TABLE logs (timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
                                    message TEXT NOT NULL)"""
        self.executeSql(sql)

    def _createCalendarEventsTable(self):
        sql = """CREATE TABLE calendar_events (id SERIAL PRIMARY KEY,
                                               title TEXT NOT NULL,
                                               description TEXT,
                                               start_date DATE NOT NULL,
                                               end_date DATE,
                                               start_time TIME,
                                               end_time TIME,
                                               created_by TEXT,
                                               created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                                               updated_at TIMESTAMP NOT NULL DEFAULT NOW())"""
        self.executeSql(sql)

    def _createMentorGameSelectionsTable(self):
        sql = """CREATE TABLE mentor_game_selections (id SERIAL PRIMARY KEY,
                                                      mentor_id INTEGER NOT NULL REFERENCES mentors(id),
                                                      game_date TEXT NOT NULL,
                                                      venue TEXT NOT NULL,
                                                      game_id TEXT NOT NULL,
                                                      selected_at TIMESTAMP NOT NULL DEFAULT NOW(),
                                                      UNIQUE(mentor_id, game_date, venue, game_id))"""
        self.executeSql(sql)


    def addVisitor(self, email: str, username: str, role: str, ip_address: str = None, user_agent: str = None) -> None:
        """
        Add a visitor record to the database.

        Args:
            email: User's email address
            username: Username
            role: User's role
            ip_address: Client IP address (optional)
            user_agent: Browser/user agent string (optional)
        """
        sql = "INSERT INTO user_visits (email, username, role, ip_address, user_agent) values (%s, %s, %s, %s, %s)"
        self.executeSql(sql, (email, username, role, ip_address, user_agent))
        self.connection.commit()


    def _getRiskRange(self) -> list:
        today = datetime.today()

        oneMonthAgo = today - timedelta(days=31)
        return [oneMonthAgo, today]


    def _getSeasonRange(self) -> list:
        # figure out if it is the fall or spring season.  Get reports for just that
        # range.
        today = datetime.today()
        year = today.year
        spring = [f'{year}-01-01', f'{year}-06-30']
        fall =   [f'{year}-07-01', f'{year}-12-31']
        return spring if today.month in (1, 2, 3, 4, 5, 6) else fall


    def _removeRisky(self, mentee: str):
        f, l = mentee.split(' ', 1)
        menteeId = self.findReferee(l, f)
        sql = f"DELETE FROM risky WHERE mentee = '{menteeId}'"
        self.executeSql(sql)


    # finding stuff

    def isRisky(self, lastname: str, firstname: str) -> bool:

        # get today's date and look into the risky table from today back one month
        # if the referee is in the risky table, return true

        range = self._getRiskRange()

        mentee = self.findReferee(lastname, firstname)
        if mentee is None:
            return False

        menteeId = mentee[0]

        sql = f"SELECT * FROM risky WHERE mentee = {menteeId} and date between '{range[0]}' and '{range[1]}'"
        r = self.executeSql(sql)

        return len(r.fetchall()) > 0


    def getRisky(self) -> list:
        range = self._getRiskRange()

        sql = f"SELECT lastname, firstname from referees r where r.id in (SELECT mentee from risky where date between '{range[0]}' and '{range[1]}')"
        r = self.executeSql(sql)
        return r.fetchall()


    def refExists(self, lastname: str, firstname:str) -> bool:
        sql = "SELECT id from referees where lastname = %s and firstname = %s"
        r = self.executeSql(sql, (lastname.lower(), firstname.lower()))
        return len(r.fetchall()) == 1


    def findReferee(self, lastname: str, firstname: str) -> list:
        sql = "SELECT * from referees where lastname = %s and firstname = %s"
        r = self.executeSql(sql, (lastname.lower(), firstname.lower()))
        return r.fetchone()


    def getReferees(self) -> list:
        # retrieve only the referees that have reports
        # return the list in sorted by last name order
        def lastname(item):
            return item[1]

        sql = "select distinct firstname, lastname from referees r join mentor_sessions ms on ms.mentee = r.id"
        r = self.executeSql(sql)
        data = r.fetchall()
        return sorted(data, key=lastname)


    def getRefereesForSelectionBox(self) -> list:
        refs = self.getReferees()
        retVal = []
        for ref in refs:
            retVal.append(f'{ref[0].capitalize()} {ref[1].capitalize()}')
        return retVal


    def getMentorsForSelectionBox(self) -> list:
        mentors = self.getMentors()
        retVal = []
        for mentor in mentors:
            retVal.append(f'{mentor[0].capitalize()} {mentor[1].capitalize()}')
        return retVal


    def getNewReferees(self) -> list:
        today = datetime.today()
        year = today.year
        sql = "SELECT firstname, lastname from referees where year_certified >= %s"
        r = self.executeSql(sql, (year,))
        return r.fetchall()


    def mentorExists(self, firstname: str, lastname:str) -> bool:
        sql = "SELECT id from mentors where mentor_last_name = %s and mentor_first_name = %s"
        r = self.executeSql(sql, (lastname.lower(), firstname.lower()))
        return len(r.fetchall()) == 1


    def findMentor(self, firstname: str, lastname: str) -> list:
        sql = "SELECT * from mentors where mentor_last_name = %s and mentor_first_name = %s"
        r = self.executeSql(sql, (lastname.lower(), firstname.lower()))
        return r.fetchone()


    def getMentors(self) -> list:
        sql = "SELECT mentor_first_name, mentor_last_name from mentors"
        r = self.executeSql(sql)
        return r.fetchall()


    # def getMentoringSessions(self) -> dict:

    #     range = self._getSeasonRange()

    #     retVal = {}
    #     sql = f"select distinct r.lastname, r.firstname, ms.position, ms.date from mentor_sessions ms join referees r on ms.mentee = r.id where ms.date between '{range[0]}' and '{range[1]}'"
    #     r = self.executeSql(sql)
    #     rows = r.fetchall()
    #     for row in rows:
    #         retVal[f'{row[1]} {row[0]}'] = [ row[2], row[3]]
    #     return retVal


    def getMentoringSessionMetrics(self, year: int, season: str) -> dict:
        '''
        season is either 'fall' or 'spring'
        returns number of referees mentored and number of mentoring sessions
        '''

        def getRanges(season: str, year: int) -> list:
            if season == 'fall':
                return [f'{year}-07-01', f'{year}-12-31']
            else:
                return [f'{year}-04-01', f'{year}-06-30']

        range = getRanges(season, year)
        sql = f"""
            SELECT
            COUNT(DISTINCT ms.mentor) AS distinct_mentors,
            COUNT(DISTINCT ms.mentee) AS distinct_referees,
            COUNT(DISTINCT ms.id) AS distinct_reports
            FROM mentor_sessions ms
            WHERE ms.date BETWEEN '{range[0]}' AND '{range[1]}'
        """
        r = self.executeSql(sql)
        data =  r.fetchall()
        retVal = {
            'mentors': data[0][0],
            'referees': data[0][1],
            'reports': data[0][2]
        }
        return retVal


    def getMentoringSessions(self) -> dict:

        range = self._getSeasonRange()

        retVal = {}
        # sql = f"select r.lastname, r.firstname, ms.position from mentor_sessions ms join referees r on ms.mentee = r.id where ms.date between '{range[0]}' and '{range[1]}'"
        sql = f"select r.lastname, r.firstname, ms.position from mentor_sessions ms join referees r on ms.mentee = r.id"
        r = self.executeSql(sql)
        rows = r.fetchall()
        for row in rows:
            key = f'{row[1]} {row[0]}'
            if key not in retVal:
                retVal[key] = []
            retVal[key].append(row[2])
        return retVal


    def getMentoringSessionDetails(self, year: int) -> dict:

        range = [f'{year}-01-01', f'{year}-12-31']
        sql = f"select r.firstname, r.lastname, ms.position, ms.date, ms.comments, me.mentor_last_name, me.mentor_first_name \
              from mentor_sessions ms \
              join referees r on ms.mentee = r.id join mentors me on ms.mentor = me.id \
              where ms.date between '{range[0]}' and '{range[1]}' ORDER BY ms.date"
        sql = f"select r.firstname, r.lastname, ms.position, ms.date, ms.comments, me.mentor_last_name, me.mentor_first_name, \
              gd.gameid, gd.center, gd.ar1, gd.ar2, gd.date AS game_date, gd.venue, gd.time, gd.age, gd.level \
              from mentor_sessions ms \
              join referees r on ms.mentee = r.id join mentors me on ms.mentor = me.id \
              left join gamedetails gd on ms.gameid = gd.gameid \
              where ms.date between '{range[0]}' and '{range[1]}' ORDER BY ms.date"
        r = self.executeSql(sql)
        return r.fetchall()


    def getMentoringsessionsForWeek(self, week: str) -> dict:
        # week string is like "Friday, April 14, 2023"
        d = datetime.strptime(week, "%A, %B %d, %Y")
        dt = d.strftime("%Y-%m-%d")
        sql = f"select r.firstname, r.lastname, ms.position, ms.date, ms.comments, me.mentor_last_name, me.mentor_first_name \
              from mentor_sessions ms \
              join referees r on ms.mentee = r.id join mentors me on ms.mentor = me.id \
              where ms.date = '{dt}'"
        sql = f"select r.firstname, r.lastname, ms.position, ms.date, ms.comments, me.mentor_last_name, me.mentor_first_name, \
              gd.gameid, gd.center, gd.ar1, gd.ar2, gd.date AS game_date, gd.venue, gd.time, gd.age, gd.level from mentor_sessions ms \
              join referees r on ms.mentee = r.id join mentors me on ms.mentor = me.id \
              left join gamedetails gd on ms.gameid = gd.gameid \
              where ms.date = '{dt}'"
        r = self.executeSql(sql)
        return r.fetchall()


    def getMentoringsessionsForReferee(self, referee: str) -> dict:
        # referee string is like "Kate Curby"
        firstname, lastname = referee.split(' ', 1)
        sql = f"select r.firstname, r.lastname, ms.position, ms.date, ms.comments, me.mentor_last_name, me.mentor_first_name \
              from mentor_sessions ms \
              join referees r on ms.mentee = r.id join mentors me on ms.mentor = me.id \
              where r.firstname = '{firstname.lower()}' and r.lastname = '{lastname.lower()}' \
              order by ms.date"
        sql = f"select r.firstname, r.lastname, ms.position, ms.date, ms.comments, me.mentor_last_name, me.mentor_first_name, \
              gd.gameid, gd.center, gd.ar1, gd.ar2, gd.date AS game_date, gd.venue, gd.time, gd.age, gd.level from mentor_sessions ms \
              join referees r on ms.mentee = r.id join mentors me on ms.mentor = me.id \
              left join gamedetails gd on ms.gameid = gd.gameid \
              where r.firstname = '{firstname.lower()}' and r.lastname = '{lastname.lower()}' \
              order by ms.date"
        r = self.executeSql(sql)
        return r.fetchall()


    def getMentoringsessionsForMentor(self, mentor: str) -> dict:
        # mentor string is like "David Helfgott"
        firstname, lastname = mentor.split(' ', 1)
        sql = f"select r.firstname, r.lastname, ms.position, ms.date, ms.comments, me.mentor_last_name, me.mentor_first_name \
              from mentor_sessions ms \
              join referees r on ms.mentee = r.id join mentors me on ms.mentor = me.id \
              where me.mentor_first_name = '{firstname.lower()}' and me.mentor_last_name = '{lastname.lower()}' \
              order by ms.date"
        sql = f"select r.firstname, r.lastname, ms.position, ms.date, ms.comments, me.mentor_last_name, me.mentor_first_name, \
              gd.gameid, gd.center, gd.ar1, gd.ar2, gd.date AS game_date, gd.venue, gd.time, gd.age, gd.level from mentor_sessions ms \
              join referees r on ms.mentee = r.id join mentors me on ms.mentor = me.id \
              left join gamedetails gd on ms.gameid = gd.gameid \
              where me.mentor_first_name = '{firstname.lower()}' and me.mentor_last_name = '{lastname.lower()}' \
              order by ms.date"
        r = self.executeSql(sql)
        return r.fetchall()

    def getYears(self) -> list:
        retVal = []
        sql = 'SELECT DISTINCT date from mentor_sessions'
        r = self.executeSql(sql)
        data = r.fetchall()
        for d in data:
            if d[0].year not in retVal:
                retVal.append(d[0].year)
        return retVal


    # adding data
    def setIsRisky(self, mentee: int, mentorSession: int, dt: datetime):
        sql = "INSERT into risky (mentee, mentor_session, date) \
               VALUES (%s, %s, %s)"
        self.executeSql(sql, (mentee, mentorSession, dt))
        self.connection.commit()


    def addReferee(self, lastname: str, firstname: str, year: int):
        sql = "INSERT INTO referees (lastname, firstname, year_certified) \
               VALUES (%s, %s, %s)"
        self.executeSql(sql, (lastname, firstname, year))
        self.connection.commit()


    def addMentor(self, firstname: str, lastname: str) -> None:
        sql = "INSERT INTO mentors (mentor_last_name, mentor_first_name) \
               VALUES (%s, %s)"
        self.executeSql(sql, (lastname, firstname))
        self.connection.commit()


    def addMentorSession(self,
                         mentor: str,
                         mentee: str,
                         position: str,
                         date: str,
                         comments: str,
                         gameid: str) -> Tuple[bool, str]:
        logging.info(f'Adding mentor session for *{mentee}* from *{mentor}* with no risky set')
        sql = 'INSERT INTO mentor_sessions (mentor, mentee, position, date, comments, gameid) \
               VALUES (%s, %s, %s, %s, %s, %s)'
        f, l = mentee.split(' ', 1)
        logging.info(f"Referee first name: {f}, last name: {l}")
        mentorId = self.findMentor(mentor.split(' ')[0], mentor.split(' ')[1])
        menteeId = self.findReferee(l, f)
        logging.info(f'Mentor ID: {mentorId}, Mentee ID: {menteeId}')
        if mentorId is None:
            return (False, f'599: Could not find mentor details for {mentor}')
        if menteeId is None:
            return (False, f'601:Could not find referee details for {mentee}')

        dt = datetime.strptime(date, "%A, %B %d, %Y")

        try:
            self.executeSql(sql,
                                [mentorId[0],
                                menteeId[0],
                                position,
                                dt,
                                comments,
                                gameid])
        except Exception as ex:
            return (False, f'Failed to add mentor report: {ex}')
        else:
            self.connection.commit()
            return (True, "Mentor Report successfully submitted!")


    def addMentorSessionNew(self,
                            mentor: str,
                            mentee: str,
                            position: str,
                            date: str,
                            comments: str,
                            isRisky: bool,
                            gameid: str) -> Tuple[bool, str]:


        logging.info(f'Adding mentor session new for *{mentee}* from *{mentor}* with risky: {isRisky}')
        if not isRisky:
            logging.info(f'Removing risky for {mentee}')
            self._removeRisky(mentee)
            return self.addMentorSession(mentor, mentee, position, date, comments, gameid)

        logging.info(f'Adding mentor session for *{mentee}* from *{mentor}* with risky: {isRisky}')
        sql = 'INSERT INTO mentor_sessions (mentor, mentee, position, date, comments, gameid) \
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id'
        f, l = mentee.split(' ', 1)
        logging.info(f"Referee first name: {f}, last name: {l}")
        mentorId = self.findMentor(mentor.split(' ')[0], mentor.split(' ')[1])
        menteeId = self.findReferee(l, f)
        logging.info(f'Mentor ID: {mentorId}, Mentee ID: {menteeId}')
        if mentorId is None:
            return (False, f'645:Could not find mentor details for {mentor}')
        if menteeId is None:
            return (False, f'647:Could not find referee details for {mentee}')

        dt = datetime.strptime(date, "%A, %B %d, %Y")

        try:
            self.executeSql(sql,
                                [mentorId[0],
                                menteeId[0],
                                position,
                                dt,
                                comments,
                                gameid])
            newId = self.cursor.fetchone()[0]

        except Exception as ex:
            return (False, f'Failed to add mentor report: {ex}')
        else:
            self.connection.commit()
            self.setIsRisky(menteeId[0], newId, dt)
            return (True, "Mentor Report successfully submitted!")

    def _getTextFromSessions(self, sessions):

        # TODO - use game details in the report if not null (from database left joining)
        # These are the columns we have from the left join:
        # firstname
        # lastname
        # position
        # date
        # comments
        # mentor_last_name
        # mentor_first_name
        # gameid
        # center
        # ar1
        # ar2
        # game_date
        # venue
        # time
        # age
        # level

        retVal = ''
        # [0] is firstname, [1] is lastname, [2] is position
        # [3] is date and [4] is comments
        sessionData = {}

        for session in sessions:
            date = session[3]
            if date not in sessionData: # session[3] is date
                sessionData[date] = []

            entry = {
                    'ref': f'{session[0].capitalize()} {session[1].capitalize()}',
                    'position': session[2],
                    'mentor': f'{session[6].capitalize()} {session[5].capitalize()}',
                    'comments': session[4],
                    'gameid': session[7],
                    'center': session[8],
                    'ar1': session[9],
                    'ar2': session[10],
                    'game_date': session[11],
                    'venue': session[12],
                    'time': session[13],
                    'age': session[14],
                    'level': session[15]
                }
            sessionData[date].append(entry)

        # build a big `ol string to returned as a download`
        for k, entries in sessionData.items():
            retVal += f'Date: {k}\r\n'
            for entry in entries:
                retVal += f"\tReferee: {entry['ref']}\r\n"
                retVal += f"\tPosition: {entry['position']}\r\n"
                retVal += f"\tMentor: {entry['mentor']}\r\n"
                retVal += f"\tComments: {entry['comments']}\r\n\r\n"

                if entry['gameid'] is not None:
                    retVal += f"\tGame Details:\r\n"
                    retVal += f"\t\tGame ID: {entry['gameid']}\r\n"
                    retVal += f"\t\tCenter: {entry['center']}\r\n"
                    retVal += f"\t\tAR1: {entry['ar1']}\r\n"
                    retVal += f"\t\tAR2: {entry['ar2']}\r\n"
                    retVal += f"\t\tGame Date: {entry['game_date']}\r\n"
                    retVal += f"\t\tVenue: {entry['venue']}\r\n"
                    retVal += f"\t\tTime: {entry['time']}\r\n"
                    retVal += f"\t\tAge Group: {entry['age']}\r\n"
                    retVal += f"\t\tLevel: {entry['level']}\r\n\r\n"

        return retVal


    def produceYearReport(self, year):
        sessions = self.getMentoringSessionDetails(year)
        return self._getTextFromSessions(sessions)


    def produceWeekReport(self, week):
        sessions = self.getMentoringsessionsForWeek(week)
        return self._getTextFromSessions(sessions)


    def produceRefereeReport(self, referee):
        for name in referee:
            name.lower()
        sessions = self.getMentoringsessionsForReferee(referee)
        return self._getTextFromSessions(sessions)


    def produceMentorReport(self, mentor):
        sessions = self.getMentoringsessionsForMentor(mentor)
        return self._getTextFromSessions(sessions)


    # The below was added so we can also track the game details

    def gameDetailsExist(self, gameId: str, date: str, time: str) -> bool:
        sql = "SELECT * from gamedetails where gameId = %s and date = %s and time = %s"
        try:
            self.executeSql(sql, (gameId, date, time))
        except Exception as ex:
            print(ex)
        return not self.cursor.fetchone() == None


    def addGameDetails(self, currentGames: dict) -> None:

        sql = """insert into gamedetails (venue,
                                    gameId,
                                    center,
                                    ar1,
                                    ar2,
                                    date,
                                    time,
                                    age,
                                    level)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""

        for venue, gameDetails in currentGames.items():
            for gameid, game in gameDetails.items():
                if 'VENUE CONFLICT' in gameid:
                    gameid = gameid.replace('VENUE CONFLICT', '')
                if self.gameDetailsExist(gameid, game['date'], game['gameTime']) is False:
                    self.executeSql(sql, (venue,
                                            gameid,
                                            game['Center'],
                                            game['AR1'],
                                            game['AR2'],
                                            game['date'],
                                            game['gameTime'],
                                            game['age'],
                                            game['level']))


    # User management methods for authentication

    def userExists(self, username: str) -> bool:
        """Check if a username already exists"""
        sql = "SELECT id FROM users WHERE username = %s"
        self.executeSql(sql, (username.lower(),))
        return self.cursor.fetchone() is not None


    def emailExists(self, email: str) -> bool:
        """Check if an email already exists"""
        sql = "SELECT id FROM users WHERE email = %s"
        self.executeSql(sql, (email.lower(),))
        return self.cursor.fetchone() is not None


    def createUser(self, username: str, password_hash: str, salt: str, email: str, role: str = 'user') -> None:
        """Create a new user"""
        sql = "INSERT INTO users (username, password_hash, salt, email, role) VALUES (%s, %s, %s, %s, %s)"
        self.executeSql(sql, (username.lower(), password_hash, salt, email.lower(), role))
        self.connection.commit()


    def getUserByUsername(self, username: str) -> dict:
        """Get user by username"""
        sql = "SELECT id, username, password_hash, salt, email, role, created_at, last_login FROM users WHERE username = %s"
        self.executeSql(sql, (username.lower(),))
        row = self.cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'username': row[1],
                'password_hash': row[2],
                'salt': row[3],
                'email': row[4],
                'role': row[5],
                'created_at': row[6],
                'last_login': row[7]
            }
        return None


    def getAllUsers(self) -> list:
        """Get all users"""
        sql = "SELECT id, username, email, role, created_at, last_login FROM users ORDER BY username"
        self.executeSql(sql)
        rows = self.cursor.fetchall()
        users = []
        for row in rows:
            users.append({
                'id': row[0],
                'username': row[1],
                'email': row[2],
                'role': row[3],
                'created_at': row[4],
                'last_login': row[5]
            })
        return users

    def getOrganizations(self) -> list:
        """Get all organizations for multi-tenant login"""
        sql = "SELECT id, name, slug FROM organizations ORDER BY name"
        self.executeSql(sql)
        rows = self.cursor.fetchall()
        return [{'id': row[0], 'name': row[1], 'slug': row[2] or ''} for row in rows]

    def getOrganizationIdsForUser(self, user_id: int) -> list:
        """Return organization ids the user belongs to"""
        sql = "SELECT organization_id FROM user_organizations WHERE user_id = %s"
        self.executeSql(sql, (user_id,))
        return [row[0] for row in self.cursor.fetchall()]

    def userBelongsToOrganization(self, user_id: int, organization_id: int) -> bool:
        """Check if user belongs to the given organization"""
        sql = "SELECT 1 FROM user_organizations WHERE user_id = %s AND organization_id = %s"
        self.executeSql(sql, (user_id, organization_id))
        return self.cursor.fetchone() is not None

    def addUserToOrganization(self, user_id: int, organization_id: int) -> None:
        """Associate a user with an organization"""
        sql = "INSERT INTO user_organizations (user_id, organization_id) VALUES (%s, %s) ON CONFLICT (user_id, organization_id) DO NOTHING"
        self.executeSql(sql, (user_id, organization_id))
        self.connection.commit()

    def updateUserPassword(self, username: str, password_hash: str, salt: str) -> None:
        """Update user password"""
        sql = "UPDATE users SET password_hash = %s, salt = %s WHERE username = %s"
        self.executeSql(sql, (password_hash, salt, username.lower()))
        self.connection.commit()


    def updateLastLogin(self, username: str) -> None:
        """Update user's last login time"""
        sql = "UPDATE users SET last_login = NOW() WHERE username = %s"
        self.executeSql(sql, (username.lower(),))
        self.connection.commit()


    def deleteUser(self, user_id: int) -> None:
        """Delete a user"""
        sql = "DELETE FROM users WHERE id = %s"
        self.executeSql(sql, (user_id,))
        self.connection.commit()


    def getUserByEmail(self, email: str) -> dict:
        """Get user by email address"""
        sql = "SELECT id, username, password_hash, salt, email, role, created_at, last_login FROM users WHERE email = %s"
        self.executeSql(sql, (email.lower(),))
        row = self.cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'username': row[1],
                'password_hash': row[2],
                'salt': row[3],
                'email': row[4],
                'role': row[5],
                'created_at': row[6],
                'last_login': row[7]
            }
        return None


    def createPasswordResetToken(self, user_id: int, token: str, expires_at: datetime) -> None:
        """Create a password reset token"""
        # First, invalidate any existing tokens for this user
        sql = "UPDATE password_reset_tokens SET used = TRUE WHERE user_id = %s AND used = FALSE"
        self.executeSql(sql, (user_id,))

        # Create the new token
        sql = "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)"
        self.executeSql(sql, (user_id, token, expires_at))
        self.connection.commit()


    def getPasswordResetToken(self, token: str, current_email: str) -> dict:
        """Get password reset token details"""
        sql = '''
          SELECT prt.id, prt.user_id, prt.token, prt.expires_at, prt.used, u.email, u.username
          FROM password_reset_tokens prt
          JOIN users u ON prt.user_id = u.id
          WHERE prt.token = %s AND prt.used = FALSE AND prt.expires_at > (NOW() AT TIME ZONE 'UTC')::TIMESTAMP AND LOWER(u.email) = LOWER(%s)
        '''

        self.executeSql(sql, (token, current_email))
        row = self.cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'user_id': row[1],
                'token': row[2],
                'expires_at': row[3],
                'used': row[4],
                'email': row[5],
                'username': row[6]
            }
        return None


    def getUsernameByResetToken(self, token: str) -> str:
        """Get username associated with a valid password reset token"""
        sql = "select u.email from password_reset_tokens prt JOIN users u on prt.user_id = u.id where prt.token = %s and prt.used = false and prt.expires_at > (NOW() AT TIME ZONE 'UTC')::TIMESTAMP"
        self.executeSql(sql, (token,))
        row = self.cursor.fetchone()
        if row:
            return row[0]
        return None


    def usePasswordResetToken(self, token: str) -> None:
        """Mark a password reset token as used"""
        sql = "UPDATE password_reset_tokens SET used = TRUE WHERE token = %s"
        self.executeSql(sql, (token,))
        self.connection.commit()


    def cleanupExpiredTokens(self) -> None:
        """Remove expired password reset tokens"""
        sql = "DELETE FROM password_reset_tokens WHERE expires_at < NOW() OR used = TRUE"
        self.executeSql(sql)
        self.connection.commit()


    def logMessage(self, message: str) -> None:
        """Log a message to the logs table"""
        sql = "INSERT INTO logs (message) VALUES (%s)"
        self.executeSql(sql, (message,))
        self.connection.commit()


    # Calendar Events methods

    def addCalendarEvent(self, title: str, description: str, start_date: str, end_date: str = None,
                        start_time: str = None, end_time: str = None, created_by: str = None) -> Tuple[bool, str, int]:
        """Add a calendar event. Returns (success, message, event_id)"""
        sql = """INSERT INTO calendar_events (title, description, start_date, end_date, start_time, end_time, created_by)
                 VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id"""
        try:
            self.executeSql(sql, (title, description or '', start_date, end_date, start_time, end_time, created_by))
            event_id = self.cursor.fetchone()[0]
            self.connection.commit()
            return (True, "Event created successfully", event_id)
        except Exception as ex:
            return (False, f'Failed to add calendar event: {ex}', -1)

    def getCalendarEvents(self, start_date: str = None, end_date: str = None) -> list:
        """Get calendar events, optionally filtered by date range"""
        if start_date and end_date:
            sql = """SELECT id, title, description, start_date, end_date, start_time, end_time, created_by, created_at, updated_at
                     FROM calendar_events
                     WHERE start_date <= %s AND (end_date >= %s OR end_date IS NULL)
                     ORDER BY start_date, start_time"""
            self.executeSql(sql, (end_date, start_date))
        else:
            sql = """SELECT id, title, description, start_date, end_date, start_time, end_time, created_by, created_at, updated_at
                     FROM calendar_events
                     ORDER BY start_date, start_time"""
            self.executeSql(sql)

        rows = self.cursor.fetchall()
        events = []
        for row in rows:
            events.append({
                'id': row[0],
                'title': row[1],
                'description': row[2] or '',
                'start_date': row[3],
                'end_date': row[4],
                'start_time': row[5].strftime('%H:%M') if row[5] else None,
                'end_time': row[6].strftime('%H:%M') if row[6] else None,
                'created_by': row[7],
                'created_at': row[8],
                'updated_at': row[9]
            })
        return events

    def getCalendarEvent(self, event_id: int) -> dict:
        """Get a single calendar event by ID"""
        sql = """SELECT id, title, description, start_date, end_date, start_time, end_time, created_by, created_at, updated_at
                 FROM calendar_events WHERE id = %s"""
        self.executeSql(sql, (event_id,))
        row = self.cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'title': row[1],
                'description': row[2] or '',
                'start_date': row[3],
                'end_date': row[4],
                'start_time': row[5].strftime('%H:%M') if row[5] else None,
                'end_time': row[6].strftime('%H:%M') if row[6] else None,
                'created_by': row[7],
                'created_at': row[8],
                'updated_at': row[9]
            }
        return None

    def updateCalendarEvent(self, event_id: int, title: str, description: str, start_date: str,
                           end_date: str = None, start_time: str = None, end_time: str = None) -> Tuple[bool, str]:
        """Update a calendar event. Returns (success, message)"""
        sql = """UPDATE calendar_events
                 SET title = %s, description = %s, start_date = %s, end_date = %s,
                     start_time = %s, end_time = %s, updated_at = NOW()
                 WHERE id = %s"""
        try:
            self.executeSql(sql, (title, description or '', start_date, end_date, start_time, end_time, event_id))
            self.connection.commit()
            if self.cursor.rowcount == 0:
                return (False, "Event not found")
            return (True, "Event updated successfully")
        except Exception as ex:
            return (False, f'Failed to update calendar event: {ex}')

    def deleteCalendarEvent(self, event_id: int) -> Tuple[bool, str]:
        """Delete a calendar event. Returns (success, message)"""
        sql = "DELETE FROM calendar_events WHERE id = %s"
        try:
            self.executeSql(sql, (event_id,))
            self.connection.commit()
            if self.cursor.rowcount == 0:
                return (False, "Event not found")
            return (True, "Event deleted successfully")
        except Exception as ex:
            return (False, f'Failed to delete calendar event: {ex}')


    # Mentor Game Selections methods

    def addMentorGameSelection(self, mentor_firstname: str, mentor_lastname: str, game_date: str,
                               venue: str, game_id: str) -> Tuple[bool, str]:
        """Add a mentor game selection. Returns (success, message)"""
        try:
            mentor = self.findMentor(mentor_firstname.lower(), mentor_lastname.lower())
            if not mentor:
                return (False, f'Mentor not found: {mentor_firstname} {mentor_lastname}')

            sql = """INSERT INTO mentor_game_selections (mentor_id, game_date, venue, game_id)
                     VALUES (%s, %s, %s, %s)"""
            self.executeSql(sql, (mentor[0], game_date, venue, game_id))
            self.connection.commit()
            return (True, "Game selection added successfully")
        except Exception as ex:
            if 'duplicate key' in str(ex).lower() or 'unique constraint' in str(ex).lower():
                return (False, "Game already selected by this mentor")
            return (False, f'Failed to add game selection: {ex}')

    def removeMentorGameSelection(self, mentor_firstname: str, mentor_lastname: str, game_date: str,
                                  venue: str, game_id: str) -> Tuple[bool, str]:
        """Remove a mentor game selection. Returns (success, message)"""
        try:
            mentor = self.findMentor(mentor_firstname.lower(), mentor_lastname.lower())
            if not mentor:
                return (False, f'Mentor not found: {mentor_firstname} {mentor_lastname}')

            sql = """DELETE FROM mentor_game_selections
                     WHERE mentor_id = %s AND game_date = %s AND venue = %s AND game_id = %s"""
            self.executeSql(sql, (mentor[0], game_date, venue, game_id))
            self.connection.commit()
            if self.cursor.rowcount == 0:
                return (False, "Game selection not found")
            return (True, "Game selection removed successfully")
        except Exception as ex:
            return (False, f'Failed to remove game selection: {ex}')

    def getMentorGameSelections(self, game_date: str = None) -> list:
        """Get mentor game selections, optionally filtered by date"""
        if game_date:
            sql = """SELECT m.mentor_first_name, m.mentor_last_name, mgs.game_date, mgs.venue, mgs.game_id, mgs.selected_at
                     FROM mentor_game_selections mgs
                     JOIN mentors m ON mgs.mentor_id = m.id
                     WHERE mgs.game_date = %s
                     ORDER BY mgs.selected_at"""
            self.executeSql(sql, (game_date,))
        else:
            sql = """SELECT m.mentor_first_name, m.mentor_last_name, mgs.game_date, mgs.venue, mgs.game_id, mgs.selected_at
                     FROM mentor_game_selections mgs
                     JOIN mentors m ON mgs.mentor_id = m.id
                     ORDER BY mgs.game_date, mgs.selected_at"""
            self.executeSql(sql)

        rows = self.cursor.fetchall()
        selections = []
        for row in rows:
            selections.append({
                'mentor_firstname': row[0],
                'mentor_lastname': row[1],
                'mentor_name': f"{row[0].capitalize()} {row[1].capitalize()}",
                'game_date': row[2],
                'venue': row[3],
                'game_id': row[4],
                'selected_at': row[5]
            })
        return selections

    def isGameSelectedByMentor(self, mentor_firstname: str, mentor_lastname: str, game_date: str,
                               venue: str, game_id: str) -> bool:
        """Check if a specific game is selected by a mentor"""
        try:
            mentor = self.findMentor(mentor_firstname.lower(), mentor_lastname.lower())
            if not mentor:
                return False

            sql = """SELECT COUNT(*) FROM mentor_game_selections
                     WHERE mentor_id = %s AND game_date = %s AND venue = %s AND game_id = %s"""
            self.executeSql(sql, (mentor[0], game_date, venue, game_id))
            return self.cursor.fetchone()[0] > 0
        except Exception as ex:
            return False

    def getGameSelectionsByGame(self, game_date: str, venue: str, game_id: str) -> list:
        """Get all mentors who have selected a specific game"""
        sql = """SELECT m.mentor_first_name, m.mentor_last_name
                 FROM mentor_game_selections mgs
                 JOIN mentors m ON mgs.mentor_id = m.id
                 WHERE mgs.game_date = %s AND mgs.venue = %s AND mgs.game_id = %s
                 ORDER BY mgs.selected_at"""
        self.executeSql(sql, (game_date, venue, game_id))
        rows = self.cursor.fetchall()
        return [f"{row[0].capitalize()} {row[1].capitalize()}" for row in rows]


