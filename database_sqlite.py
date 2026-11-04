"""SQLite backend for Referee Mentor.

RefereeDbSqlite subclasses RefereeDbCockroach so query methods stay in one place.
It does not change the Cockroach class; it only replaces connection, DDL, and a
few Postgres-only operations (JSONB merge, catalog tables, ALTER COLUMN).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any, Optional

from database import RefereeDbCockroach, sql_identifier

logger = logging.getLogger(__name__)

_NOW_UTC = "(NOW() AT TIME ZONE 'UTC')::TIMESTAMP"


def demo_mode() -> bool:
    """True on the public demo app, where visitors share the demo/demo login."""
    return (os.environ.get('DEMO_MODE') or '').strip().lower() in {'1', 'true', 'yes', 'on'}


DEMO_SESSION_DB_KEY = 'demo_db_path'
DEMO_SESSION_MAX_AGE_SECONDS = 10 * 60 * 60
DEMO_SESSION_SWEEP_INTERVAL_SECONDS = 60 * 60
_SESSION_DB_NAME = re.compile(r'^refmentor-[0-9a-f]{32}\.sqlite$')
_schema_ready_paths: set[str] = set()
_schema_ready_lock = threading.Lock()
_sweeper_started = False
_sweeper_lock = threading.Lock()


class DemoSessionExpired(Exception):
    """The visitor's demo database was removed while they were still signed in."""


def restore_sqlite_baseline(baseline: Path, target: Path) -> None:
    """Replace target with baseline and drop WAL/SHM sidecars so old writes are not replayed."""
    baseline = Path(baseline)
    target = Path(target)
    if not baseline.is_file():
        raise FileNotFoundError(baseline)
    if baseline.resolve() == target.resolve():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    for sidecar_name in (f'{target.name}-wal', f'{target.name}-shm'):
        sidecar = target.parent / sidecar_name
        if sidecar.exists():
            sidecar.unlink()
    temporary = target.with_name(f'{target.name}.restore')
    shutil.copyfile(baseline, temporary)
    os.replace(temporary, target)


def demo_golden_path() -> Path:
    """Packaged baseline. Never open this file; copy it."""
    configured = (os.environ.get('DEMO_BASELINE_PATH') or '').strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / 'demo' / 'refmentor.sqlite'


def demo_auth_db_path() -> Path:
    """Stable copy used for login and password checks."""
    return Path(sqlite_db_path()).parent / 'refmentor-auth.sqlite'


def prepare_demo_auth_database() -> bool:
    """Refresh the auth database from the golden file. The golden file stays closed."""
    if not demo_mode():
        return False
    baseline = demo_golden_path()
    target = demo_auth_db_path()
    if not baseline.is_file():
        logger.warning(
            "Demo baseline not found at %s; leaving the auth database in place",
            baseline,
        )
        return False
    restore_sqlite_baseline(baseline, target)
    logger.info("Prepared demo auth database from %s to %s", baseline, target)
    return True


def restore_demo_baseline_if_enabled() -> bool:
    """On demo startup, refresh the auth copy from the golden file."""
    return prepare_demo_auth_database()


def provision_demo_session_database() -> str:
    """Copy the golden file to a new per-login database and return its path."""
    session_id = uuid.uuid4().hex
    target = Path(sqlite_db_path()).parent / f'refmentor-{session_id}.sqlite'
    restore_sqlite_baseline(demo_golden_path(), target)
    logger.info("Provisioned demo session database %s", target)
    return str(target)


def delete_sqlite_file(path: Path) -> None:
    """Remove a SQLite file and the WAL/SHM sidecars beside it."""
    target = Path(path)
    for sidecar in (target, Path(f'{target}-wal'), Path(f'{target}-shm')):
        try:
            sidecar.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove %s", sidecar, exc_info=True)


def file_created_at(path: Path) -> float:
    """Birth time when the filesystem has one, otherwise the inode change time."""
    stat = path.stat()
    birth = getattr(stat, 'st_birthtime', None)
    if birth:
        return float(birth)
    return float(stat.st_ctime)


def sweep_abandoned_demo_databases(
    max_age_seconds: float = DEMO_SESSION_MAX_AGE_SECONDS,
    now: Optional[float] = None,
) -> int:
    """Delete per-login demo databases created more than max_age_seconds ago."""
    if not demo_mode():
        return 0
    clock = time.time() if now is None else now
    directory = Path(sqlite_db_path()).parent
    if not directory.is_dir():
        return 0
    removed = 0
    for path in directory.glob('refmentor-*.sqlite'):
        if not _SESSION_DB_NAME.match(path.name):
            continue
        try:
            age = clock - file_created_at(path)
        except OSError:
            logger.warning("Could not stat %s", path, exc_info=True)
            continue
        if age < max_age_seconds:
            continue
        logger.info("Removing abandoned demo database %s (age %.0f seconds)", path, age)
        delete_sqlite_file(path)
        removed += 1
    return removed


