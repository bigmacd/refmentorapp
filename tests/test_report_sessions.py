"""Unit tests for structured mentoring session report rows."""

import re
import sys
import unittest
import zlib
from datetime import date, datetime
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
from pdfWriter import pdf_bytes_from_session_rows


def _pdf_objects(data: bytes) -> dict[int, bytes]:
    """Split an uncompressed-structure PDF into object bodies."""
    objects: dict[int, bytes] = {}
    pos = 0
    while True:
        match = re.search(rb'(\d+) 0 obj\r?\n', data[pos:])
        if not match:
            break
        number = int(match.group(1))
        start = pos + match.end()
        index = start
        while True:
            stream_at = data.find(b'\nstream\n', index)
            endobj_at = data.find(b'\nendobj', index)
            if endobj_at < 0:
                return objects
            if stream_at != -1 and stream_at < endobj_at:
                endstream = data.find(b'\nendstream', stream_at)
                if endstream < 0:
                    return objects
                index = endstream + len(b'\nendstream')
                continue
            objects[number] = data[start:endobj_at]
            pos = endobj_at + len(b'\nendobj')
            break
    return objects


def _stream_bytes(obj: bytes) -> bytes:
    marker = b'\nstream\n'
    start = obj.find(marker)
    if start < 0:
        return b''
    body_start = start + len(marker)
    end = obj.rfind(b'\nendstream')
    body = obj[body_start:end if end > body_start else None]
    header = obj[:start]
    if b'/FlateDecode' in header:
        return zlib.decompress(body)
    return body


def _cmap(stream: bytes) -> dict[int, str]:
    text = stream.decode('latin-1', errors='ignore')
    mapping: dict[int, str] = {}
    for block in re.findall(r'beginbfchar(.*?)endbfchar', text, re.S):
        for src, dst in re.findall(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', block):
            mapping[int(src, 16)] = chr(int(dst, 16))
    return mapping


def _pdf_literal(data: bytes, index: int) -> tuple[bytes, int]:
    """Read a PDF literal string starting at '('."""
    index += 1
    out = bytearray()
    depth = 1
    while index < len(data) and depth:
        byte = data[index]
        if byte == 0x5C:
            index += 1
            if index >= len(data):
                break
            escaped = data[index]
            if escaped in b'()\\':
                out.append(escaped)
            elif escaped == ord('n'):
                out.append(10)
            elif escaped == ord('r'):
                out.append(13)
            elif escaped == ord('t'):
                out.append(9)
            elif chr(escaped) in '01234567':
                octal = bytearray([escaped])
                for _ in range(2):
                    if index + 1 < len(data) and chr(data[index + 1]) in '01234567':
                        index += 1
                        octal.append(data[index])
                    else:
                        break
                out.append(int(octal, 8) & 0xFF)
            else:
                out.append(escaped)
        elif byte == ord('('):
            depth += 1
            out.append(byte)
        elif byte == ord(')'):
            depth -= 1
            if depth:
                out.append(byte)
        else:
            out.append(byte)
        index += 1
    return bytes(out), index


def _decode_cid(blob: bytes, mapping: dict[int, str]) -> str:
    chars = []
    if len(blob) % 2:
        blob = blob[:-1]
    for offset in range(0, len(blob), 2):
        cid = int.from_bytes(blob[offset:offset + 2], 'big')
        chars.append(mapping.get(cid, ''))
    return ''.join(chars)


def pdf_plain_text(raw: bytes) -> str:
    """Recover visible text from an fpdf2 mentoring-report PDF."""
    objects = _pdf_objects(raw)
    font_maps: dict[str, dict[int, str]] = {}
    for obj in objects.values():
        for name, ref in re.findall(rb'/F(\d+)\s+(\d+)\s+0\s+R', obj):
            font_obj = objects.get(int(ref), b'')
            link = re.search(rb'/ToUnicode\s+(\d+)\s+0\s+R', font_obj)
            if not link:
                continue
            font_maps['F' + name.decode()] = _cmap(_stream_bytes(objects[int(link.group(1))]))

    parts: list[str] = []
    for obj in objects.values():
        if b'/Contents' not in obj or not obj.strip().startswith(b'<<'):
            continue
        for ref in re.findall(rb'/Contents\s+(\d+)\s+0\s+R', obj):
            content = _stream_bytes(objects[int(ref)])
            font = ''
            index = 0
            while index < len(content):
                if content.startswith(b'/F', index) and index + 2 < len(content) and content[index + 2:index + 3].isdigit():
                    end = index + 2
                    while end < len(content) and content[end:end + 1].isdigit():
                        end += 1
                    font = content[index + 1:end].decode()
                    index = end
                    continue
                if content[index:index + 1] == b'(':
                    blob, index = _pdf_literal(content, index)
                    parts.append(_decode_cid(blob, font_maps.get(font, {})))
                    continue
                index += 1
    return '\n'.join(part for part in parts if part)


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

    def test_pdf_bytes_are_a_narrative_report(self):
        rows = [
            MentoringSessionRow(
                date=date(2025, 9, 6),
                referee='José García',
                position='Center',
                mentor='David Helfgott',
                comments='Arrived early — good positioning.\nTalked at halftime.',
                game_id='G123',
                center='José García',
                ar1='A',
                ar2='B',
                game_date=datetime(2025, 9, 6, 9, 0),
                venue='Field 1',
                time='09:00',
                age='U10',
                level='Rec',
            ),
            MentoringSessionRow(
                date=date(2025, 9, 13),
                referee='Sam Smith',
                position='AR1',
                mentor='David Helfgott',
                comments='',
            ),
        ]
        raw = pdf_bytes_from_session_rows(rows, scope='year', selection='2025')
        self.assertTrue(raw.startswith(b'%PDF-'))
        self.assertIn(b'/Title (Mentoring Report)', raw)
        text = pdf_plain_text(raw)
        self.assertIn('Mentoring Report', text)
        self.assertIn('Year: 2025', text)
        self.assertIn('September 6, 2025', text)
        self.assertIn('September 13, 2025', text)
        self.assertIn('José García', text)
        self.assertIn('Arrived early — good positioning.', text)
        self.assertIn('Game G123', text)
        self.assertIn('September 6, 2025  ·  09:00  ·  Field 1', text)
        self.assertNotIn('09:00  ·  09:00', text)
        self.assertIn('Sam Smith', text)
        self.assertIn('No comments recorded.', text)
        self.assertNotIn('Game None', text)

    def test_pdf_long_comment_spans_pages(self):
        rows = [
            MentoringSessionRow(
                date=date(2025, 9, 6),
                referee='Jane Doe',
                position='Center',
                mentor='David Helfgott',
                comments='\n'.join(f'Observation line {i}.' for i in range(120)),
            )
        ]
        raw = pdf_bytes_from_session_rows(rows, scope='referee', selection='Jane Doe')
        self.assertTrue(raw.startswith(b'%PDF-'))
        page_count = len(re.findall(rb'/Type /Page(?!s)', raw))
        self.assertGreaterEqual(page_count, 2)

    def test_pdf_empty_rows_still_produce_a_document(self):
        raw = pdf_bytes_from_session_rows([], scope='week', selection='Oct 4')
        text = pdf_plain_text(raw)
        self.assertIn('No mentoring sessions found', text)
        self.assertIn('Week: Oct 4', text)