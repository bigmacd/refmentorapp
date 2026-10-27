"""Year-end mentoring summary for a director of officials.

The first page is five blocks — reach, depth, spread, mentor load, and new
referees — plus a header that keeps reports, referees, and games separate.
The names behind the reach counts follow on the next page.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Optional


MONTH_NAMES = (
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
)

_AR_POSITIONS = frozenset({'ar', 'ar1', 'ar2'})


@dataclass(frozen=True)
class SummarySession:
    """One mentoring report used to build the year-end counts."""

    referee_id: int
    position: str
    when: date
    mentor_name: str
    game_id: Optional[str] = None
    referee_first: str = ''
    referee_last: str = ''


@dataclass(frozen=True)
class MonthActivity:
    month: int
    reports: int
    referees: int


@dataclass(frozen=True)
class MentorLoad:
    name: str
    reports: int
    referees: int


@dataclass(frozen=True)
class YearEndSummary:
    year: int
    reports: int
    referees: int
    games: int
    ar_only: int
    center_only: int
    both: int
    other_position: int
    seen_once: int
    seen_twice: int
    seen_three_or_more: int
    seen_by_multiple_mentors: int
    within_seven_days: int
    beyond_seven_days: int
    spring_reports: int
    spring_referees: int
    fall_reports: int
    fall_referees: int
    months: tuple[MonthActivity, ...]
    mentors: tuple[MentorLoad, ...]
    new_referees: int
    new_referees_mentored: int
    ar_only_names: tuple[str, ...]
    center_only_names: tuple[str, ...]
    both_names: tuple[str, ...]
    other_position_names: tuple[str, ...]

    @property
    def new_referees_not_mentored(self) -> int:
        return self.new_referees - self.new_referees_mentored

    @property
    def average_reports_per_referee(self) -> float:
        if self.referees <= 0:
            return 0.0
        return self.reports / self.referees


def session_date(value: Any) -> Optional[date]:
    """Calendar date from a session timestamp, or None if it cannot be read."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip().replace('T', ' ')
    for fmt, size in (('%Y-%m-%d %H:%M:%S', 19), ('%Y-%m-%d', 10)):
        try:
            return datetime.strptime(text[:size], fmt).date()
        except ValueError:
            continue
    return None


def mentor_display_name(first: Optional[str], last: Optional[str]) -> str:
    """Match the app's mentor labels: first letter of each name capitalized."""
    first_name = (first or '').strip()
    last_name = (last or '').strip()
    if first_name and last_name:
        return f'{first_name.capitalize()} {last_name.capitalize()}'
    single = first_name or last_name
    if single:
        return single.capitalize()
    return 'Unknown mentor'


