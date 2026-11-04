"""Demo login keeps the golden file closed and gives each login its own database."""

import hashlib
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from auth_nicegui import AuthManager
from database import get_db
from database_sqlite import (
    DEMO_SESSION_DB_KEY,
    DemoSessionExpired,
    RefereeDbSqlite,
    active_sqlite_path,
    demo_auth_db_path,
    prepare_demo_auth_database,
    provision_demo_session_database,
    session_demo_db_path,
    sweep_abandoned_demo_databases,
)


class TestDemoSessionDatabase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        self.golden_path = root / 'golden.sqlite'
        self.live_path = root / 'live.sqlite'
        self._saved = {
            key: os.environ.get(key)
            for key in ('DB_BACKEND', 'DEMO_MODE', 'DEMO_BASELINE_PATH', 'SQLITE_PATH')
        }
        os.environ['DB_BACKEND'] = 'sqlite'
        os.environ['DEMO_MODE'] = 'true'
        os.environ['DEMO_BASELINE_PATH'] = str(self.golden_path)
        os.environ['SQLITE_PATH'] = str(self.live_path)

        auth = AuthManager()
        password_hash, salt = auth.hash_password('secret')
        golden = RefereeDbSqlite(str(self.golden_path))
        golden.createUser('demo', password_hash, salt, 'demo@example.com', 'user', 'Dee', 'Mo')
        user = golden.getUserByUsername('demo')
        self.org_id = golden.getDefaultOrganizationId()
        golden.addUserToOrganization(user['id'], self.org_id)
        golden.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        golden.connection.close()
        for suffix in ('-wal', '-shm'):
            sidecar = Path(f'{self.golden_path}{suffix}')
            if sidecar.exists():
                sidecar.unlink()
        self.golden_digest = hashlib.sha256(self.golden_path.read_bytes()).hexdigest()

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmpdir.cleanup()

    def test_login_uses_auth_copy_and_a_private_session_file(self):
        self.assertTrue(prepare_demo_auth_database())
        self.assertTrue(demo_auth_db_path().is_file())
        self.assertNotEqual(demo_auth_db_path().resolve(), self.golden_path.resolve())
        self.assertEqual(active_sqlite_path(), str(demo_auth_db_path()))

        storage = SimpleNamespace(user={}, browser={})
        with patch('auth_nicegui.app.storage', storage):
            signed_in = AuthManager().authenticate_user('demo', 'secret', organization_id=self.org_id)
            self.assertTrue(signed_in)
            session_path = storage.user['demo_db_path']
            self.assertEqual(active_sqlite_path(), session_path)
            session_db = get_db()
            session_db.executeSql(
                "UPDATE users SET email = %s WHERE username = %s",
                ('changed@example.com', 'demo'),
            )
            session_db.connection.commit()
            self.assertEqual(session_db.getUserByUsername('demo')['email'], 'changed@example.com')

        self.assertTrue(Path(session_path).is_file())
        self.assertNotEqual(Path(session_path).resolve(), self.golden_path.resolve())
        self.assertNotEqual(Path(session_path).resolve(), demo_auth_db_path().resolve())
        self.assertEqual(
            hashlib.sha256(self.golden_path.read_bytes()).hexdigest(),
            self.golden_digest,
        )
        auth_db = RefereeDbSqlite(str(demo_auth_db_path()))
        self.assertEqual(auth_db.getUserByUsername('demo')['email'], 'demo@example.com')

    def test_second_login_gets_a_different_file(self):
        prepare_demo_auth_database()
        first = provision_demo_session_database()
        second = provision_demo_session_database()
        self.assertNotEqual(first, second)
        self.assertTrue(Path(first).is_file())
        self.assertTrue(Path(second).is_file())

    def test_sweep_deletes_session_files_older_than_ten_hours(self):
        prepare_demo_auth_database()
        old = Path(provision_demo_session_database())
        new = Path(provision_demo_session_database())
        wal = Path(f'{old}-wal')
        wal.write_bytes(b'wal')
        created = {old.resolve(): 0.0, new.resolve(): time.time()}

        def fake_created(path):
            return created.get(Path(path).resolve(), time.time())

        with patch('database_sqlite.file_created_at', fake_created):
            removed = sweep_abandoned_demo_databases(now=time.time())

        self.assertEqual(removed, 1)
        self.assertFalse(old.exists())
        self.assertFalse(wal.exists())
        self.assertTrue(new.exists())
        self.assertTrue(demo_auth_db_path().is_file())

    def test_missing_session_file_ends_the_demo_login(self):
        storage = SimpleNamespace(
            user={DEMO_SESSION_DB_KEY: str(Path(self._tmpdir.name) / 'gone.sqlite')},
            browser={},
        )
        with patch('auth_nicegui.app.storage', storage):
            with self.assertRaises(DemoSessionExpired):
                session_demo_db_path()
        self.assertEqual(storage.user, {})