def start_demo_session_sweeper() -> None:
    """Sweep once now, then hourly, inside this process."""
    global _sweeper_started
    if not demo_mode():
        return
    with _sweeper_lock:
        if _sweeper_started:
            return
        _sweeper_started = True
    sweep_abandoned_demo_databases()

    def loop() -> None:
        while True:
            time.sleep(DEMO_SESSION_SWEEP_INTERVAL_SECONDS)
            try:
                sweep_abandoned_demo_databases()
            except Exception:
                logger.exception("Demo session cleanup failed")

    threading.Thread(target=loop, name='demo-session-cleanup', daemon=True).start()


def _stored_demo_db_path() -> Optional[str]:
    try:
        from nicegui import app
        path = app.storage.user.get(DEMO_SESSION_DB_KEY)
    except Exception:
        return None
    if not path:
        return None
    return str(path)


def expire_demo_session() -> None:
    """Clear the signed-in demo visitor and send them back to the login screen."""
    logger.info("Demo session database is gone; returning to login")
    try:
        from nicegui import app, ui
        try:
            app.storage.user.clear()
        except Exception:
            logger.debug("Could not clear demo session storage", exc_info=True)
        ui.navigate.to('/login?demo_timeout=1')
    except Exception:
        logger.exception("Could not end expired demo session")
    raise DemoSessionExpired()


def session_demo_db_path() -> Optional[str]:
    """Path stored for this browser session, when this request has one."""
    if not demo_mode():
        return None
    path = _stored_demo_db_path()
    if not path:
        return None
    if Path(path).is_file():
        return path
    logger.warning("Demo session database missing at %s", path)
    expire_demo_session()
    return None


def active_sqlite_path() -> str:
    """Session copy for a logged-in demo visitor, otherwise the auth copy or SQLITE_PATH."""
    session_path = session_demo_db_path()
    if session_path:
        return session_path
    if demo_mode():
        return str(demo_auth_db_path())
    return sqlite_db_path()


def sqlite_db_path() -> str:
    """Resolve the SQLite file path from env (db_url, SQLITE_PATH, or DATA_CACHE_DIR)."""
    url = (os.environ.get('db_url') or os.environ.get('DATABASE_URL') or '').strip()
    if url.startswith('sqlite:///'):
        return url[len('sqlite:///'):]
    configured = (os.environ.get('SQLITE_PATH') or '').strip()
    if configured:
        return configured
    cache_dir = (os.environ.get('DATA_CACHE_DIR') or '').strip()
    if cache_dir:
        return str(Path(cache_dir) / 'refmentor.sqlite')
    return str(Path(__file__).resolve().parent / '.data' / 'refmentor.sqlite')


def to_sqlite_sql(sql: str) -> str:
    """Translate the Postgres-shaped SQL used by RefereeDbCockroach into SQLite."""
    translated = sql.replace(_NOW_UTC, "datetime('now')")
    translated = translated.replace('NOW()', "datetime('now')")
    translated = translated.replace("'{}'::jsonb", "'{}'")
    translated = translated.replace('::jsonb', '')
    translated = translated.replace('::TIMESTAMP', '')
    translated = re.sub(r'\bTRUE\b', '1', translated)
    translated = re.sub(r'\bFALSE\b', '0', translated)
    translated = translated.replace('%s', '?')
    return translated


def _adapt_datetime(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.strftime('%Y-%m-%d %H:%M:%S')


def _adapt_date(value: date) -> str:
    return value.isoformat()


def _adapt_time(value: dt_time) -> str:
    return value.strftime('%H:%M:%S')


def _convert_timestamp(raw: bytes) -> datetime:
    text = raw.decode('utf-8').replace('T', ' ')[:19]
    return datetime.strptime(text, '%Y-%m-%d %H:%M:%S')


def _convert_date(raw: bytes) -> date:
    return datetime.strptime(raw.decode('utf-8')[:10], '%Y-%m-%d').date()


def _convert_time(raw: bytes) -> dt_time:
    parts = raw.decode('utf-8').split(':')
    return dt_time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)


sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_adapter(date, _adapt_date)
sqlite3.register_adapter(dt_time, _adapt_time)
sqlite3.register_converter('TIMESTAMP', _convert_timestamp)
sqlite3.register_converter('TIMESTAMPTZ', _convert_timestamp)
sqlite3.register_converter('DATE', _convert_date)
sqlite3.register_converter('TIME', _convert_time)


