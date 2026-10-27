"""Narrative PDF export for mentoring-session reports."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from fpdf import FPDF
from fpdf.enums import Align, XPos, YPos

from report_sessions import MentoringSessionRow

_FONT_DIR = Path(__file__).resolve().parent / 'fonts'
_FONT_REGULAR = _FONT_DIR / 'DejaVuSans.ttf'
_FONT_BOLD = _FONT_DIR / 'DejaVuSans-Bold.ttf'

_NAVY = (30, 64, 110)
_INK = (28, 32, 38)
_MUTED = (80, 90, 102)
_RULE = (210, 216, 224)
_BAND = (232, 238, 245)

_SCOPE_LABELS = {
    'year': 'Year',
    'week': 'Week',
    'referee': 'Referee',
    'mentor': 'Mentor',
}


class MentoringReportPDF(FPDF):
    def __init__(self, running_title: str = '', **kwargs):
        super().__init__(**kwargs)
        self.running_title = running_title

    def header(self):
        self.set_font('DejaVu', '', 9)
        self.set_text_color(*_MUTED)
        brand = 'Referee Mentor System'
        right = self.running_title if self.page_no() > 1 else ''
        brand_width = self.get_string_width(brand) + 6
        available = max(self.epw - brand_width, 0)
        while right and self.get_string_width(right) > available and len(right) > 1:
            right = right[:-2].rstrip() + '…'
        self.cell(brand_width, 5, brand)
        self.cell(
            available,
            5,
            right,
            align=Align.R,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        y = self.get_y() + 1
        self.set_draw_color(*_NAVY)
        self.set_line_width(0.4)
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.set_y(y + 4)

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(*_RULE)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_y(-12)
        self.set_font('DejaVu', '', 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 8, f'Page {self.page_no()}/{{nb}}', align=Align.C)


def pdf_bytes_from_session_rows(
    rows: Iterable[MentoringSessionRow],
    *,
    scope: Optional[str] = None,
    selection: Optional[str] = None,
) -> bytes:
    """Build a printable mentoring report grouped by session date."""
    row_list = list(rows)
    regular, bold = _require_fonts()
    pdf = MentoringReportPDF(
        running_title=_selection_line(scope, selection),
        format='letter',
        unit='mm',
    )
    pdf.set_title('Mentoring Report')
    pdf.set_creator('Referee Mentor System')
    pdf.add_font('DejaVu', '', str(regular))
    pdf.add_font('DejaVu', 'B', str(bold))
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(16, 14, 16)
    pdf.add_page()
    _write_title(pdf, scope, selection, len(row_list))

    grouped: dict[Any, list[MentoringSessionRow]] = {}
    for row in row_list:
        grouped.setdefault(row.date, []).append(row)

    if not grouped:
        pdf.set_font('DejaVu', '', 11)
        pdf.set_text_color(*_INK)
        pdf.multi_cell(
            0,
            6,
            'No mentoring sessions found for this selection.',
            align=Align.L,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
    else:
        for session_date, entries in grouped.items():
            _write_date_heading(pdf, session_date)
            for index, entry in enumerate(entries):
                _write_session(pdf, entry, draw_rule=index < len(entries) - 1)

    output = pdf.output()
    return bytes(output)


def _require_fonts() -> tuple[Path, Path]:
    missing = [path.name for path in (_FONT_REGULAR, _FONT_BOLD) if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f'Missing PDF font file(s) in {_FONT_DIR}: {", ".join(missing)}'
        )
    return _FONT_REGULAR, _FONT_BOLD


def _write_title(
    pdf: FPDF,
    scope: Optional[str],
    selection: Optional[str],
    count: int,
) -> None:
    pdf.set_text_color(*_NAVY)
    pdf.set_font('DejaVu', 'B', 18)
    pdf.cell(0, 10, 'Mentoring Report', new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    selection_line = _selection_line(scope, selection)
    if selection_line:
        pdf.set_font('DejaVu', '', 12)
        pdf.set_text_color(*_INK)
        pdf.multi_cell(
            0,
            6,
            selection_line,
            align=Align.L,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    noun = 'session' if count == 1 else 'sessions'
    generated = _format_report_date(date.today())
    pdf.set_font('DejaVu', '', 9)
    pdf.set_text_color(*_MUTED)
    pdf.cell(
        0,
        6,
        f'{count} {noun}  ·  Generated {generated}',
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(4)


def _write_date_heading(pdf: FPDF, session_date: Any) -> None:
    _ensure_room(pdf, 28)
    label = _format_report_date(session_date) or 'Undated'
    y = pdf.get_y()
    pdf.set_fill_color(*_BAND)
    pdf.rect(pdf.l_margin, y, pdf.epw, 8, style='F')
    pdf.set_fill_color(*_NAVY)
    pdf.rect(pdf.l_margin, y, 1.4, 8, style='F')
    pdf.set_xy(pdf.l_margin + 4, y + 1.4)
    pdf.set_font('DejaVu', 'B', 11)
    pdf.set_text_color(*_NAVY)
    pdf.cell(
        pdf.epw - 6,
        5.2,
        label,
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.set_y(y + 11)


def _write_session(pdf: FPDF, entry: MentoringSessionRow, *, draw_rule: bool) -> None:
    _ensure_room(pdf, 22)
    pdf.set_text_color(*_INK)
    pdf.set_font('DejaVu', 'B', 11)
    pdf.multi_cell(
        0,
        6,
        _plain(entry.referee) or 'Unknown referee',
        align=Align.L,
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )

    pdf.set_font('DejaVu', '', 10)
    pdf.set_text_color(*_MUTED)
    position = _plain(entry.position) or 'Position not recorded'
    mentor = _plain(entry.mentor) or 'Unknown mentor'
    pdf.multi_cell(
        0,
        5,
        f'{position}    Mentor: {mentor}',
        align=Align.L,
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )

    pdf.ln(1)
    pdf.set_font('DejaVu', '', 10)
    pdf.set_text_color(*_INK)
    comments = _plain(entry.comments) or 'No comments recorded.'
    pdf.multi_cell(
        0,
        5,
        comments,
        align=Align.L,
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )

    detail_lines = _game_detail_lines(entry)
    if detail_lines:
        pdf.ln(1)
        pdf.set_font('DejaVu', '', 9)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(
            0,
            4.5,
            '\n'.join(detail_lines),
            align=Align.L,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    pdf.ln(2.5)
    if draw_rule and not _needs_page(pdf, 8):
        y = pdf.get_y()
        pdf.set_draw_color(*_RULE)
        pdf.set_line_width(0.2)
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.ln(3)


def _selection_line(scope: Optional[str], selection: Optional[str]) -> str:
    if selection is None or str(selection).strip() == '':
        return ''
    label = _SCOPE_LABELS.get((scope or '').strip().lower(), 'Selection')
    return f'{label}: {selection}'


def _game_detail_lines(entry: MentoringSessionRow) -> list[str]:
    if not entry.has_game_details():
        return []

    lines: list[str] = []
    summary = []
    if _plain(entry.game_id):
        summary.append(f'Game {_plain(entry.game_id)}')
    if entry.game_date:
        summary.append(_format_calendar_date(entry.game_date))
    if _plain(entry.time):
        summary.append(_plain(entry.time))
    if _plain(entry.venue):
        summary.append(_plain(entry.venue))
    if summary:
        lines.append('  ·  '.join(summary))

    crew = []
    if _plain(entry.center):
        crew.append(f'Center: {_plain(entry.center)}')
    if _plain(entry.ar1):
        crew.append(f'AR1: {_plain(entry.ar1)}')
    if _plain(entry.ar2):
        crew.append(f'AR2: {_plain(entry.ar2)}')
    if crew:
        lines.append('  ·  '.join(crew))

    meta = []
    if _plain(entry.age):
        meta.append(f'Age: {_plain(entry.age)}')
    if _plain(entry.level):
        meta.append(f'Level: {_plain(entry.level)}')
    if meta:
        lines.append('  ·  '.join(meta))
    return lines


def _format_calendar_date(value: Any) -> str:
    """Date only. Game time is a separate field, so drop any clock here."""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return f'{value.strftime("%B")} {value.day}, {value.year}'
    return _plain(value)


def _format_report_date(value: Any) -> str:
    if isinstance(value, datetime):
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            value = value.date()
        else:
            clock = value.strftime('%H:%M')
            return f'{value.strftime("%B")} {value.day}, {value.year} {clock}'
    if isinstance(value, date):
        return f'{value.strftime("%B")} {value.day}, {value.year}'
    if value is None:
        return ''
    return str(value)


def _plain(value: Any) -> str:
    if value is None:
        return ''
    text = str(value).replace('\r\n', '\n').replace('\r', '\n').replace('\t', ' ')
    return text.strip()


def _needs_page(pdf: FPDF, height: float) -> bool:
    trigger = getattr(pdf, 'page_break_trigger', pdf.h - pdf.b_margin)
    return pdf.get_y() + height > trigger


def _ensure_room(pdf: FPDF, height: float) -> None:
    if _needs_page(pdf, height):
        pdf.add_page()
