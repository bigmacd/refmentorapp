from datetime import datetime, timedelta
import json
import os
import logging
import re
import psycopg
from typing import Tuple, Optional, Any, List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from report_sessions import MentoringSessionRow, rows_from_db_tuples, text_from_session_rows


def _parse_user_settings(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


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

            # Existing DBs restored from pre-multi-tenant backups need column migrations
            self._migrateMultiTenantSchema()

        # Fresh createDb() path also needs org tables + columns before first use
        if self._tableExists('referees') and not self._columnExists('referees', 'organization_id'):
            self._migrateMultiTenantSchema()
        elif self._tableExists('users') and (
            not self._columnExists('users', 'first_name')
            or not self._columnExists('users', 'last_name')
        ):
            self._migrateMultiTenantSchema()

        self._migrateUsersSettingsColumn()
        self._migrateUsersAvatarColumn()
        try:
            from avatars import import_legacy_file_avatars
            import_legacy_file_avatars(self)
        except Exception:
            logging.exception('Could not import legacy avatar files')
        self._ensureOneMentorPerGameConstraint()


    def _tableExists(self, table_name: str) -> bool:
        self.executeSql(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE' AND table_name = %s
            """,
            (table_name,),
        )
        return self.cursor.fetchone() is not None

    def _columnExists(self, table_name: str, column_name: str) -> bool:
        self.executeSql(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
            """,
            (table_name, column_name),
        )
        return self.cursor.fetchone() is not None

    def _ensureOrganizationsSeeded(self) -> int:
        """Ensure organizations / user_organizations exist and at least one org row is present."""
        if not self._tableExists('organizations'):
            self._createOrganizationsTable()
        if not self._tableExists('user_organizations'):
            self._createUserOrganizationsTable()

        self.executeSql("SELECT id FROM organizations ORDER BY id LIMIT 1")
        row = self.cursor.fetchone()
        if row:
            return row[0]

        self.executeSql(
            "INSERT INTO organizations (name, slug) VALUES (%s, %s) RETURNING id",
            ('Default', 'default'),
        )
        org_id = self.cursor.fetchone()[0]
        self.connection.commit()
        logging.info("Created default organization id=%s", org_id)
        return org_id

    def _pickBackfillOrganizationId(self, fallback: int) -> int:
        """
        Choose which org owns pre-multi-tenant rows.

        Preference: ORGANIZATION_ID env → VYS → Default → fallback / first org.
        """
        env_org = os.environ.get('ORGANIZATION_ID')
        if env_org:
            return int(env_org)

        orgs = self.getOrganizations()
        if not orgs:
            return fallback

        for org in orgs:
            slug = (org.get('slug') or '').lower()
            name = (org.get('name') or '').lower()
            if slug == 'vys' or name == 'vys' or 'vys' in name.split():
                return org['id']

        for org in orgs:
            if org.get('slug') == 'default' or org.get('name') == 'Default':
                return org['id']

        return orgs[0]['id']

    def _addOrganizationIdColumn(self, table_name: str, default_org_id: int) -> None:
        """Add organization_id to an existing table, backfill, and set NOT NULL."""
        if not self._tableExists(table_name):
            return
        if self._columnExists(table_name, 'organization_id'):
            # Backfill any NULLs left from a partial prior migration
            self.executeSql(
                f"UPDATE {table_name} SET organization_id = %s WHERE organization_id IS NULL",
                (default_org_id,),
            )
            return

        logging.info(
            "Migrating %s: adding organization_id (backfill org_id=%s)",
            table_name,
            default_org_id,
        )
        self.executeSql(f"ALTER TABLE {table_name} ADD COLUMN organization_id INTEGER")
        self.executeSql(
            f"UPDATE {table_name} SET organization_id = %s WHERE organization_id IS NULL",
            (default_org_id,),
        )
        self.executeSql(f"ALTER TABLE {table_name} ALTER COLUMN organization_id SET NOT NULL")
        try:
            self.executeSql(
                f"""
                ALTER TABLE {table_name}
                ADD CONSTRAINT {table_name}_organization_id_fkey
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
                """
            )
        except Exception as ex:
            # Constraint may already exist or CRDB may name it differently — non-fatal
            logging.warning("Could not add FK on %s.organization_id: %s", table_name, ex)
            try:
                self.connection.rollback()
            except Exception:
                pass
        logging.info("Migrated %s.organization_id", table_name)

    def _migrateUsersNameColumns(self) -> None:
        """Ensure users.first_name / users.last_name exist (required for mentor UI queries)."""
        if not self._tableExists('users'):
            return

        added = False
        if not self._columnExists('users', 'first_name'):
            self.executeSql("ALTER TABLE users ADD COLUMN first_name TEXT")
            logging.info("Added users.first_name")
            added = True
        if not self._columnExists('users', 'last_name'):
            self.executeSql("ALTER TABLE users ADD COLUMN last_name TEXT")
            logging.info("Added users.last_name")
            added = True

        # Prefer names from legacy mentors table when usernames align with mentor first names
        if self._tableExists('mentors'):
            try:
                self.executeSql(
                    """
                    UPDATE users u
                    SET first_name = COALESCE(NULLIF(TRIM(u.first_name), ''), m.mentor_first_name),
                        last_name = COALESCE(NULLIF(TRIM(u.last_name), ''), m.mentor_last_name)
                    FROM mentors m
                    WHERE LOWER(u.username) = LOWER(m.mentor_first_name)
                       OR LOWER(u.username) = LOWER(CONCAT(m.mentor_first_name, m.mentor_last_name))
                       OR LOWER(u.username) = LOWER(CONCAT(m.mentor_first_name, '-', m.mentor_last_name))
                       OR LOWER(u.username) = LOWER(CONCAT(m.mentor_first_name, '.', m.mentor_last_name))
                    """
                )
            except Exception as ex:
                logging.warning("Could not backfill user names from mentors table: %s", ex)

        # Last resort so getMentors() returns rows: use username for blank names
        self.executeSql(
            """
            UPDATE users
            SET first_name = COALESCE(NULLIF(TRIM(first_name), ''), username),
                last_name = COALESCE(NULLIF(TRIM(last_name), ''), username)
            WHERE COALESCE(TRIM(first_name), '') = ''
               OR COALESCE(TRIM(last_name), '') = ''
            """
        )
        if added:
            logging.info("Migrated users name columns")

    def _migrateUsersSettingsColumn(self) -> None:
        """Ensure users.settings exists for account-scoped preferences."""
        if not self._tableExists('users'):
            return
        if self._columnExists('users', 'settings'):
            return
        self.executeSql("ALTER TABLE users ADD COLUMN settings JSONB NOT NULL DEFAULT '{}'::jsonb")
        logging.info("Added users.settings")

    def _migrateUsersAvatarColumn(self) -> None:
        """Ensure users.avatar_jpeg exists for account-scoped profile photos."""
        if not self._tableExists('users'):
            return
        if self._columnExists('users', 'avatar_jpeg'):
            return
        self.executeSql("ALTER TABLE users ADD COLUMN avatar_jpeg BYTEA")
        logging.info("Added users.avatar_jpeg")

    def _migrateMultiTenantSchema(self) -> None:
        """
        Bring a restored / pre-multi-tenant database up to the org-scoped schema.

        Creates org tables if missing, seeds a Default org when empty, and adds
        organization_id to referees / gamedetails / mentor_game_selections.
        """
        try:
            default_org_id = self._ensureOrganizationsSeeded()
            default_org_id = self._pickBackfillOrganizationId(fallback=default_org_id)

            for table in ('referees', 'gamedetails', 'mentor_game_selections'):
                self._addOrganizationIdColumn(table, default_org_id)

            self._migrateUsersNameColumns()
            self._migrateUsersSettingsColumn()
            self._migrateMentorGameSelectionsFkToUsers()

            # Attach existing users to the default org when they have no memberships
            if self._tableExists('users') and self._tableExists('user_organizations'):
                self.executeSql(
                    """
                    INSERT INTO user_organizations (user_id, organization_id)
                    SELECT u.id, %s FROM users u
                    WHERE NOT EXISTS (
                        SELECT 1 FROM user_organizations uo WHERE uo.user_id = u.id
                    )
                    ON CONFLICT DO NOTHING
                    """,
                    (default_org_id,),
                )

            self.connection.commit()
            logging.info(
                "Multi-tenant schema migration complete (default_org_id=%s)",
                default_org_id,
            )
        except Exception as e:
            logging.error("Error migrating multi-tenant schema: %s", e, exc_info=True)
            try:
                self.connection.rollback()
            except Exception:
                pass

    def _mentorGameSelectionsFkReferencesUsers(self) -> bool:
        """True when mentor_game_selections.mentor_id already FKs to users."""
        if not self._tableExists('mentor_game_selections'):
            return True
        self.executeSql(
            """
            SELECT ccu.table_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name = 'mentor_game_selections'
              AND kcu.column_name = 'mentor_id'
            """
        )
        rows = self.cursor.fetchall()
        if not rows:
            return False
        return any((row[0] or '').lower() == 'users' for row in rows)

    def _migrateMentorGameSelectionsFkToUsers(self) -> None:
        """
        Point mentor_game_selections.mentor_id at users.id.

        Older schemas FKed mentor_id to the legacy mentors table, but findMentor()
        now returns users.id (multi-tenant mentors-as-users).
        """
        if not self._tableExists('mentor_game_selections') or not self._tableExists('users'):
            return
        if self._mentorGameSelectionsFkReferencesUsers():
            return

        logging.info("Migrating mentor_game_selections.mentor_id FK to users")

        # Drop FK first — remapping to users.id cannot succeed while FK still targets mentors
        self.executeSql(
            """
            SELECT tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name = 'mentor_game_selections'
              AND kcu.column_name = 'mentor_id'
            """
        )
        for (constraint_name,) in self.cursor.fetchall():
            logging.info("Dropping FK constraint %s on mentor_game_selections", constraint_name)
            self.executeSql(
                f'ALTER TABLE mentor_game_selections DROP CONSTRAINT IF EXISTS "{constraint_name}"'
            )

        # Remap any legacy mentors.id values to matching users by name
        if self._tableExists('mentors'):
            self.executeSql(
                """
                UPDATE mentor_game_selections AS mgs
                SET mentor_id = u.id
                FROM mentors AS m
                JOIN users AS u
                  ON LOWER(TRIM(u.first_name)) = LOWER(TRIM(m.mentor_first_name))
                 AND LOWER(TRIM(u.last_name)) = LOWER(TRIM(m.mentor_last_name))
                WHERE mgs.mentor_id = m.id
                """
            )

        # Drop rows that still don't resolve to a user (can't satisfy users FK)
        self.executeSql(
            """
            DELETE FROM mentor_game_selections mgs
            WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id = mgs.mentor_id)
            """
        )

        self.executeSql(
            """
            ALTER TABLE mentor_game_selections
            ADD CONSTRAINT mentor_game_selections_mentor_id_fkey
            FOREIGN KEY (mentor_id) REFERENCES users(id)
            """
        )
        logging.info("mentor_game_selections.mentor_id now references users(id)")


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
                                     first_name TEXT,
                                     last_name TEXT,
                                     settings JSONB NOT NULL DEFAULT '{}'::jsonb,
                                     avatar_jpeg BYTEA,
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
                                                      mentor_id INTEGER NOT NULL REFERENCES users(id),
                                                      game_date TEXT NOT NULL,
                                                      venue TEXT NOT NULL,
                                                      game_id TEXT NOT NULL,
                                                      organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                                                      selected_at TIMESTAMP NOT NULL DEFAULT NOW(),
                                                      UNIQUE(organization_id, mentor_id, game_date, venue, game_id))"""
        self.executeSql(sql)

    def _ensureOneMentorPerGameConstraint(self) -> None:
        """Keep one mentor per game (org + date + venue + game_id)."""
        if not self._tableExists('mentor_game_selections'):
            return
        if not self._columnExists('mentor_game_selections', 'organization_id'):
            return
        try:
            self.executeSql(
                """
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'mentor_game_selections'
                  AND indexname = 'mentor_game_selections_one_mentor_per_game'
                """
            )
            if self.cursor.fetchone():
                return
            self.executeSql(
                """
                DELETE FROM mentor_game_selections
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY organization_id, game_date, venue, game_id
                                   ORDER BY selected_at, id
                               ) AS rn
                        FROM mentor_game_selections
                    ) ranked
                    WHERE rn > 1
                )
                """
            )
            self.executeSql(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS mentor_game_selections_one_mentor_per_game
                ON mentor_game_selections (organization_id, game_date, venue, game_id)
                """
            )
        except Exception as e:
            logging.warning("Could not enforce one-mentor-per-game uniqueness: %s", e)


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


    def _removeRisky(self, mentee: str, organization_id: int = None):
        parts = mentee.strip().split(' ', 1)
        if len(parts) < 2:
            logging.warning(f"_removeRisky: could not parse mentee name '{mentee}'")
            return
        firstname, lastname = parts[0], parts[1]
        org_id = self._resolve_organization_id(organization_id)
        mentee_row = self.findReferee(lastname, firstname, org_id)
        if mentee_row is None:
            logging.warning(f"_removeRisky: referee not found for '{mentee}'")
            return
        self.executeSql("DELETE FROM risky WHERE mentee = %s", (mentee_row[0],))
        self.connection.commit()


    # finding stuff

    def isRisky(self, lastname: str, firstname: str, organization_id: int = None) -> bool:

        # get today's date and look into the risky table from today back one month
        # if the referee is in the risky table, return true

        range = self._getRiskRange()
        org_id = self._resolve_organization_id(organization_id)

        mentee = self.findReferee(lastname, firstname, org_id)
        if mentee is None:
            return False

        menteeId = mentee[0]

        sql = "SELECT * FROM risky WHERE mentee = %s and date between %s and %s"
        r = self.executeSql(sql, (menteeId, range[0], range[1]))

        return len(r.fetchall()) > 0


    def getRisky(self, organization_id: int = None) -> list:
        range = self._getRiskRange()
        org_id = self._resolve_organization_id(organization_id)

        sql = """SELECT lastname, firstname from referees r
                 where r.organization_id = %s
                 and r.id in (SELECT mentee from risky where date between %s and %s)"""
        r = self.executeSql(sql, (org_id, range[0], range[1]))
        return r.fetchall()


    def refExists(self, lastname: str, firstname: str, organization_id: int) -> bool:
        sql = "SELECT id from referees where lastname = %s and firstname = %s and organization_id = %s"
        r = self.executeSql(sql, (lastname.lower(), firstname.lower(), organization_id))
        return len(r.fetchall()) == 1


    def findReferee(self, lastname: str, firstname: str, organization_id: int = None) -> list:
        org_id = self._resolve_organization_id(organization_id)
        sql = "SELECT * from referees where lastname = %s and firstname = %s and organization_id = %s"
        r = self.executeSql(sql, (lastname.lower(), firstname.lower(), org_id))
        return r.fetchone()


    def getReferees(self, organization_id: int = None) -> list:
        # retrieve only the referees that have reports
        # return the list in sorted by last name order
        def lastname(item):
            return item[1]

        org_id = self._resolve_organization_id(organization_id)
        sql = """select distinct firstname, lastname from referees r
                 join mentor_sessions ms on ms.mentee = r.id
                 where r.organization_id = %s"""
        r = self.executeSql(sql, (org_id,))
        data = r.fetchall()
        return sorted(data, key=lastname)


    def getRefereesForSelectionBox(self, organization_id: int = None) -> list:
        refs = self.getReferees(organization_id)
        retVal = []
        for ref in refs:
            retVal.append(f'{ref[0].capitalize()} {ref[1].capitalize()}')
        return retVal


    def getMentorsForSelectionBox(self, organization_id: int = None) -> list:
        mentors = self.getMentors(organization_id)
        retVal = []
        for mentor in mentors:
            retVal.append(f'{mentor[0].capitalize()} {mentor[1].capitalize()}')
        return retVal


    def getNewReferees(self, organization_id: int = None) -> list:
        today = datetime.today()
        year = today.year
        org_id = self._resolve_organization_id(organization_id)
        sql = "SELECT firstname, lastname from referees where year_certified >= %s and organization_id = %s"
        r = self.executeSql(sql, (year, org_id))
        return r.fetchall()


    def mentorExists(self, firstname: str, lastname: str, organization_id: int = None) -> bool:
        org_id = self._resolve_organization_id(organization_id)
        sql = """SELECT u.id FROM users u
                 JOIN user_organizations uo ON u.id = uo.user_id
                 WHERE LOWER(u.last_name) = %s AND LOWER(u.first_name) = %s
                   AND uo.organization_id = %s"""
        r = self.executeSql(sql, (lastname.lower(), firstname.lower(), org_id))
        return len(r.fetchall()) == 1


    def findMentor(self, firstname: str, lastname: str, organization_id: int = None) -> list:
        """Mentors are application users (multi-tenant); id is users.id."""
        org_id = self._resolve_organization_id(organization_id)
        sql = """SELECT u.* FROM users u
                 JOIN user_organizations uo ON u.id = uo.user_id
                 WHERE LOWER(u.last_name) = %s AND LOWER(u.first_name) = %s
                   AND uo.organization_id = %s"""
        r = self.executeSql(sql, (lastname.lower(), firstname.lower(), org_id))
        return r.fetchone()


    def getMentors(self, organization_id: int = None) -> list:
        """Return mentor display names for users in the given organization."""
        org_id = self._resolve_organization_id(organization_id)
        sql = """SELECT u.first_name, u.last_name FROM users u
                 JOIN user_organizations uo ON u.id = uo.user_id
                 WHERE uo.organization_id = %s
                   AND COALESCE(TRIM(u.first_name), '') <> ''
                   AND COALESCE(TRIM(u.last_name), '') <> ''
                 ORDER BY u.last_name, u.first_name"""
        r = self.executeSql(sql, (org_id,))
        return r.fetchall()

    def _mentor_name_select_sql(self) -> str:
        """Mentor display columns for report queries (users and/or legacy mentors)."""
        if self._tableExists('mentors'):
            return (
                "COALESCE(me.last_name, m.mentor_last_name) AS mentor_last_name, "
                "COALESCE(me.first_name, m.mentor_first_name) AS mentor_first_name"
            )
        return "me.last_name AS mentor_last_name, me.first_name AS mentor_first_name"

    def _mentor_join_sql(self) -> str:
        """
        mentor_sessions.mentor historically referenced mentors.id; newer rows use users.id.
        Join both when the legacy table exists so reports resolve either id space.
        """
        if self._tableExists('mentors'):
            return (
                "LEFT JOIN mentors m ON ms.mentor = m.id "
                "LEFT JOIN users me ON ms.mentor = me.id"
            )
        return "LEFT JOIN users me ON ms.mentor = me.id"

    def _mentor_name_match_sql(self) -> str:
        if self._tableExists('mentors'):
            return (
                "LOWER(COALESCE(me.first_name, m.mentor_first_name)) = %s "
                "AND LOWER(COALESCE(me.last_name, m.mentor_last_name)) = %s"
            )
        return "LOWER(me.first_name) = %s AND LOWER(me.last_name) = %s"


    # def getMentoringSessions(self) -> dict:

    #     range = self._getSeasonRange()

    #     retVal = {}
    #     sql = f"select distinct r.lastname, r.firstname, ms.position, ms.date from mentor_sessions ms join referees r on ms.mentee = r.id where ms.date between '{range[0]}' and '{range[1]}'"
    #     r = self.executeSql(sql)
    #     rows = r.fetchall()
    #     for row in rows:
    #         retVal[f'{row[1]} {row[0]}'] = [ row[2], row[3]]
    #     return retVal


    def getMentoringSessionMetrics(self, year: int, season: str, organization_id: int = None) -> dict:
        '''
        season is either 'fall' or 'spring'
        returns number of referees mentored and number of mentoring sessions
        '''

        def getRanges(season: str, year: int) -> list:
            if season == 'fall':
                return [f'{year}-07-01', f'{year}-12-31']
            else:
                return [f'{year}-04-01', f'{year}-06-30']

        org_id = self._resolve_organization_id(organization_id)
        range = getRanges(season, year)
        sql = """
            SELECT
            COUNT(DISTINCT ms.mentor) AS distinct_mentors,
            COUNT(DISTINCT ms.mentee) AS distinct_referees,
            COUNT(DISTINCT ms.id) AS distinct_reports
            FROM mentor_sessions ms
            JOIN referees r ON ms.mentee = r.id
            WHERE ms.date BETWEEN %s AND %s AND r.organization_id = %s
        """
        r = self.executeSql(sql, (range[0], range[1], org_id))
        data =  r.fetchall()
        retVal = {
            'mentors': data[0][0],
            'referees': data[0][1],
            'reports': data[0][2]
        }
        return retVal


    def getMentoringSessions(self, organization_id: int = None) -> dict:

        org_id = self._resolve_organization_id(organization_id)
        retVal = {}
        sql = """select r.lastname, r.firstname, ms.position from mentor_sessions ms
                 join referees r on ms.mentee = r.id
                 where r.organization_id = %s"""
        r = self.executeSql(sql, (org_id,))
        rows = r.fetchall()
        for row in rows:
            key = f'{row[1]} {row[0]}'
            if key not in retVal:
                retVal[key] = []
            retVal[key].append(row[2])
        return retVal


    def getMentoringSessionDetails(self, year: int, organization_id: int = None) -> dict:

        org_id = self._resolve_organization_id(organization_id)
        range = [f'{year}-01-01', f'{year}-12-31']
        sql = f"""select r.firstname, r.lastname, ms.position, ms.date, ms.comments,
              {self._mentor_name_select_sql()},
              gd.gameid, gd.center, gd.ar1, gd.ar2, gd.date AS game_date, gd.venue, gd.time, gd.age, gd.level
              from mentor_sessions ms
              join referees r on ms.mentee = r.id
              {self._mentor_join_sql()}
              left join gamedetails gd on ms.gameid = gd.gameid and gd.organization_id = %s
              where ms.date between %s and %s and r.organization_id = %s ORDER BY ms.date"""
        r = self.executeSql(sql, (org_id, range[0], range[1], org_id))
        return r.fetchall()


    def getMentoringsessionsForWeek(self, week: str, organization_id: int = None) -> dict:
        org_id = self._resolve_organization_id(organization_id)
        # week string is like "Friday, April 14, 2023"
        d = datetime.strptime(week, "%A, %B %d, %Y")
        dt = d.strftime("%Y-%m-%d")
        sql = f"""select r.firstname, r.lastname, ms.position, ms.date, ms.comments,
              {self._mentor_name_select_sql()},
              gd.gameid, gd.center, gd.ar1, gd.ar2, gd.date AS game_date, gd.venue, gd.time, gd.age, gd.level
              from mentor_sessions ms
              join referees r on ms.mentee = r.id
              {self._mentor_join_sql()}
              left join gamedetails gd on ms.gameid = gd.gameid and gd.organization_id = %s
              where ms.date = %s and r.organization_id = %s"""
        r = self.executeSql(sql, (org_id, dt, org_id))
        return r.fetchall()


    def getMentoringsessionsForReferee(self, referee: str, organization_id: int = None) -> dict:
        org_id = self._resolve_organization_id(organization_id)
        # referee string is like "Kate Curby"
        firstname, lastname = referee.split(' ', 1)
        sql = f"""select r.firstname, r.lastname, ms.position, ms.date, ms.comments,
              {self._mentor_name_select_sql()},
              gd.gameid, gd.center, gd.ar1, gd.ar2, gd.date AS game_date, gd.venue, gd.time, gd.age, gd.level
              from mentor_sessions ms
              join referees r on ms.mentee = r.id
              {self._mentor_join_sql()}
              left join gamedetails gd on ms.gameid = gd.gameid and gd.organization_id = %s
              where r.firstname = %s and r.lastname = %s and r.organization_id = %s
              order by ms.date"""
        r = self.executeSql(sql, (org_id, firstname.lower(), lastname.lower(), org_id))
        return r.fetchall()


    def getMentoringsessionsForMentor(self, mentor: str, organization_id: int = None) -> dict:
        org_id = self._resolve_organization_id(organization_id)
        # mentor string is like "David Helfgott"
        firstname, lastname = mentor.split(' ', 1)
        sql = f"""select r.firstname, r.lastname, ms.position, ms.date, ms.comments,
              {self._mentor_name_select_sql()},
              gd.gameid, gd.center, gd.ar1, gd.ar2, gd.date AS game_date, gd.venue, gd.time, gd.age, gd.level
              from mentor_sessions ms
              join referees r on ms.mentee = r.id
              {self._mentor_join_sql()}
              left join gamedetails gd on ms.gameid = gd.gameid and gd.organization_id = %s
              where {self._mentor_name_match_sql()}
                and r.organization_id = %s
              order by ms.date"""
        r = self.executeSql(
            sql,
            (org_id, firstname.lower(), lastname.lower(), org_id),
        )
        return r.fetchall()

    def getYears(self, organization_id: int = None) -> list:
        org_id = self._resolve_organization_id(organization_id)
        retVal = []
        sql = """SELECT DISTINCT ms.date from mentor_sessions ms
                 join referees r on ms.mentee = r.id
                 where r.organization_id = %s"""
        r = self.executeSql(sql, (org_id,))
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


    def addReferee(self, lastname: str, firstname: str, year: int, organization_id: int):
        sql = "INSERT INTO referees (lastname, firstname, year_certified, organization_id) \
               VALUES (%s, %s, %s, %s)"
        self.executeSql(sql, (lastname, firstname, year, organization_id))
        self.connection.commit()


    def addMentor(self, firstname: str, lastname: str) -> None:
        raise NotImplementedError(
            "Mentors are application users now; create a user account instead of inserting into mentors"
        )


    def addMentorSession(self,
                         mentor: str,
                         mentee: str,
                         position: str,
                         date: str,
                         comments: str,
                         gameid: str,
                         organization_id: int = None) -> Tuple[bool, str]:
        org_id = self._resolve_organization_id(organization_id)
        logging.info(f'Adding mentor session for *{mentee}* from *{mentor}* with no risky set')
        sql = 'INSERT INTO mentor_sessions (mentor, mentee, position, date, comments, gameid) \
               VALUES (%s, %s, %s, %s, %s, %s)'
        f, l = mentee.split(' ', 1)
        logging.info(f"Referee first name: {f}, last name: {l}")
        mentorId = self.findMentor(mentor.split(' ')[0], mentor.split(' ')[1], org_id)
        menteeId = self.findReferee(l, f, org_id)
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
                            gameid: str,
                            organization_id: int = None) -> Tuple[bool, str]:


        org_id = self._resolve_organization_id(organization_id)
        logging.info(f'Adding mentor session new for *{mentee}* from *{mentor}* with risky: {isRisky}')
        if not isRisky:
            logging.info(f'Removing risky for {mentee}')
            self._removeRisky(mentee, org_id)
            return self.addMentorSession(mentor, mentee, position, date, comments, gameid, org_id)

        logging.info(f'Adding mentor session for *{mentee}* from *{mentor}* with risky: {isRisky}')
        sql = 'INSERT INTO mentor_sessions (mentor, mentee, position, date, comments, gameid) \
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id'
        f, l = mentee.split(' ', 1)
        logging.info(f"Referee first name: {f}, last name: {l}")
        mentorId = self.findMentor(mentor.split(' ')[0], mentor.split(' ')[1], org_id)
        menteeId = self.findReferee(l, f, org_id)
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
        """Backward-compatible text report from raw DB tuples."""
        return text_from_session_rows(rows_from_db_tuples(sessions))

    def sessions_to_rows(self, sessions) -> List[MentoringSessionRow]:
        """Convert raw mentoring-session query tuples into structured rows."""
        return rows_from_db_tuples(sessions)

    def getYearReportRows(self, year, organization_id: int = None) -> List[MentoringSessionRow]:
        return self.sessions_to_rows(self.getMentoringSessionDetails(year, organization_id))

    def getWeekReportRows(self, week, organization_id: int = None) -> List[MentoringSessionRow]:
        return self.sessions_to_rows(self.getMentoringsessionsForWeek(week, organization_id))

    def getRefereeReportRows(self, referee, organization_id: int = None) -> List[MentoringSessionRow]:
        return self.sessions_to_rows(self.getMentoringsessionsForReferee(referee, organization_id))

    def getMentorReportRows(self, mentor, organization_id: int = None) -> List[MentoringSessionRow]:
        return self.sessions_to_rows(self.getMentoringsessionsForMentor(mentor, organization_id))

    def produceYearReport(self, year, organization_id: int = None):
        return text_from_session_rows(self.getYearReportRows(year, organization_id))

    def produceWeekReport(self, week, organization_id: int = None):
        return text_from_session_rows(self.getWeekReportRows(week, organization_id))

    def produceRefereeReport(self, referee, organization_id: int = None):
        return text_from_session_rows(self.getRefereeReportRows(referee, organization_id))

    def produceMentorReport(self, mentor, organization_id: int = None):
        return text_from_session_rows(self.getMentorReportRows(mentor, organization_id))


    # The below was added so we can also track the game details

    def gameDetailsExist(self, gameId: str, date: str, time: str, organization_id: int) -> bool:
        sql = "SELECT * from gamedetails where gameId = %s and date = %s and time = %s and organization_id = %s"
        try:
            self.executeSql(sql, (gameId, date, time, organization_id))
        except Exception as ex:
            print(ex)
        return not self.cursor.fetchone() == None


    def addGameDetails(self, currentGames: dict, organization_id: int) -> None:

        sql = """insert into gamedetails (venue,
                                    gameId,
                                    center,
                                    ar1,
                                    ar2,
                                    date,
                                    time,
                                    age,
                                    level,
                                    organization_id)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""

        for venue, gameDetails in currentGames.items():
            for gameid, game in gameDetails.items():
                if 'VENUE CONFLICT' in gameid:
                    gameid = gameid.replace('VENUE CONFLICT', '')
                if self.gameDetailsExist(gameid, game['date'], game['gameTime'], organization_id) is False:
                    self.executeSql(sql, (venue,
                                            gameid,
                                            game['Center'],
                                            game['AR1'],
                                            game['AR2'],
                                            game['date'],
                                            game['gameTime'],
                                            game['age'],
                                            game['level'],
                                            organization_id))


    def getDefaultOrganizationId(self) -> int:
        """Resolve the default organization for background jobs / single-org flows.

        Preference order:
        1. ORGANIZATION_ID env var
        2. org with slug 'default' or name 'Default'
        3. first organization by name
        """
        env_org = os.environ.get('ORGANIZATION_ID')
        if env_org:
            return int(env_org)

        orgs = self.getOrganizations()
        if not orgs:
            raise RuntimeError("No organizations found; create one before adding referees/games")

        default_org = next(
            (o for o in orgs if (o.get('slug') == 'default' or o.get('name') == 'Default')),
            None,
        )
        return default_org['id'] if default_org else orgs[0]['id']

    def _resolve_organization_id(self, organization_id: int = None) -> int:
        """Use explicit org when provided; otherwise default org (session / env / first org)."""
        if organization_id is not None:
            return organization_id
        return self.getDefaultOrganizationId()

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


    def createUser(
        self,
        username: str,
        password_hash: str,
        salt: str,
        email: str,
        role: str = 'user',
        first_name: str = None,
        last_name: str = None,
    ) -> None:
        """Create a new user"""
        first = (first_name or '').strip().lower()
        last = (last_name or '').strip().lower()
        sql = """INSERT INTO users (username, password_hash, salt, email, role, first_name, last_name)
                 VALUES (%s, %s, %s, %s, %s, %s, %s)"""
        self.executeSql(
            sql,
            (username.lower(), password_hash, salt, email.lower(), role, first, last),
        )
        self.connection.commit()


    def getUserByUsername(self, username: str) -> dict:
        """Get user by username"""
        sql = (
            "SELECT id, username, password_hash, salt, email, role, created_at, last_login, settings "
            "FROM users WHERE username = %s"
        )
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
                'last_login': row[7],
                'settings': _parse_user_settings(row[8] if len(row) > 8 else None),
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

    def getUsersByOrganization(self, organization_id: int) -> list:
        """Get users belonging to a specific organization."""
        sql = """SELECT u.id, u.username, u.email, u.role, u.created_at, u.last_login
                 FROM users u
                 JOIN user_organizations uo ON u.id = uo.user_id
                 WHERE uo.organization_id = %s
                 ORDER BY u.username"""
        self.executeSql(sql, (organization_id,))
        rows = self.cursor.fetchall()
        return [
            {
                'id': row[0],
                'username': row[1],
                'email': row[2],
                'role': row[3],
                'created_at': row[4],
                'last_login': row[5],
            }
            for row in rows
        ]

    def getUsersLastLoginByOrganization(self, organization_id: int) -> list:
        """Get users in an organization with their most recent login time."""
        sql = """SELECT u.username, u.email, u.role, u.last_login
                 FROM users u
                 JOIN user_organizations uo ON u.id = uo.user_id
                 WHERE uo.organization_id = %s
                 ORDER BY u.last_login DESC NULLS LAST, u.username"""
        self.executeSql(sql, (organization_id,))
        rows = self.cursor.fetchall()
        return [
            {
                'username': row[0],
                'email': row[1],
                'role': row[2],
                'last_login': row[3],
            }
            for row in rows
        ]

    def getRecentLoginsByOrganization(self, organization_id: int, limit: int = 100) -> list:
        """Get recent login events for users in an organization."""
        sql = """SELECT uv.username, uv.email, uv.role, uv.date, uv.ip_address
                 FROM user_visits uv
                 JOIN users u ON LOWER(u.username) = LOWER(uv.username)
                 JOIN user_organizations uo ON u.id = uo.user_id
                 WHERE uo.organization_id = %s
                 ORDER BY uv.date DESC
                 LIMIT %s"""
        self.executeSql(sql, (organization_id, limit))
        rows = self.cursor.fetchall()
        return [
            {
                'username': row[0],
                'email': row[1],
                'role': row[2],
                'login_time': row[3],
                'ip_address': row[4] or '',
            }
            for row in rows
        ]

    def getOrganizations(self) -> list:
        """Get all organizations for multi-tenant login"""
        sql = "SELECT id, name, slug FROM organizations ORDER BY name"
        self.executeSql(sql)
        rows = self.cursor.fetchall()
        return [{'id': row[0], 'name': row[1], 'slug': row[2] or ''} for row in rows]

    def getOrganizationById(self, organization_id: int) -> Optional[dict]:
        sql = "SELECT id, name, slug FROM organizations WHERE id = %s"
        self.executeSql(sql, (organization_id,))
        row = self.cursor.fetchone()
        if not row:
            return None
        return {'id': row[0], 'name': row[1], 'slug': row[2] or ''}

    def _slugify_organization_name(self, name: str) -> str:
        slug = re.sub(r'[^a-z0-9]+', '-', name.lower().strip()).strip('-')
        return slug or 'org'

    def organizationNameExists(self, name: str) -> bool:
        sql = "SELECT 1 FROM organizations WHERE LOWER(name) = LOWER(%s)"
        self.executeSql(sql, (name.strip(),))
        return self.cursor.fetchone() is not None

    def getOrganizationDependencyCounts(self, organization_id: int) -> dict:
        """Return row counts for data tied to an organization (for safe delete checks)."""
        queries = {
            'users': "SELECT COUNT(*) FROM user_organizations WHERE organization_id = %s",
            'referees': "SELECT COUNT(*) FROM referees WHERE organization_id = %s",
            'gamedetails': "SELECT COUNT(*) FROM gamedetails WHERE organization_id = %s",
            'game_selections': "SELECT COUNT(*) FROM mentor_game_selections WHERE organization_id = %s",
        }
        counts = {}
        for key, sql in queries.items():
            try:
                self.executeSql(sql, (organization_id,))
                counts[key] = self.cursor.fetchone()[0]
            except Exception:
                counts[key] = 0
        return counts

    def createOrganization(self, name: str, slug: str = None) -> Tuple[bool, str]:
        name = name.strip()
        if not name:
            return (False, 'Organization name is required')

        slug_value = (slug or '').strip() or self._slugify_organization_name(name)

        try:
            sql = "INSERT INTO organizations (name, slug) VALUES (%s, %s) RETURNING id"
            self.executeSql(sql, (name, slug_value))
            self.connection.commit()
            return (True, f"Organization '{name}' created")
        except Exception as ex:
            self.connection.rollback()
            if 'unique' in str(ex).lower() or 'duplicate' in str(ex).lower():
                return (False, 'An organization with that name already exists')
            return (False, f'Failed to create organization: {ex}')

    def deleteOrganization(self, organization_id: int) -> Tuple[bool, str]:
        org = self.getOrganizationById(organization_id)
        if not org:
            return (False, 'Organization not found')

        counts = self.getOrganizationDependencyCounts(organization_id)
        blocking = []
        if counts.get('referees', 0) > 0:
            blocking.append(f"{counts['referees']} referee(s)")
        if counts.get('gamedetails', 0) > 0:
            blocking.append(f"{counts['gamedetails']} game detail(s)")
        if blocking:
            return (
                False,
                f"Cannot delete '{org['name']}': still has {', '.join(blocking)}. "
                "Remove or reassign that data first.",
            )

        try:
            # Explicit cleanup — production DB may lack ON DELETE CASCADE on these FKs
            self.executeSql(
                "DELETE FROM mentor_game_selections WHERE organization_id = %s",
                (organization_id,),
            )
            self.executeSql(
                "DELETE FROM user_organizations WHERE organization_id = %s",
                (organization_id,),
            )
            sql = "DELETE FROM organizations WHERE id = %s"
            self.executeSql(sql, (organization_id,))
            self.connection.commit()
            if self.cursor.rowcount == 0:
                return (False, 'Organization not found')
            return (True, f"Organization '{org['name']}' deleted")
        except Exception as ex:
            self.connection.rollback()
            return (False, f'Failed to delete organization: {ex}')

    def getOrganizationIdsForUser(self, user_id: int) -> list:
        """Return organization ids the user belongs to"""
        sql = "SELECT organization_id FROM user_organizations WHERE user_id = %s"
        self.executeSql(sql, (user_id,))
        return [row[0] for row in self.cursor.fetchall()]

    def getOrganizationsForUser(self, user_id: int) -> list:
        """Return organization records the user belongs to."""
        sql = """SELECT o.id, o.name, o.slug
                 FROM organizations o
                 JOIN user_organizations uo ON o.id = uo.organization_id
                 WHERE uo.user_id = %s
                 ORDER BY o.name"""
        self.executeSql(sql, (user_id,))
        return [{'id': row[0], 'name': row[1], 'slug': row[2] or ''} for row in self.cursor.fetchall()]

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

    def removeUserFromOrganization(self, user_id: int, organization_id: int) -> Tuple[bool, str]:
        """Remove a user from an organization. Returns (success, message)."""
        if not self.userBelongsToOrganization(user_id, organization_id):
            return (False, 'User is not a member of that organization')

        org_ids = self.getOrganizationIdsForUser(user_id)
        if len(org_ids) <= 1:
            return (False, 'Cannot remove user from their only organization. Add them to another org first, or delete the user.')

        try:
            sql = "DELETE FROM user_organizations WHERE user_id = %s AND organization_id = %s"
            self.executeSql(sql, (user_id, organization_id))
            self.connection.commit()
            return (True, 'User removed from organization')
        except Exception as ex:
            self.connection.rollback()
            return (False, f'Failed to remove user from organization: {ex}')

    def updateUserRole(self, user_id: int, role: str) -> Tuple[bool, str]:
        if role not in ('user', 'admin'):
            return (False, 'Role must be user or admin')
        try:
            sql = "UPDATE users SET role = %s WHERE id = %s"
            self.executeSql(sql, (role, user_id))
            self.connection.commit()
            if self.cursor.rowcount == 0:
                return (False, 'User not found')
            return (True, 'Role updated')
        except Exception as ex:
            self.connection.rollback()
            return (False, f'Failed to update role: {ex}')

    def getUserById(self, user_id: int) -> Optional[dict]:
        sql = "SELECT id, username, email, role, created_at, last_login FROM users WHERE id = %s"
        self.executeSql(sql, (user_id,))
        row = self.cursor.fetchone()
        if not row:
            return None
        return {
            'id': row[0],
            'username': row[1],
            'email': row[2],
            'role': row[3],
            'created_at': row[4],
            'last_login': row[5],
        }

    def getUserSettings(self, user_id: int) -> dict:
        sql = "SELECT settings FROM users WHERE id = %s"
        self.executeSql(sql, (user_id,))
        row = self.cursor.fetchone()
        if not row:
            return {}
        return _parse_user_settings(row[0])

    def userHasAvatar(self, user_id: int) -> bool:
        sql = "SELECT avatar_jpeg IS NOT NULL FROM users WHERE id = %s"
        self.executeSql(sql, (user_id,))
        row = self.cursor.fetchone()
        return bool(row and row[0])

    def getUserAvatar(self, user_id: int) -> Optional[bytes]:
        sql = "SELECT avatar_jpeg FROM users WHERE id = %s"
        self.executeSql(sql, (user_id,))
        row = self.cursor.fetchone()
        if not row or row[0] is None:
            return None
        return bytes(row[0])

    def setUserAvatar(self, user_id: int, jpeg_bytes: bytes) -> None:
        sql = "UPDATE users SET avatar_jpeg = %s WHERE id = %s"
        self.executeSql(sql, (jpeg_bytes, user_id))
        self.connection.commit()

    def deleteUserAvatar(self, user_id: int) -> None:
        sql = "UPDATE users SET avatar_jpeg = NULL WHERE id = %s"
        self.executeSql(sql, (user_id,))
        self.connection.commit()

    def updateUserSetting(self, user_id: int, key: str, value: Any) -> None:
        """Merge one key into users.settings (JSONB)."""
        patch = json.dumps({key: value})
        sql = """
            UPDATE users
            SET settings = COALESCE(settings, '{}'::jsonb) || %s::jsonb
            WHERE id = %s
        """
        self.executeSql(sql, (patch, user_id))
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


    def deleteUser(self, user_id: int) -> Tuple[bool, str]:
        """Delete a user and cascaded memberships. Blocks if other FKs prevent it."""
        user = self.getUserById(user_id)
        if not user:
            return (False, 'User not found')
        try:
            sql = "DELETE FROM users WHERE id = %s"
            self.executeSql(sql, (user_id,))
            self.connection.commit()
            return (True, f"User '{user['username']}' deleted")
        except Exception as ex:
            self.connection.rollback()
            err = str(ex).lower()
            if 'foreign key' in err or 'violates' in err:
                return (
                    False,
                    f"Cannot delete '{user['username']}': still referenced by other records "
                    "(e.g. mentor sessions or game selections). Remove those first, or just remove org membership.",
                )
            return (False, f'Failed to delete user: {ex}')


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

    def _takenByOtherMentors(self, mentor_firstname: str, mentor_lastname: str, game_date: str,
                               venue: str, game_id: str, organization_id: int) -> list:
        this_name = f"{mentor_firstname} {mentor_lastname}".lower()
        existing = self.getGameSelectionsByGame(game_date, venue, game_id, organization_id)
        return [name for name in existing if name.lower() != this_name]

    def addMentorGameSelection(self, mentor_firstname: str, mentor_lastname: str, game_date: str,
                               venue: str, game_id: str, organization_id: int = None) -> Tuple[bool, str]:
        """Add a mentor game selection. Returns (success, message)"""
        try:
            org_id = self._resolve_organization_id(organization_id)
            mentor = self.findMentor(mentor_firstname.lower(), mentor_lastname.lower(), org_id)
            if not mentor:
                return (False, f'Mentor not found: {mentor_firstname} {mentor_lastname}')

            taken_by = self._takenByOtherMentors(
                mentor_firstname, mentor_lastname, game_date, venue, game_id, org_id
            )
            if taken_by:
                return (False, f'This game is already taken by {", ".join(taken_by)}')

            sql = """INSERT INTO mentor_game_selections (mentor_id, game_date, venue, game_id, organization_id)
                     VALUES (%s, %s, %s, %s, %s)"""
            self.executeSql(sql, (mentor[0], game_date, venue, game_id, org_id))
            self.connection.commit()
            return (True, "Game selection added successfully")
        except Exception as ex:
            if 'duplicate key' in str(ex).lower() or 'unique constraint' in str(ex).lower():
                org_id = self._resolve_organization_id(organization_id)
                taken_by = self._takenByOtherMentors(
                    mentor_firstname, mentor_lastname, game_date, venue, game_id, org_id
                )
                if taken_by:
                    return (False, f'This game is already taken by {", ".join(taken_by)}')
                return (False, "Game already selected by this mentor")
            return (False, f'Failed to add game selection: {ex}')

    def removeMentorGameSelection(self, mentor_firstname: str, mentor_lastname: str, game_date: str,
                                  venue: str, game_id: str, organization_id: int = None) -> Tuple[bool, str]:
        """Remove a mentor game selection. Returns (success, message)"""
        try:
            org_id = self._resolve_organization_id(organization_id)
            mentor = self.findMentor(mentor_firstname.lower(), mentor_lastname.lower(), org_id)
            if not mentor:
                return (False, f'Mentor not found: {mentor_firstname} {mentor_lastname}')

            sql = """DELETE FROM mentor_game_selections
                     WHERE mentor_id = %s AND game_date = %s AND venue = %s AND game_id = %s
                       AND organization_id = %s"""
            self.executeSql(sql, (mentor[0], game_date, venue, game_id, org_id))
            self.connection.commit()
            if self.cursor.rowcount == 0:
                return (False, "Game selection not found")
            return (True, "Game selection removed successfully")
        except Exception as ex:
            return (False, f'Failed to remove game selection: {ex}')

    def getMentorGameSelections(self, game_date: str = None, organization_id: int = None) -> list:
        """Get mentor game selections, optionally filtered by date"""
        org_id = self._resolve_organization_id(organization_id)
        if game_date:
            sql = """SELECT u.first_name, u.last_name, mgs.game_date, mgs.venue, mgs.game_id, mgs.selected_at
                     FROM mentor_game_selections mgs
                     JOIN users u ON mgs.mentor_id = u.id
                     WHERE mgs.organization_id = %s AND mgs.game_date = %s
                     ORDER BY mgs.selected_at"""
            self.executeSql(sql, (org_id, game_date))
        else:
            sql = """SELECT u.first_name, u.last_name, mgs.game_date, mgs.venue, mgs.game_id, mgs.selected_at
                     FROM mentor_game_selections mgs
                     JOIN users u ON mgs.mentor_id = u.id
                     WHERE mgs.organization_id = %s
                     ORDER BY mgs.game_date, mgs.selected_at"""
            self.executeSql(sql, (org_id,))

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
                               venue: str, game_id: str, organization_id: int = None) -> bool:
        """Check if a specific game is selected by a mentor"""
        try:
            org_id = self._resolve_organization_id(organization_id)
            mentor = self.findMentor(mentor_firstname.lower(), mentor_lastname.lower(), org_id)
            if not mentor:
                return False

            sql = """SELECT COUNT(*) FROM mentor_game_selections
                     WHERE mentor_id = %s AND game_date = %s AND venue = %s AND game_id = %s
                       AND organization_id = %s"""
            self.executeSql(sql, (mentor[0], game_date, venue, game_id, org_id))
            return self.cursor.fetchone()[0] > 0
        except Exception as ex:
            return False

    def getGameSelectionsByGame(self, game_date: str, venue: str, game_id: str,
                                organization_id: int = None) -> list:
        """Get all mentors who have selected a specific game"""
        org_id = self._resolve_organization_id(organization_id)
        sql = """SELECT u.first_name, u.last_name
                 FROM mentor_game_selections mgs
                 JOIN users u ON mgs.mentor_id = u.id
                 WHERE mgs.game_date = %s AND mgs.venue = %s AND mgs.game_id = %s
                   AND mgs.organization_id = %s
                 ORDER BY mgs.selected_at"""
        self.executeSql(sql, (game_date, venue, game_id, org_id))
        rows = self.cursor.fetchall()
        return [f"{row[0].capitalize()} {row[1].capitalize()}" for row in rows]