class RefereeDbSqlite(RefereeDbCockroach):
    """Same public API as RefereeDbCockroach, backed by a local SQLite file."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or sqlite_db_path()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connectToDb()
        with _schema_ready_lock:
            if self.db_path in _schema_ready_paths:
                return
            if not self._tableExists('referees'):
                self.createDb()
            else:
                self._ensureSqliteSchema()
            self._ensureOrganizationsSeeded()
            try:
                from avatars import import_legacy_file_avatars
                import_legacy_file_avatars(self)
            except Exception:
                logging.exception('Could not import legacy avatar files')
            self._ensureOneMentorPerGameConstraint()
            _schema_ready_paths.add(self.db_path)

    def _connectToDb(self):
        self.connection = sqlite3.connect(
            self.db_path,
            timeout=30,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,
        )
        self.connection.execute('PRAGMA foreign_keys = ON')
        self.connection.execute('PRAGMA journal_mode = WAL')
        self.connection.execute('PRAGMA busy_timeout = 30000')
        self.cursor = self.connection.cursor()

    def _executeSql(self, sql: str, params: Optional[Any] = None):
        converted = to_sqlite_sql(sql)
        if params is not None:
            return self.cursor.execute(converted, tuple(params))
        return self.cursor.execute(converted)

    def _tableExists(self, table_name: str) -> bool:
        self.cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return self.cursor.fetchone() is not None

    def _columnExists(self, table_name: str, column_name: str) -> bool:
        try:
            table_name = sql_identifier(table_name)
        except ValueError:
            return False
        self.cursor.execute(f'PRAGMA table_info({table_name})')
        return any(row[1] == column_name for row in self.cursor.fetchall())

    def _ensureSqliteSchema(self) -> None:
        """Add current tables/columns to an existing SQLite file. Skip PG ALTER TYPE."""
        creators = (
            ('organizations', self._createOrganizationsTable),
            ('users', self._createUsersTable),
            ('user_organizations', self._createUserOrganizationsTable),
            ('gamedetails', self._createNewGameDetailTable),
            ('user_visits', self._createUserVisitsTable),
            ('password_reset_tokens', self._createPasswordResetTokensTable),
            ('logs', self._createLogsTable),
            ('calendar_events', self._createCalendarEventsTable),
            ('mentor_game_selections', self._createMentorGameSelectionsTable),
        )
        for table_name, create in creators:
            if not self._tableExists(table_name):
                create()

        default_org_id = self._ensureOrganizationsSeeded()
        for table in ('referees', 'gamedetails', 'mentor_game_selections'):
            self._addOrganizationIdColumn(table, default_org_id)
        self._migrateUsersNameColumns()
        self._migrateUsersSettingsColumn()
        self._migrateUsersAvatarColumn()
        self._migrateUserVisitsTable()

    def _addOrganizationIdColumn(self, table_name: str, default_org_id: int) -> None:
        table_name = sql_identifier(table_name)
        if not self._tableExists(table_name):
            return
        if self._columnExists(table_name, 'organization_id'):
            self.executeSql(
                f"UPDATE {table_name} SET organization_id = %s WHERE organization_id IS NULL",
                (default_org_id,),
            )
            self.connection.commit()
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
        self.connection.commit()

    def _migrateUsersSettingsColumn(self) -> None:
        if not self._tableExists('users') or self._columnExists('users', 'settings'):
            return
        self.executeSql("ALTER TABLE users ADD COLUMN settings TEXT NOT NULL DEFAULT '{}'")
        logging.info("Added users.settings")

    def _migrateUsersAvatarColumn(self) -> None:
        if not self._tableExists('users') or self._columnExists('users', 'avatar_jpeg'):
            return
        self.executeSql("ALTER TABLE users ADD COLUMN avatar_jpeg BLOB")
        logging.info("Added users.avatar_jpeg")

    def _migrateUserVisitsTable(self) -> None:
        if not self._tableExists('user_visits'):
            return
        if not self._columnExists('user_visits', 'ip_address'):
            self.executeSql("ALTER TABLE user_visits ADD COLUMN ip_address TEXT")
        if not self._columnExists('user_visits', 'user_agent'):
            self.executeSql("ALTER TABLE user_visits ADD COLUMN user_agent TEXT")
        self.connection.commit()

    def _mentorGameSelectionsFkReferencesUsers(self) -> bool:
        if not self._tableExists('mentor_game_selections'):
            return True
        self.cursor.execute('PRAGMA foreign_key_list(mentor_game_selections)')
        rows = self.cursor.fetchall()
        if not rows:
            return False
        return any(
            (row[2] or '').lower() == 'users' and (row[3] or '').lower() == 'mentor_id'
            for row in rows
        )

    def _migrateMentorGameSelectionsFkToUsers(self) -> None:
        """SQLite cannot drop a FK without rebuilding the table; fresh files already point at users."""
        if self._mentorGameSelectionsFkReferencesUsers():
            return
        logging.warning(
            "mentor_game_selections.mentor_id does not reference users; "
            "SQLite will not rebuild the table automatically"
        )

    def _ensureOneMentorPerGameConstraint(self) -> None:
        if not self._tableExists('mentor_game_selections'):
            return
        if not self._columnExists('mentor_game_selections', 'organization_id'):
            return
        try:
            self.cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' "
                "AND name='mentor_game_selections_one_mentor_per_game'"
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

    def createDb(self) -> bool:
        self._createOrganizationsTable()
        self._createUsersTable()
        self._createUserOrganizationsTable()
        self.executeSql(
            """CREATE TABLE referees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lastname TEXT NOT NULL,
                firstname TEXT NOT NULL,
                year_certified INTEGER,
                organization_id INTEGER NOT NULL REFERENCES organizations(id)
            )"""
        )
        self.executeSql(
            """CREATE TABLE mentors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mentor_last_name TEXT NOT NULL,
                mentor_first_name TEXT NOT NULL
            )"""
        )
        self.executeSql(
            """CREATE TABLE mentor_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mentor INTEGER NOT NULL,
                mentee INTEGER NOT NULL,
                position TEXT NOT NULL,
                date TIMESTAMP NOT NULL,
                comments TEXT NOT NULL,
                gameid TEXT
            )"""
        )
        self.executeSql(
            """CREATE TABLE risky (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mentee INTEGER NOT NULL,
                mentor_session INTEGER NOT NULL,
                date TIMESTAMP NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        self._createNewGameDetailTable()
        self._createUserVisitsTable()
        self._createPasswordResetTokensTable()
        self._createLogsTable()
        self._createCalendarEventsTable()
        self._createMentorGameSelectionsTable()
        self.connection.commit()
        return True

    def _createNewGameDetailTable(self):
        self.executeSql(
            """CREATE TABLE gamedetails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venue TEXT NOT NULL,
                gameId TEXT NOT NULL,
                center TEXT NOT NULL,
                ar1 TEXT NOT NULL,
                ar2 TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                age TEXT NOT NULL,
                level TEXT NOT NULL,
                organization_id INTEGER NOT NULL REFERENCES organizations(id)
            )"""
        )

    def _createUserVisitsTable(self):
        self.executeSql(
            """CREATE TABLE user_visits (
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                email TEXT NOT NULL,
                date TIMESTAMP NOT NULL DEFAULT (datetime('now')),
                ip_address TEXT,
                user_agent TEXT
            )"""
        )

    def _createUsersTable(self):
        self.executeSql(
            """CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                first_name TEXT,
                last_name TEXT,
                settings TEXT NOT NULL DEFAULT '{}',
                avatar_jpeg BLOB,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now')),
                last_login TIMESTAMP
            )"""
        )

    def _createOrganizationsTable(self):
        self.executeSql(
            """CREATE TABLE organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                slug TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now'))
            )"""
        )

    def _createUserOrganizationsTable(self):
        self.executeSql(
            """CREATE TABLE user_organizations (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, organization_id)
            )"""
        )
        self.connection.commit()

    def _createPasswordResetTokensTable(self):
        self.executeSql(
            """CREATE TABLE password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now')),
                used INTEGER NOT NULL DEFAULT 0
            )"""
        )

    def _createLogsTable(self):
        self.executeSql(
            """CREATE TABLE logs (
                timestamp TIMESTAMP NOT NULL DEFAULT (datetime('now')),
                message TEXT NOT NULL
            )"""
        )

    def _createCalendarEventsTable(self):
        self.executeSql(
            """CREATE TABLE calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                start_date DATE NOT NULL,
                end_date DATE,
                start_time TIME,
                end_time TIME,
                created_by TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now')),
                updated_at TIMESTAMP NOT NULL DEFAULT (datetime('now'))
            )"""
        )

    def _createMentorGameSelectionsTable(self):
        self.executeSql(
            """CREATE TABLE mentor_game_selections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mentor_id INTEGER NOT NULL REFERENCES users(id),
                game_date TEXT NOT NULL,
                venue TEXT NOT NULL,
                game_id TEXT NOT NULL,
                organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                selected_at TIMESTAMP NOT NULL DEFAULT (datetime('now')),
                UNIQUE (organization_id, mentor_id, game_date, venue, game_id)
            )"""
        )

    def updateUserSetting(self, user_id: int, key: str, value: Any) -> None:
        settings = self.getUserSettings(user_id)
        settings[key] = value
        self.executeSql(
            "UPDATE users SET settings = %s WHERE id = %s",
            (json.dumps(settings), user_id),
        )
        self.connection.commit()