def build_year_end_summary(
    year: int,
    sessions: Iterable[SummarySession],
    certified_referee_ids: Iterable[int],
) -> YearEndSummary:
    """Aggregate a calendar year of mentoring reports.

    Spring is 1 April through 30 June. Fall is 1 July through 31 December.
    Sessions in January–March count in the year and in their month, and in
    neither season. A repeat referee is "within 7 days" when the first and
    last session are at most 7 days apart.
    """
    year = int(year)
    start = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    spring_start = date(year, 4, 1)
    fall_start = date(year, 7, 1)

    in_year: list[tuple[int, str, date, str, str]] = []
    referee_names: dict[int, tuple[str, str]] = {}
    for session in sessions:
        when = session_date(session.when)
        if when is None or not (start <= when < end):
            continue
        referee_id = int(session.referee_id)
        referee_names.setdefault(
            referee_id,
            ((session.referee_first or '').strip(), (session.referee_last or '').strip()),
        )
        mentor = _display_mentor(session.mentor_name)
        game_id = (session.game_id or '').strip()
        in_year.append((referee_id, session.position or '', when, mentor, game_id))

    by_referee: dict[int, list[tuple[str, date, str]]] = {}
    games: set[str] = set()
    month_reports = [0] * 12
    month_referees: list[set[int]] = [set() for _ in range(12)]
    spring_reports = 0
    spring_referees: set[int] = set()
    fall_reports = 0
    fall_referees: set[int] = set()
    mentor_reports: dict[str, int] = {}
    mentor_referees: dict[str, set[int]] = {}
    mentor_names: dict[str, str] = {}

    for referee_id, position, when, mentor, game_id in in_year:
        by_referee.setdefault(referee_id, []).append((position, when, mentor))
        if game_id:
            games.add(game_id)
        month_index = when.month - 1
        month_reports[month_index] += 1
        month_referees[month_index].add(referee_id)
        if spring_start <= when < fall_start:
            spring_reports += 1
            spring_referees.add(referee_id)
        elif when >= fall_start:
            fall_reports += 1
            fall_referees.add(referee_id)
        key = mentor.casefold()
        mentor_names.setdefault(key, mentor)
        mentor_reports[key] = mentor_reports.get(key, 0) + 1
        mentor_referees.setdefault(key, set()).add(referee_id)

    ar_only = center_only = both = other_position = 0
    ar_only_names: list[tuple[tuple[str, str, str], str]] = []
    center_only_names: list[tuple[tuple[str, str, str], str]] = []
    both_names: list[tuple[tuple[str, str, str], str]] = []
    other_position_names: list[tuple[tuple[str, str, str], str]] = []
    seen_once = seen_twice = seen_three_or_more = 0
    seen_by_multiple_mentors = 0
    within_seven_days = beyond_seven_days = 0

    for referee_id, entries in by_referee.items():
        roles = {_position_role(position) for position, _, _ in entries}
        roles.discard('')
        has_ar = 'ar' in roles
        has_center = 'center' in roles
        label = _referee_label(*referee_names.get(referee_id, ('', '')), referee_id)
        if has_ar and has_center:
            both += 1
            both_names.append(label)
        elif has_ar:
            ar_only += 1
            ar_only_names.append(label)
        elif has_center:
            center_only += 1
            center_only_names.append(label)
        else:
            other_position += 1
            other_position_names.append(label)

        count = len(entries)
        if count == 1:
            seen_once += 1
        elif count == 2:
            seen_twice += 1
        else:
            seen_three_or_more += 1

        if len({mentor.casefold() for _, _, mentor in entries}) > 1:
            seen_by_multiple_mentors += 1

        if count >= 2:
            dates = [when for _, when, _ in entries]
            span = (max(dates) - min(dates)).days
            if span <= 7:
                within_seven_days += 1
            else:
                beyond_seven_days += 1

    certified = {int(referee_id) for referee_id in certified_referee_ids}
    mentored = set(by_referee)
    mentors = tuple(
        sorted(
            (
                MentorLoad(mentor_names[key], mentor_reports[key], len(mentor_referees[key]))
                for key in mentor_reports
            ),
            key=lambda load: (-load.reports, load.name.casefold()),
        )
    )
    months = tuple(
        MonthActivity(index + 1, month_reports[index], len(month_referees[index]))
        for index in range(12)
    )

    return YearEndSummary(
        year=year,
        reports=len(in_year),
        referees=len(by_referee),
        games=len(games),
        ar_only=ar_only,
        center_only=center_only,
        both=both,
        other_position=other_position,
        seen_once=seen_once,
        seen_twice=seen_twice,
        seen_three_or_more=seen_three_or_more,
        seen_by_multiple_mentors=seen_by_multiple_mentors,
        within_seven_days=within_seven_days,
        beyond_seven_days=beyond_seven_days,
        spring_reports=spring_reports,
        spring_referees=len(spring_referees),
        fall_reports=fall_reports,
        fall_referees=len(fall_referees),
        months=months,
        mentors=mentors,
        new_referees=len(certified),
        new_referees_mentored=len(certified & mentored),
        ar_only_names=_sorted_names(ar_only_names),
        center_only_names=_sorted_names(center_only_names),
        both_names=_sorted_names(both_names),
        other_position_names=_sorted_names(other_position_names),
    )


def headline_lines(summary: YearEndSummary) -> list[str]:
    return [
        f'Year-end summary {summary.year}',
        _count_phrase(summary.reports, 'report'),
        f'{_count_phrase(summary.referees, "referee")} mentored',
        f'{_count_phrase(summary.games, "game")} observed',
    ]


def reach_lines(summary: YearEndSummary) -> list[str]:
    whole = summary.referees
    lines = [
        f'AR only: {summary.ar_only} ({format_percent(summary.ar_only, whole)})',
        f'Center only: {summary.center_only} ({format_percent(summary.center_only, whole)})',
        f'Both: {summary.both} ({format_percent(summary.both, whole)})',
    ]
    if summary.other_position:
        lines.append(
            f'Other position: {summary.other_position} ({format_percent(summary.other_position, whole)})'
        )
    return lines


def depth_lines(summary: YearEndSummary) -> list[str]:
    return [
        f'{_count_phrase(summary.seen_once, "referee")} with 1 session',
        f'{_count_phrase(summary.seen_twice, "referee")} with 2 sessions',
        f'{_count_phrase(summary.seen_three_or_more, "referee")} with 3 or more sessions',
        f'Average reports per referee: {_average_text(summary)}',
        f'Seen by more than one mentor: {summary.seen_by_multiple_mentors}',
    ]


def spread_lines(summary: YearEndSummary) -> list[str]:
    return [
        'Spring is April–June. Fall is July–December.',
        (
            f'Spring: {_count_phrase(summary.spring_reports, "report")}, '
            f'{_count_phrase(summary.spring_referees, "referee")}'
        ),
        (
            f'Fall: {_count_phrase(summary.fall_reports, "report")}, '
            f'{_count_phrase(summary.fall_referees, "referee")}'
        ),
        (
            f'{_count_phrase(summary.seen_twice + summary.seen_three_or_more, "referee")} '
            'with two or more sessions'
        ),
        (
            f'{_count_phrase(summary.within_seven_days, "referee")} '
            'with every session within 7 days'
        ),
        (
            f'{_count_phrase(summary.beyond_seven_days, "referee")} '
            'with a first and last session more than 7 days apart'
        ),
    ]


