"""Unit tests for structured mentoring session report rows."""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from report_sessions import (
    MentoringSessionRow,
    csv_bytes_from_session_rows,
    csv_ready_dicts,
    preview_text_from_session_rows,
    rows_from_db_tuples,
    text_from_session_rows,
)
from excelWriter import excel_bytes_from_session_rows


class TestReportSessions(unittest.TestCase):
    def test_rows_from_db_tuples_maps_columns_and_names(self):
        raw = [
            (
                'jane',
                'doe',
                'Center',
                date(2025, 9, 6),
                'Good positioning.',
                'helf gott',
                'david',
                'G123',
                'Jane Doe',
                'AR One',
                'AR Two',
                date(2025, 9, 6),
                'Field 1',
                '09:00',
                'U10',
                'Rec',
            )
        ]
        rows = rows_from_db_tuples(raw)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.referee, 'Jane Doe')
        self.assertEqual(row.mentor, 'David Helf gott')
        self.assertEqual(row.position, 'Center')
        self.assertEqual(row.comments, 'Good positioning.')
        self.assertEqual(row.game_id, 'G123')
        self.assertTrue(row.has_game_details())

    def test_rows_from_db_tuples_unknown_mentor_when_missing(self):
        raw = [
            (
                'sam',
                'smith',
                'AR1',
                date(2025, 9, 7),
                'Notes',
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
        ]
        row = rows_from_db_tuples(raw)[0]
        self.assertEqual(row.mentor, 'Mentor Unknown')
        self.assertFalse(row.has_game_details())

    def test_text_from_session_rows_matches_classic_shape(self):
        rows = [
            MentoringSessionRow(
                date=date(2025, 9, 6),
                referee='Jane Doe',
                position='Center',
                mentor='David Helfgott',
                comments='Line one.\nLine two.',
                game_id='G1',
                center='Jane Doe',
                ar1='A',
                ar2='B',
                game_date=date(2025, 9, 6),
                venue='Park',
                time='10:00',
                age='U12',
                level='Travel',
            ),
            MentoringSessionRow(
                date=date(2025, 9, 6),
                referee='Sam Smith',
                position='AR1',
                mentor='David Helfgott',
                comments='Second session',
            ),
        ]
        text = text_from_session_rows(rows)
        self.assertIn('Date: 2025-09-06\r\n', text)
        self.assertIn('\tReferee: Jane Doe\r\n', text)
        self.assertIn('\tComments: Line one.\nLine two.\r\n\r\n', text)
        self.assertIn('\tGame Details:\r\n', text)
        self.assertIn('\t\tGame ID: G1\r\n', text)
        self.assertIn('\tReferee: Sam Smith\r\n', text)
        self.assertNotIn('Game ID: None', text)

    def test_csv_ready_dicts_stringifies_dates(self):
        rows = [
            MentoringSessionRow(
                date=date(2025, 9, 6),
                referee='Jane Doe',
                position='Center',
                mentor='David Helfgott',
                comments='ok',
                game_date=date(2025, 9, 6),
            )
        ]
        data = csv_ready_dicts(rows)
        self.assertEqual(data[0]['date'], '2025-09-06')
        self.assertEqual(data[0]['game_date'], '2025-09-06')
        self.assertEqual(data[0]['referee'], 'Jane Doe')

    def test_preview_text_uses_plain_newlines(self):
        rows = [
            MentoringSessionRow(
                date=date(2025, 9, 6),
                referee='Jane Doe',
                position='Center',
                mentor='David Helfgott',
                comments='ok',
            )
        ]
        preview = preview_text_from_session_rows(rows)
        self.assertNotIn('\r', preview)
        self.assertIn('Date: 2025-09-06\n', preview)

    def test_csv_bytes_include_header_and_row(self):
        rows = [
            MentoringSessionRow(
                date=date(2025, 9, 6),
                referee='Jane Doe',
                position='Center',
                mentor='David Helfgott',
                comments='Good day',
            )
        ]
        raw = csv_bytes_from_session_rows(rows)
        text = raw.decode('utf-8-sig')
        self.assertIn('Date,Referee,Position,Mentor,Comments', text)
        self.assertIn('Jane Doe', text)
        self.assertIn('Good day', text)

    def test_excel_bytes_are_xlsx_zip(self):
        rows = [
            MentoringSessionRow(
                date=date(2025, 9, 6),
                referee='Jane Doe',
                position='Center',
                mentor='David Helfgott',
                comments='Good day',
            )
        ]
        raw = excel_bytes_from_session_rows(rows)
        self.assertTrue(raw.startswith(b'PK'))
        self.assertGreater(len(raw), 100)