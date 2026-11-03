"""Demo baseline restore: visitor writes are replaced by demo/refmentor.sqlite."""

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from database_sqlite import restore_sqlite_baseline


class TestRestoreSqliteBaseline(unittest.TestCase):
    def test_replaces_live_file_and_drops_wal(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / 'baseline.sqlite'
            live = root / 'live' / 'refmentor.sqlite'
            live.parent.mkdir()
            _write_sqlite(baseline, 'baseline-report')
            _write_sqlite(live, 'visitor-report')
            (root / 'live' / 'refmentor.sqlite-wal').write_text('stale')
            (root / 'live' / 'refmentor.sqlite-shm').write_text('stale')

            restore_sqlite_baseline(baseline, live)

            self.assertEqual(_note(live), 'baseline-report')
            self.assertFalse((root / 'live' / 'refmentor.sqlite-wal').exists())
            self.assertFalse((root / 'live' / 'refmentor.sqlite-shm').exists())
            self.assertFalse(live.with_name('refmentor.sqlite.restore').exists())

    def test_same_path_is_left_alone(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'refmentor.sqlite'
            _write_sqlite(path, 'keep')
            restore_sqlite_baseline(path, path)
            self.assertEqual(_note(path), 'keep')


def _write_sqlite(path: Path, note: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE notes (body TEXT)')
    connection.execute('INSERT INTO notes (body) VALUES (?)', (note,))
    connection.commit()
    connection.close()


def _note(path: Path) -> str:
    connection = sqlite3.connect(path)
    row = connection.execute('SELECT body FROM notes').fetchone()
    connection.close()
    return row[0]
