"""
Structured mentoring-session rows for reports.

DB queries return tuples; convert once to MentoringSessionRow, then render
text / CSV / Excel from those rows instead of parsing report text.
"""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from typing import Any, Iterable, Optional, Sequence


@dataclass(frozen=True)
class MentoringSessionRow:
    """One mentoring observation, optionally enriched with game details."""

    date: Any
    referee: str
    position: str
    mentor: str
    comments: str
    game_id: Optional[str] = None
    center: Optional[str] = None
    ar1: Optional[str] = None
    ar2: Optional[str] = None
    game_date: Any = None
    venue: Optional[str] = None
    time: Optional[str] = None
    age: Optional[str] = None
    level: Optional[str] = None

    def has_game_details(self) -> bool:
        return self.game_id is not None

    def as_export_dict(self) -> dict:
        """Flat dict suitable for CSV / spreadsheet writers."""
        return asdict(self)


SESSION_ROW_FIELD_NAMES = tuple(f.name for f in fields(MentoringSessionRow))

# Stable export column order + human-readable headers (CSV / Excel).
EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ('date', 'Date'),
    ('referee', 'Referee'),
    ('position', 'Position'),
    ('mentor', 'Mentor'),
    ('comments', 'Comments'),
    ('game_id', 'Game ID'),
    ('center', 'Center'),
    ('ar1', 'AR1'),
    ('ar2', 'AR2'),
    ('game_date', 'Game Date'),
    ('venue', 'Venue'),
    ('time', 'Time'),
    ('age', 'Age'),
    ('level', 'Level'),
)


def _cap_name(value: Optional[str], fallback: str = '') -> str:
    if not value:
        return fallback
    return str(value).capitalize()


def _format_cell(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def rows_from_db_tuples(sessions: Sequence[Sequence[Any]]) -> list[MentoringSessionRow]:
    """
    Convert raw SQL tuples from the mentoring-session report queries.

    Expected column order:
      firstname, lastname, position, date, comments,
      mentor_last_name, mentor_first_name,
      gameid, center, ar1, ar2, game_date, venue, time, age, level
    """
    rows: list[MentoringSessionRow] = []
    for session in sessions:
        mentor_last = _cap_name(session[5], 'Unknown')
        mentor_first = _cap_name(session[6], 'Mentor')
        rows.append(
            MentoringSessionRow(
                date=session[3],
                referee=f'{_cap_name(session[0])} {_cap_name(session[1])}'.strip(),
                position=session[2] or '',
                mentor=f'{mentor_first} {mentor_last}'.strip(),
                comments=session[4] or '',
                game_id=session[7],
                center=session[8],
                ar1=session[9],
                ar2=session[10],
                game_date=session[11],
                venue=session[12],
                time=session[13],
                age=session[14],
                level=session[15],
            )
        )
    return rows


def text_from_session_rows(rows: Iterable[MentoringSessionRow]) -> str:
    """Render the classic narrative text report from structured rows."""
    session_data: dict[Any, list[MentoringSessionRow]] = {}
    for row in rows:
        session_data.setdefault(row.date, []).append(row)

    parts: list[str] = []
    for session_date, entries in session_data.items():
        parts.append(f'Date: {session_date}\r\n')
        for entry in entries:
            parts.append(f'\tReferee: {entry.referee}\r\n')
            parts.append(f'\tPosition: {entry.position}\r\n')
            parts.append(f'\tMentor: {entry.mentor}\r\n')
            parts.append(f'\tComments: {entry.comments}\r\n\r\n')
            if entry.has_game_details():
                parts.append('\tGame Details:\r\n')
                parts.append(f'\t\tGame ID: {entry.game_id}\r\n')
                parts.append(f'\t\tCenter: {entry.center}\r\n')
                parts.append(f'\t\tAR1: {entry.ar1}\r\n')
                parts.append(f'\t\tAR2: {entry.ar2}\r\n')
                parts.append(f'\t\tGame Date: {entry.game_date}\r\n')
                parts.append(f'\t\tVenue: {entry.venue}\r\n')
                parts.append(f'\t\tTime: {entry.time}\r\n')
                parts.append(f'\t\tAge Group: {entry.age}\r\n')
                parts.append(f'\t\tLevel: {entry.level}\r\n\r\n')
    return ''.join(parts)


def preview_text_from_session_rows(rows: Iterable[MentoringSessionRow]) -> str:
    """Narrative text for on-screen preview (normal newlines)."""
    return text_from_session_rows(rows).replace('\r\n', '\n').replace('\r', '\n')


def csv_ready_dicts(rows: Iterable[MentoringSessionRow]) -> list[dict]:
    """Normalize rows for tabular export (string cells, stable keys)."""
    out = []
    for row in rows:
        data = row.as_export_dict()
        out.append({key: _format_cell(value) for key, value in data.items()})
    return out


def csv_bytes_from_session_rows(rows: Iterable[MentoringSessionRow]) -> bytes:
    """UTF-8 CSV (with BOM for Excel-friendly open) built from session rows."""
    dicts = csv_ready_dicts(rows)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([label for _, label in EXPORT_COLUMNS])
    for item in dicts:
        writer.writerow([item.get(key, '') for key, _ in EXPORT_COLUMNS])
    # BOM helps Excel on Windows recognize UTF-8
    return ('\ufeff' + buffer.getvalue()).encode('utf-8')