def load_lead(summary: YearEndSummary) -> str:
    if summary.reports <= 0 or not summary.mentors:
        return 'No reports were filed.'
    top_reports = summary.mentors[0].reports
    leaders = [mentor for mentor in summary.mentors if mentor.reports == top_reports]
    share = format_percent(top_reports, summary.reports)
    amount = _of_reports(top_reports, summary.reports)
    if len(leaders) == 1:
        return f'{leaders[0].name} wrote {amount} ({share}).'
    if len(leaders) == 2:
        names = f'{leaders[0].name} and {leaders[1].name}'
    else:
        names = ', '.join(mentor.name for mentor in leaders[:-1]) + f', and {leaders[-1].name}'
    return f'{names} each wrote {amount} ({share}).'


def new_referee_lines(summary: YearEndSummary) -> list[str]:
    return [
        f'Certified in {summary.year}: {summary.new_referees}',
        f'Mentored: {summary.new_referees_mentored}',
        f'Not mentored: {summary.new_referees_not_mentored}',
    ]


def month_table_lines(summary: YearEndSummary) -> list[str]:
    lines = [f'{"Month":<12}{"Reports":>8}{"Referees":>10}']
    for month in summary.months:
        name = MONTH_NAMES[month.month - 1]
        lines.append(f'{name:<12}{month.reports:>8}{month.referees:>10}')
    return lines


def mentor_table_lines(summary: YearEndSummary) -> list[str]:
    if not summary.mentors:
        return []
    lines = [f'{"Mentor":<24}{"Reports":>8}{"Referees":>10}{"Share":>8}']
    for mentor in summary.mentors:
        name = mentor.name if len(mentor.name) <= 24 else mentor.name[:23] + '…'
        share = format_percent(mentor.reports, summary.reports)
        lines.append(f'{name:<24}{mentor.reports:>8}{mentor.referees:>10}{share:>8}')
    return lines


def text_from_year_end_summary(summary: YearEndSummary) -> str:
    """Plain-text preview of the one-page summary."""
    blocks = [
        '\n'.join(headline_lines(summary)),
        'Reach\n' + '\n'.join(reach_lines(summary)),
        'Depth\n' + '\n'.join(depth_lines(summary)),
        'Spread across the year\n' + '\n'.join(spread_lines(summary) + [''] + month_table_lines(summary)),
        'Who carried the load\n' + '\n'.join([load_lead(summary)] + mentor_table_lines(summary)),
        'New referees\n' + '\n'.join(new_referee_lines(summary)),
        '\n'.join(reach_name_lines(summary)),
    ]
    return '\n\n'.join(blocks) + '\n'


def reach_name_lines(summary: YearEndSummary) -> list[str]:
    """Names behind the reach counts, in the same order as the boss's query."""
    sections = [
        ('AR only', summary.ar_only_names),
        ('Center only', summary.center_only_names),
        ('Both', summary.both_names),
    ]
    if summary.other_position_names:
        sections.append(('Other position', summary.other_position_names))
    lines = ['Reach names']
    for title, names in sections:
        lines.append(f'{title} ({len(names)})')
        lines.extend(names or ['None'])
        lines.append('')
    return lines


def _sorted_names(labels: list[tuple[tuple[str, str, str], str]]) -> tuple[str, ...]:
    return tuple(name for _, name in sorted(labels, key=lambda item: item[0]))


def _referee_label(first: str, last: str, referee_id: int) -> tuple[tuple[str, str, str], str]:
    first_name = (first or '').strip()
    last_name = (last or '').strip()
    if first_name or last_name:
        display = mentor_display_name(first_name, last_name)
    else:
        display = f'Referee {referee_id}'
    return ((last_name.casefold(), first_name.casefold(), display.casefold()), display)


def _display_mentor(name: Optional[str]) -> str:
    collapsed = ' '.join((name or '').split())
    if not collapsed:
        return 'Unknown mentor'
    return ' '.join(part.capitalize() for part in collapsed.split(' '))


def _position_role(position: str) -> str:
    text = (position or '').strip().casefold()
    if text == 'center':
        return 'center'
    if text in _AR_POSITIONS:
        return 'ar'
    return ''


def format_percent(part: int, whole: int) -> str:
    if whole <= 0:
        return '0%'
    value = (100.0 * part) / whole
    rounded = round(value)
    if abs(value - rounded) < 0.05:
        return f'{rounded:.0f}%'
    return f'{value:.1f}%'


def _average_text(summary: YearEndSummary) -> str:
    value = summary.average_reports_per_referee
    rounded = round(value)
    if abs(value - rounded) < 0.05:
        return f'{rounded:.0f}'
    return f'{value:.1f}'


def _count_phrase(count: int, singular: str, plural: Optional[str] = None) -> str:
    word = singular if count == 1 else (plural or f'{singular}s')
    return f'{count} {word}'


def _of_reports(part: int, whole: int) -> str:
    if whole == 1:
        return f'{part} of 1 report'
    return f'{part} of {whole} reports'
