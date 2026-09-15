"""Smoke tests for the SQLite RefereeDb port."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import use_sqlite_backend
from database_sqlite import RefereeDbSqlite, to_sqlite_sql


class TestSqliteSqlTranslation(unittest.TestCase):
    def test_placeholders_and_now(self):
        sql = "UPDATE users SET last_login = NOW() WHERE username = %s"
        self.assertEqual(
            to_sqlite_sql(sql),
            "UPDATE users SET last_login = datetime('now') WHERE username = ?",
        )

    def test_password_reset_now_cast(self):
        sql = "SELECT 1 WHERE expires_at > (NOW() AT TIME ZONE 'UTC')::TIMESTAMP AND used = FALSE"
        translated = to_sqlite_sql(sql)
        self.assertIn("datetime('now')", translated)
        self.assertNotIn('NOW()', translated)
        self.assertIn('used = 0', translated)


class TestRefereeDbSqlite(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmpdir.name) / 'demo.sqlite')
        self._old_backend = os.environ.get('DB_BACKEND')
        self._old_path = os.environ.get('SQLITE_PATH')
        os.environ['DB_BACKEND'] = 'sqlite'
        os.environ['SQLITE_PATH'] = self.db_path
        self.db = RefereeDbSqlite()

    def tearDown(self):
        self.db.connection.close()
        if self._old_backend is None:
            os.environ.pop('DB_BACKEND', None)
        else:
            os.environ['DB_BACKEND'] = self._old_backend
        if self._old_path is None:
            os.environ.pop('SQLITE_PATH', None)
        else:
            os.environ['SQLITE_PATH'] = self._old_path
        self._tmpdir.cleanup()

    def test_get_db_selects_sqlite(self):
        self.assertTrue(use_sqlite_backend())
        self.assertIsInstance(self.db, RefereeDbSqlite)

    def test_default_org_seeded(self):
        org_id = self.db.getDefaultOrganizationId()
        self.assertIsInstance(org_id, int)
        org = self.db.getOrganizationById(org_id)
        self.assertEqual(org['slug'], 'default')

    def test_user_settings_and_avatar(self):
        self.db.createUser('demo', 'hash', 'salt', 'demo@example.com', 'user', 'Dee', 'Mo')
        user = self.db.getUserByUsername('demo')
        self.assertEqual(user['email'], 'demo@example.com')
        self.db.updateUserSetting(user['id'], 'dark_mode', True)
        settings = self.db.getUserSettings(user['id'])
        self.assertTrue(settings['dark_mode'])
        self.db.setUserAvatar(user['id'], b'\xff\xd8jpeg')
        self.assertTrue(self.db.userHasAvatar(user['id']))
        self.assertEqual(self.db.getUserAvatar(user['id']), b'\xff\xd8jpeg')

    def test_referee_session_and_years(self):
        org_id = self.db.getDefaultOrganizationId()
        self.db.createUser('mentor1', 'h', 's', 'm@example.com', 'user', 'Pat', 'Mentor')
        user = self.db.getUserByUsername('mentor1')
        self.db.addUserToOrganization(user['id'], org_id)
        self.db.addReferee('smith', 'alex', 2026, org_id)
        ok, message = self.db.addMentorSession(
            'Pat Mentor',
            'Alex Smith',
            'Center',
            'Saturday, May 16, 2026',
            'Good positioning',
            'G1',
            org_id,
        )
        self.assertTrue(ok, message)
        years = self.db.getYears(org_id)
        self.assertIn(2026, years)
        metrics = self.db.getMentoringSessionMetrics(2026, 'spring', org_id)
        self.assertEqual(metrics['reports'], 1)

    def test_calendar_event_times(self):
        ok, message, event_id = self.db.addCalendarEvent(
            'Clinic', 'Notes', '2026-03-14', '2026-03-14', '09:00', '11:00', 'demo'
        )
        self.assertTrue(ok, message)
        event = self.db.getCalendarEvent(event_id)
        self.assertEqual(event['title'], 'Clinic')
        self.assertEqual(event['start_time'], '09:00')
        self.assertEqual(event['end_time'], '11:00')

    def test_password_reset_token_not_expired(self):
        self.db.createUser('resetme', 'h', 's', 'reset@example.com')
        user = self.db.getUserByEmail('reset@example.com')
        expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        self.db.createPasswordResetToken(user['id'], 'tok-1', expires)
        row = self.db.getPasswordResetToken('tok-1', 'reset@example.com')
        self.assertIsNotNone(row)
        self.assertEqual(row['username'], 'resetme')
