"""Year-end summary counts and the one-page PDF."""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from pdfWriter import pdf_bytes_from_year_end_summary
from test_report_sessions import pdf_plain_text
from year_end_summary import (
    SummarySession,
    build_year_end_summary,
    text_from_year_end_summary,
)


def _session(referee_id, position, when, mentor, game_id=None, first='', last=''):
    return SummarySession(
        referee_id,
        position,
        when,
        mentor,
        game_id,
        referee_first=first,
        referee_last=last,
    )


class TestYearEndSummary(unittest.TestCase):
    def test_blocks_from_a_mixed_year(self):
        sessions = [
            _session(1, 'Center', date(2026, 5, 1), 'Pat Mentor', 'G1', first='zoe', last='adams'),
            _session(1, 'AR1', date(2026, 5, 20), 'Pat Mentor', 'G1'),
            _session(1, 'Center', date(2026, 9, 1), 'Rae Coach', 'G2'),
            _session(2, 'AR1', date(2026, 4, 2), 'Pat Mentor', 'G3', first='amy', last='chen'),
            _session(2, 'ar2', date(2026, 4, 5), 'pat mentor', 'G3'),
            _session(3, 'center', date(2026, 11, 2), 'Sam Lee', 'G4', first='sam', last='lee'),
            _session(6, 'Center', date(2026, 1, 10), 'Pat Mentor', '', first='casey', last='ng'),
            _session(6, 'Center', date(2026, 3, 1), 'Pat Mentor', 'G5'),
            _session(1, 'Center', date(2025, 9, 1), 'Pat Mentor', 'OLD'),
            _session(7, 'Fourth official', date(2026, 6, 1), '', 'G6', first='pat', last='quinn'),
        ]
        summary = build_year_end_summary(2026, sessions, [1, 3, 4])

        self.assertEqual(summary.reports, 9)
        self.assertEqual(summary.referees, 5)
        self.assertEqual(summary.games, 6)
        self.assertEqual(summary.ar_only, 1)
        self.assertEqual(summary.center_only, 2)
        self.assertEqual(summary.both, 1)
        self.assertEqual(summary.other_position, 1)
        self.assertEqual(summary.ar_only_names, ('Amy Chen',))
        self.assertEqual(summary.center_only_names, ('Sam Lee', 'Casey Ng'))
        self.assertEqual(summary.both_names, ('Zoe Adams',))
        self.assertEqual(summary.other_position_names, ('Pat Quinn',))
        self.assertEqual(summary.seen_once, 2)
        self.assertEqual(summary.seen_twice, 2)
        self.assertEqual(summary.seen_three_or_more, 1)
        self.assertEqual(summary.seen_by_multiple_mentors, 1)
        self.assertEqual(summary.within_seven_days, 1)
        self.assertEqual(summary.beyond_seven_days, 2)
        self.assertEqual(summary.spring_reports, 5)
        self.assertEqual(summary.spring_referees, 3)
        self.assertEqual(summary.fall_reports, 2)
        self.assertEqual(summary.fall_referees, 2)
        self.assertEqual(summary.months[0].reports, 1)
        self.assertEqual(summary.months[1].reports, 0)
        self.assertEqual(summary.months[2].referees, 1)
        self.assertEqual(summary.months[3].reports, 2)
        self.assertEqual(summary.months[4].reports, 2)
        self.assertEqual(summary.months[8].reports, 1)
        self.assertEqual(summary.months[10].reports, 1)
        self.assertEqual(summary.new_referees, 3)
        self.assertEqual(summary.new_referees_mentored, 2)
        self.assertEqual(summary.new_referees_not_mentored, 1)
        self.assertEqual(summary.average_reports_per_referee, 1.8)
        self.assertEqual(
            [mentor.name for mentor in summary.mentors],
            ['Pat Mentor', 'Rae Coach', 'Sam Lee', 'Unknown mentor'],
        )
        self.assertEqual(summary.mentors[0].reports, 6)
        self.assertEqual(summary.mentors[0].referees, 3)

        text = text_from_year_end_summary(summary)
        for heading in (
            'Year-end summary 2026',
            'Reach',
            'Depth',
            'Spread across the year',
            'Who carried the load',
            'New referees',
        ):
            self.assertIn(heading, text)
        self.assertIn('AR only: 1 (20%)', text)
        self.assertIn('Both: 1 (20%)', text)
        self.assertIn('Other position: 1 (20%)', text)
        self.assertIn('2 referees with 1 session', text)
        self.assertIn('2 referees with 2 sessions', text)
        self.assertIn('1 referee with 3 or more sessions', text)
        self.assertIn('Average reports per referee: 1.8', text)
        self.assertIn('Spring: 5 reports, 3 referees', text)
        self.assertIn('Fall: 2 reports, 2 referees', text)
        self.assertIn('3 referees with two or more sessions', text)
        self.assertIn('1 referee with every session within 7 days', text)
        self.assertIn('2 referees with a first and last session more than 7 days apart', text)
        self.assertIn('Pat Mentor wrote 6 of 9 reports (66.7%)', text)
        self.assertIn('Not mentored: 1', text)
        self.assertIn('January', text)
        self.assertIn('Reach names', text)
        self.assertIn('Amy Chen', text)
        self.assertIn('Zoe Adams', text)
        self.assertNotIn('OLD', text)

    def test_seven_day_boundary_and_tied_mentors(self):
        sessions = [
            _session(1, 'Center', date(2026, 5, 1), 'Pat Mentor', 'G1'),
            _session(1, 'Center', date(2026, 5, 8), 'Rae Coach', 'G2'),
            _session(2, 'AR1', date(2026, 5, 1), 'Pat Mentor', 'G3'),
            _session(2, 'AR2', date(2026, 5, 9), 'Rae Coach', 'G4'),
        ]
        summary = build_year_end_summary(2026, sessions, [])
        self.assertEqual(summary.within_seven_days, 1)
        self.assertEqual(summary.beyond_seven_days, 1)
        self.assertEqual(summary.ar_only, 1)
        self.assertEqual(summary.center_only, 1)
        text = text_from_year_end_summary(summary)
        self.assertIn('Pat Mentor and Rae Coach each wrote 2 of 4 reports (50%)', text)

    def test_empty_year(self):
        summary = build_year_end_summary(2026, [], [4])
        self.assertEqual(summary.reports, 0)
        self.assertEqual(summary.referees, 0)
        self.assertEqual(summary.games, 0)
        self.assertEqual(summary.new_referees, 1)
        self.assertEqual(summary.new_referees_mentored, 0)
        self.assertEqual(len(summary.months), 12)
        text = text_from_year_end_summary(summary)
        self.assertIn('No reports were filed.', text)
        self.assertIn('Certified in 2026: 1', text)
        self.assertIn('AR only: 0 (0%)', text)

    def test_pdf_contains_the_five_blocks(self):
        summary = build_year_end_summary(
            2026,
            [
                _session(1, 'Center', date(2026, 5, 1), 'Pat Mentor', 'G1', first='zoe', last='adams'),
                _session(1, 'AR1', date(2026, 8, 2), 'Rae Coach', 'G2'),
            ],
            [1, 9],
        )
        plain = pdf_plain_text(pdf_bytes_from_year_end_summary(summary))
        for heading in (
            'Year-end summary 2026',
            'Reports',
            'Referees mentored',
            'Games observed',
            'Reach',
            'Depth',
            'Spread across the year',
            'Who carried the load',
            'New referees',
            'Pat Mentor',
            '1 referee with 2 sessions',
            '1 referee with two or more sessions',
            'Zoe Adams',
            'Not mentored: 1',
            'January',
            'December',
        ):
            self.assertIn(heading, plain)
