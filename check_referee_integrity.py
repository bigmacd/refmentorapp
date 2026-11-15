#!/usr/bin/env python3
"""Compare referee lists from the certification spreadsheet, MySoccerLeague, and Mentor Database.

A referee is the same person when the first word of the first name and the last
word of the last name match. Middle names, Jr/Sr/II/III/IV, periods, and letter
case are ignored. The spreadsheet stores "Last, First" (middle names stay on
the first name). MySoccerLeague stores "First Last" (middle names stay on the
last name). Mentor Database stores whatever was inserted.

The spreadsheet is "Referee Certification and Eligibility (Responses)",
worksheet "Form Responses 1". Column D is the name and column K is the
certification date — the columns read by getRefsFromGoogleSignupSheet. This
check reads every response. The importer only inserts names certified in the
last 182 days, and only when the name contains a comma and the date is m/d/YYYY.

MySoccerLeague is the show-all referee roster. Mentor Database is the referees table.
The default organization is VYS, because the form and the league roster are the
VYS lists. Pass --all-orgs to include every Mentor Database organization.

    python check_referee_integrity.py
    python check_referee_integrity.py --org 3
    python check_referee_integrity.py --all-orgs --output integrity.txt --json integrity.json

Exit status is 0 when every referee is in all three sources and nothing else
looks wrong, 1 when the lists differ or a conflict was found, and 2 when a
source could not be read.

Requires GOOGLE_SERVICE_ACCOUNT_JSON, mslUsername, mslPassword, and db_url.
When the spreadsheet certification year differs from Mentor Database, that
spreadsheet year is written to year_certified. A two-digit year such as 24 is
read as 2024. MySoccerLeague is opened in a normal browser window so the
Cloudflare check can be completed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path


SPREADSHEET_NAME = "Referee Certification and Eligibility (Responses)"
WORKSHEET_NAME = "Form Responses 1"
# 1-based columns, matching googleSheets.getRefsFromGoogleSignupSheet.
NAME_COLUMN = 4
DATE_COLUMN = 11
IMPORT_WINDOW_DAYS = 182

SOURCE_SHEET = "spreadsheet"
SOURCE_MSL = "mysoccerleague"
SOURCE_DB = "cockroach"
ALL_SOURCES = frozenset({SOURCE_SHEET, SOURCE_MSL, SOURCE_DB})

SOURCE_LABELS = {
    SOURCE_SHEET: "spreadsheet",
    SOURCE_MSL: "MySoccerLeague",
    SOURCE_DB: "Mentor Database",
}

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

_NICKNAME_GROUPS = (
    ("alexander", "alex"),
    ("andrew", "andy"),
    ("anthony", "tony"),
    ("benjamin", "ben"),
    ("catherine", "cathy"),
    ("christopher", "chris"),
    ("daniel", "dan", "danny"),
    ("david", "dave"),
    ("elizabeth", "liz", "beth"),
    ("james", "jim", "jimmy"),
    ("jennifer", "jen", "jenny"),
    ("jessica", "jess"),
    ("john", "jon", "johnny"),
    ("joseph", "joe"),
    ("katherine", "kathryn", "kate", "katie", "kathy"),
    ("matthew", "matt"),
    ("michael", "mike"),
    ("nicholas", "nick"),
    ("patrick", "pat"),
    ("robert", "rob", "bob"),
    ("samuel", "sam"),
    ("stephen", "steven", "steve"),
    ("thomas", "tom"),
    ("william", "will", "bill", "billy"),
)
NICKNAMES = {
    name: group[0]
    for group in _NICKNAME_GROUPS
    for name in group
}


@dataclass
class Person:
    source: str
    first: str
    last: str
    year: int | None = None
    recent: bool = False
    importable: bool = False
    db_id: int | None = None
    sessions: int = 0
    org_id: int | None = None
    org_label: str = ""
    sheet_row: int | None = None
    cert_text: str = ""
    stored_first: str = ""
    stored_last: str = ""


@dataclass(frozen=True)
class YearUpdate:
    db_id: int
    name: str
    old_year: int
    new_year: int


@dataclass
class Group:
    key: tuple[str, str]
    people: dict[str, list[Person]] = field(default_factory=dict)

    def sources(self) -> frozenset[str]:
        return frozenset(self.people)


@dataclass
class Analysis:
    groups: list[Group]
    conflicts: list[str]
    notes: list[str]
    near_matches: list[str]
    sheet_people: int
    msl_people: int
    db_people: int


def abort(message: str):
    print(message, file=sys.stderr)
    raise SystemExit(2)


def normalize_piece(value: str) -> str:
    """Lowercase a name part and drop periods, commas, and extra whitespace."""
    text = (value or "").replace("\xa0", " ").replace(".", " ").replace(",", " ")
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _without_suffixes(parts: list[str]) -> list[str]:
    trimmed = list(parts)
    while trimmed and trimmed[-1] in SUFFIXES:
        trimmed.pop()
    return trimmed


def loose_key(first: str, last: str) -> tuple[str, str]:
    """Identity used to decide that two records are the same referee."""
    first_parts = _without_suffixes([part for part in first.split() if part])
    last_parts = _without_suffixes([part for part in last.split() if part])
    if not first_parts or not last_parts:
        return ("", "")
    return (first_parts[0], last_parts[-1])


def display_word(word: str) -> str:
    lower = word.lower()
    if lower in {"jr", "sr"}:
        return lower.capitalize()
    if lower in {"ii", "iii", "iv", "v"}:
        return lower.upper()
    if lower.startswith("mc") and len(lower) > 2 and lower[2].isalpha():
        return "Mc" + lower[2:].capitalize()
    if lower.startswith("o'") and len(lower) > 2:
        return "O'" + lower[2:].capitalize()
    return "-".join(part.capitalize() for part in word.split("-"))


def display_name(first: str, last: str) -> str:
    def words(value: str) -> str:
        return " ".join(display_word(word) for word in value.split() if word)

    return f"{words(first)} {words(last)}".strip()


def full_year(year: int) -> int:
    """Read a one- or two-digit year such as 24 as 2024."""
    if 0 <= year < 100:
        return 2000 + year
    return year


def ussf_year(cert_date: datetime) -> int:
    """Same July 1 rollover as googleSheets.adjustPerUSSF."""
    year = full_year(cert_date.year)
    if cert_date.month >= 7:
        year += 1
    return year


def is_recent_certification(cert_date: datetime, now: datetime | None = None) -> bool:
    """True when the importer would still treat this certification as new."""
    current = now or datetime.now()
    earliest = current - timedelta(days=IMPORT_WINDOW_DAYS)
    return earliest <= cert_date <= current


def parse_sheet_name(raw: str) -> tuple[str, str, bool] | None:
    """Return (first, last, comma_form). comma_form is what the importer requires."""
    if not raw or not raw.strip() or "@" in raw:
        return None
    if "," in raw:
        left, right = raw.split(",", 1)
        last = normalize_piece(left)
        first = normalize_piece(right)
        if first and last:
            return first, last, True
        return None
    parts = normalize_piece(raw).split()
    if len(parts) < 2:
        return None
    return parts[0], " ".join(parts[1:]), False


def parse_cert_date(text: str) -> datetime | None:
    text = (text or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{2}(?:\d{2})?", text):
        return datetime(full_year(int(text)), 1, 1)
    parsed = None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return None
    if parsed.year < 100:
        parsed = parsed.replace(year=full_year(parsed.year))
    return parsed


def column_letter(index: int) -> str:
    """Convert a 0-based column index to a spreadsheet letter."""
    number = index + 1
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def best_name(group: Group) -> str:
    people = [person for rows in group.people.values() for person in rows]
    chosen = max(people, key=lambda person: (len(person.first.split()) + len(person.last.split()), len(person.first) + len(person.last)))
    return display_name(chosen.first, chosen.last)


def source_phrase(group: Group) -> str:
    return ", ".join(SOURCE_LABELS[source] for source in (SOURCE_SHEET, SOURCE_MSL, SOURCE_DB) if source in group.people)


def membership_line(group: Group) -> str:
    details = []
    sheet = group.people.get(SOURCE_SHEET, [])
    msl = group.people.get(SOURCE_MSL, [])
    database = group.people.get(SOURCE_DB, [])

    if sheet:
        years = sorted({person.year for person in sheet if person.year is not None})
        if years:
            text = f"USSF {years[-1]}"
            if any(person.recent for person in sheet):
                text += ", certified in the last 6 months"
            details.append(text)
        else:
            details.append("certification date missing")
        rows = ", ".join(str(person.sheet_row) for person in sheet if person.sheet_row)
        if rows:
            details.append(f"sheet row {rows}" if len(sheet) == 1 else f"sheet rows {rows}")

    if database:
        sessions = sum(person.sessions for person in database)
        years = sorted({person.year for person in database if person.year is not None})
        year_text = "certified " + ", ".join(str(year) for year in years) if years else "no certification year"
        session_word = "session" if sessions == 1 else "sessions"
        org_names = sorted({person.org_label for person in database if person.org_label})
        org_text = f" [{', '.join(org_names)}]" if len(org_names) > 1 else ""
        details.append(f"{year_text}, {sessions} {session_word}{org_text}")

    name = best_name(group)
    if not details:
        return name
    return f"{name} — {'; '.join(details)}"


def _ratio(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def related_reason(left: tuple[str, str], right: tuple[str, str]) -> str | None:
    """Why two different identity keys might still be the same referee."""
    if left == right or left == ("", "") or right == ("", ""):
        return None
    first_a, last_a = left
    first_b, last_b = right
    last_same = last_a == last_b
    nick_a = NICKNAMES.get(first_a, first_a)
    nick_b = NICKNAMES.get(first_b, first_b)

    if last_same and first_a != first_b and nick_a == nick_b:
        return "possible nickname"
    shorter, longer = sorted((first_a, first_b), key=len)
    if (
        last_same
        and shorter != longer
        and longer.startswith(shorter)
        and len(shorter) >= 3
        and len(longer) - len(shorter) <= 8
    ):
        return "one first name extends the other"
    # A one-letter misspelling of a typical last name lands near 0.8.
    if first_a == first_b and not last_same and _ratio(last_a, last_b) >= 0.8:
        return "similar last name"
    if last_same and first_a != first_b and _ratio(first_a, first_b) >= 0.84:
        return "similar first name"
    if _ratio(f"{first_a} {last_a}", f"{first_b} {last_b}") >= 0.92:
        return "similar full name"
    return None


def planned_certification_updates(sheet: list[Person], database: list[Person]) -> list[YearUpdate]:
    """Mentor Database rows whose year_certified is not the spreadsheet's latest USSF year."""
    sheet_years: dict[tuple[str, str], set[int]] = defaultdict(set)
    for person in sheet:
        key = loose_key(person.first, person.last)
        if key != ("", "") and person.year is not None:
            sheet_years[key].add(person.year)

    by_db: dict[tuple[str, str], list[Person]] = defaultdict(list)
    for person in database:
        key = loose_key(person.first, person.last)
        if key != ("", "") and person.db_id is not None and person.year is not None:
            by_db[key].append(person)

    updates = []
    for key, years in sheet_years.items():
        rows = by_db.get(key, [])
        if not rows:
            continue
        target = max(years)
        if target in {person.year for person in rows}:
            continue
        for person in rows:
            if person.year != target:
                updates.append(YearUpdate(
                    db_id=person.db_id,
                    name=display_name(person.first, person.last),
                    old_year=person.year,
                    new_year=target,
                ))
    return sorted(updates, key=lambda item: (item.name, item.db_id))


def apply_certification_updates(updates: list[YearUpdate]) -> None:
    """Write spreadsheet certification years onto the matching Mentor Database rows."""
    if not updates:
        return
    import psycopg

    url = (os.environ.get("db_url") or os.environ.get("DATABASE_URL") or "").strip()
    if not url or url.startswith("sqlite:"):
        abort("Cannot update certification years without a Mentor Database db_url.")
    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE referees SET year_certified = %s WHERE id = %s",
                [(item.new_year, item.db_id) for item in updates],
            )
        connection.commit()


def group_people(sheet: list[Person], msl: list[Person], database: list[Person]) -> list[Group]:
    grouped: dict[tuple[str, str], Group] = {}
    for source, people in ((SOURCE_SHEET, sheet), (SOURCE_MSL, msl), (SOURCE_DB, database)):
        for person in people:
            key = loose_key(person.first, person.last)
            if key == ("", ""):
                continue
            group = grouped.get(key)
            if group is None:
                group = Group(key)
                grouped[key] = group
            group.people.setdefault(source, []).append(person)
    return sorted(grouped.values(), key=lambda group: (group.key[1], group.key[0]))


def _exact_names(people: list[Person]) -> list[tuple[str, str]]:
    return sorted({(person.first, person.last) for person in people})


def analyze(
    sheet: list[Person],
    msl: list[Person],
    database: list[Person],
    extra_conflicts: list[str] | None = None,
    extra_notes: list[str] | None = None,
) -> Analysis:
    groups = group_people(sheet, msl, database)
    conflicts = list(extra_conflicts or [])
    notes = list(extra_notes or [])
    found: list[str] = []

    for source, people in ((SOURCE_SHEET, sheet), (SOURCE_MSL, msl), (SOURCE_DB, database)):
        for person in people:
            if loose_key(person.first, person.last) == ("", ""):
                found.append(f"{SOURCE_LABELS[source]} record {person.stored_first!r} {person.stored_last!r} has no usable first and last name.")

    for group in groups:
        name = best_name(group)
        sheet_rows = group.people.get(SOURCE_SHEET, [])
        db_rows = group.people.get(SOURCE_DB, [])
        exact_by_source = {
            source: _exact_names(people)
            for source, people in group.people.items()
        }
        distinct_exact = {pair for pairs in exact_by_source.values() for pair in pairs}
        if len(distinct_exact) > 1:
            rendered = []
            for source in (SOURCE_SHEET, SOURCE_MSL, SOURCE_DB):
                pairs = exact_by_source.get(source)
                if not pairs:
                    continue
                forms = " or ".join(f"first {first!r}, last {last!r}" for first, last in pairs)
                rendered.append(f"{SOURCE_LABELS[source]} ({forms})")
            message = f"{name} is stored under different first/last splits: " + "; ".join(rendered) + "."
            sheet_exact = set(exact_by_source.get(SOURCE_SHEET, []))
            db_exact = set(exact_by_source.get(SOURCE_DB, []))
            if sheet_exact and db_exact and not sheet_exact <= db_exact:
                message += " The importer looks up the spreadsheet spelling exactly and will insert another Mentor Database row."
            found.append(message)

        sheet_years = {person.year for person in sheet_rows if person.year is not None}
        db_years = {person.year for person in db_rows if person.year is not None}
        if len(sheet_years) > 1 and len(_exact_names(sheet_rows)) > 1:
            rows = ", ".join(str(person.sheet_row) for person in sheet_rows if person.sheet_row)
            notes.append(
                f"{name} has certification years {', '.join(str(year) for year in sorted(sheet_years))} "
                f"on the spreadsheet (rows {rows}). The latest year is compared with Mentor Database."
            )
        if sheet_years and db_years and max(sheet_years) not in db_years:
            found.append(
                f"{name} certification year differs: spreadsheet USSF {max(sheet_years)}, "
                f"Mentor Database {', '.join(str(year) for year in sorted(db_years))}."
            )
        if sheet_years and db_rows and not db_years:
            found.append(f"{name} has spreadsheet USSF {max(sheet_years)} and a blank year_certified in the Mentor Database.")
        if len(db_years) > 1:
            found.append(
                f"{name} has more than one year_certified in the Mentor Database: "
                f"{', '.join(str(year) for year in sorted(db_years))}."
            )

        if any(person.importable for person in sheet_rows) and SOURCE_DB not in group.people:
            dates = ", ".join(sorted({person.cert_text for person in sheet_rows if person.importable and person.cert_text}))
            found.append(f"{name} was certified {dates}, inside the import window, and is not in Mentor Database.")

    by_db_exact: dict[tuple[str, str, int | None], list[Person]] = defaultdict(list)
    for person in database:
        by_db_exact[(person.first, person.last, person.org_id)].append(person)
    for (first, last, _org_id), people in sorted(by_db_exact.items(), key=lambda item: (item[0][1], item[0][0])):
        if len(people) < 2:
            continue
        org = people[0].org_label or "the organization"
        found.append(
            f"{display_name(first, last)} has {len(people)} Mentor Database rows in {org}. "
            "refExists requires exactly one row, so the importer will insert another."
        )

    by_msl_exact: dict[tuple[str, str], list[Person]] = defaultdict(list)
    for person in msl:
        by_msl_exact[(person.first, person.last)].append(person)
    for (first, last), people in sorted(by_msl_exact.items(), key=lambda item: (item[0][1], item[0][0])):
        if len(people) > 1:
            found.append(f"{display_name(first, last)} is listed {len(people)} times on the MySoccerLeague roster.")

    by_sheet_exact: dict[tuple[str, str], list[Person]] = defaultdict(list)
    for person in sheet:
        by_sheet_exact[(person.first, person.last)].append(person)
    for (first, last), people in sorted(by_sheet_exact.items(), key=lambda item: (item[0][1], item[0][0])):
        if len(people) < 2:
            continue
        rows = ", ".join(str(person.sheet_row) for person in people if person.sheet_row)
        years = sorted({person.year for person in people if person.year is not None})
        year_text = ", ".join(str(year) for year in years) if years else "unknown"
        message = f"{display_name(first, last)} is on the spreadsheet {len(people)} times (rows {rows}, USSF {year_text})."
        if len(years) > 1:
            message += " The latest year is compared with Mentor Database."
        notes.append(message)

    current_season = ussf_year(datetime.now())
    sheet_years_by_key = {
        group.key: {person.year for person in group.people.get(SOURCE_SHEET, []) if person.year is not None}
        for group in groups
    }
    for person in database:
        label = display_name(person.first, person.last)
        if (
            person.stored_first != normalize_piece(person.stored_first)
            or person.stored_last != normalize_piece(person.stored_last)
        ):
            found.append(
                f"{label} is stored as {person.stored_first!r} {person.stored_last!r}. "
                "Lookups use the lowercase name, so this capitalization or spacing will not match."
            )
        if person.year is None and not sheet_years_by_key.get(loose_key(person.first, person.last)):
            found.append(f"{label} has no year_certified in the Mentor Database.")
        elif person.year is not None and (person.year < 1990 or person.year > current_season + 1):
            found.append(f"{label} has year_certified {person.year} in the Mentor Database.")

    near_matches = []
    for index, left in enumerate(groups):
        for right in groups[index + 1:]:
            reason = related_reason(left.key, right.key)
            if reason is None:
                continue
            near_matches.append(
                f"{best_name(left)} [{source_phrase(left)}]  ~  {best_name(right)} [{source_phrase(right)}]  ({reason})"
            )

    conflicts.extend(sorted(found))
    return Analysis(
        groups=groups,
        conflicts=conflicts,
        notes=sorted(notes),
        near_matches=near_matches,
        sheet_people=len(sheet),
        msl_people=len(msl),
        db_people=len(database),
    )


def bucket_groups(groups: list[Group]) -> dict[str, list[Group]]:
    buckets = {
        "all": [],
        "sheet_msl": [],
        "sheet_db": [],
        "msl_db": [],
        "sheet": [],
        "msl": [],
        "db": [],
    }
    for group in groups:
        present = group.sources()
        if present == ALL_SOURCES:
            buckets["all"].append(group)
        elif present == frozenset({SOURCE_SHEET, SOURCE_MSL}):
            buckets["sheet_msl"].append(group)
        elif present == frozenset({SOURCE_SHEET, SOURCE_DB}):
            buckets["sheet_db"].append(group)
        elif present == frozenset({SOURCE_MSL, SOURCE_DB}):
            buckets["msl_db"].append(group)
        elif present == frozenset({SOURCE_SHEET}):
            buckets["sheet"].append(group)
        elif present == frozenset({SOURCE_MSL}):
            buckets["msl"].append(group)
        elif present == frozenset({SOURCE_DB}):
            buckets["db"].append(group)
    return buckets


def _section(lines: list[str], title: str, entries: list[str]) -> None:
    lines.append("")
    lines.append(f"{title} ({len(entries)})")
    if not entries:
        lines.append("  (none)")
        return
    for entry in entries:
        lines.append(f"  {entry}")


def year_update_line(item: YearUpdate) -> str:
    return f"{item.name} — year_certified {item.old_year} updated to {item.new_year}"


def render_report(analysis: Analysis, preamble: list[str], updates: list[YearUpdate] | None = None) -> str:
    buckets = bucket_groups(analysis.groups)
    in_two = len(buckets["sheet_msl"]) + len(buckets["sheet_db"]) + len(buckets["msl_db"])
    in_one = len(buckets["sheet"]) + len(buckets["msl"]) + len(buckets["db"])
    lines = list(preamble)
    lines.append("")
    lines.append(f"Distinct referees: {len(analysis.groups)}")
    lines.append(f"In all three: {len(buckets['all'])}")
    lines.append(f"In exactly two: {in_two}")
    lines.append(f"  spreadsheet and MySoccerLeague: {len(buckets['sheet_msl'])}")
    lines.append(f"  spreadsheet and Mentor Database: {len(buckets['sheet_db'])}")
    lines.append(f"  MySoccerLeague and Mentor Database: {len(buckets['msl_db'])}")
    lines.append(f"In exactly one: {in_one}")
    lines.append(f"  spreadsheet: {len(buckets['sheet'])}")
    lines.append(f"  MySoccerLeague: {len(buckets['msl'])}")
    lines.append(f"  Mentor Database: {len(buckets['db'])}")
    lines.append(f"Updated certification years: {len(updates or [])}")
    lines.append(f"Conflicts: {len(analysis.conflicts)}")
    lines.append(f"Possible alternate names: {len(analysis.near_matches)}")
    lines.append(f"Notes: {len(analysis.notes)}")

    _section(lines, "In all three", [membership_line(group) for group in buckets["all"]])
    _section(lines, "In spreadsheet and MySoccerLeague", [membership_line(group) for group in buckets["sheet_msl"]])
    _section(lines, "In spreadsheet and Mentor Database", [membership_line(group) for group in buckets["sheet_db"]])
    _section(lines, "In MySoccerLeague and Mentor Database", [membership_line(group) for group in buckets["msl_db"]])
    _section(lines, "Only in the spreadsheet", [membership_line(group) for group in buckets["sheet"]])
    _section(lines, "Only in MySoccerLeague", [membership_line(group) for group in buckets["msl"]])
    _section(lines, "Only in Mentor Database", [membership_line(group) for group in buckets["db"]])
    _section(lines, "Updated Mentor Database certification years", [year_update_line(item) for item in (updates or [])])
    _section(lines, "Conflicts", analysis.conflicts)
    _section(lines, "Possible same person under different names", analysis.near_matches)
    _section(lines, "Notes", analysis.notes)
    lines.append("")
    return "\n".join(lines)


def analysis_to_json(analysis: Analysis, preamble: list[str], updates: list[YearUpdate] | None = None) -> dict:
    buckets = bucket_groups(analysis.groups)

    def dump(groups: list[Group]) -> list[dict]:
        return [
            {
                "name": best_name(group),
                "first": group.key[0],
                "last": group.key[1],
                "sources": [SOURCE_LABELS[source] for source in (SOURCE_SHEET, SOURCE_MSL, SOURCE_DB) if source in group.people],
                "line": membership_line(group),
            }
            for group in groups
        ]

    return {
        "preamble": preamble,
        "distinct": len(analysis.groups),
        "in_all_three": dump(buckets["all"]),
        "in_two": {
            "spreadsheet_and_mysoccerleague": dump(buckets["sheet_msl"]),
            "spreadsheet_and_cockroach": dump(buckets["sheet_db"]),
            "mysoccerleague_and_cockroach": dump(buckets["msl_db"]),
        },
        "in_one": {
            "spreadsheet": dump(buckets["sheet"]),
            "mysoccerleague": dump(buckets["msl"]),
            "cockroach": dump(buckets["db"]),
        },
        "updated_certification_years": [
            {
                "name": item.name,
                "old_year": item.old_year,
                "new_year": item.new_year,
            }
            for item in (updates or [])
        ],
        "conflicts": analysis.conflicts,
        "near_matches": analysis.near_matches,
        "notes": analysis.notes,
    }


def has_problems(analysis: Analysis) -> bool:
    incomplete = any(group.sources() != ALL_SOURCES for group in analysis.groups)
    return incomplete or bool(analysis.conflicts or analysis.near_matches)


def _cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    return row[index]


def load_service_account() -> dict:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        abort("Set GOOGLE_SERVICE_ACCOUNT_JSON to the service account JSON or a path to that file.")
    try:
        if raw.startswith("{"):
            return json.loads(raw)
        path = Path(raw)
        if path.is_file():
            return json.loads(path.read_text())
    except json.JSONDecodeError as ex:
        abort(f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {ex}")
    abort("GOOGLE_SERVICE_ACCOUNT_JSON must be the JSON contents or a path to that file.")


def load_spreadsheet() -> tuple[list[Person], list[str], list[str]]:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(load_service_account(), scope)
    client = gspread.authorize(credentials)
    worksheet = client.open(SPREADSHEET_NAME).worksheet(WORKSHEET_NAME)
    rows = worksheet.get_all_values()
    if not rows:
        raise RuntimeError(f"{SPREADSHEET_NAME} / {WORKSHEET_NAME} is empty.")

    headers = rows[0]
    name_index = NAME_COLUMN - 1
    date_index = DATE_COLUMN - 1
    name_header = _cell(headers, name_index) or "(no header)"
    date_header = _cell(headers, date_index) or "(no header)"
    now = datetime.now()
    people: list[Person] = []
    issues: list[str] = []

    for row_number, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        raw_name = _cell(row, name_index).strip()
        raw_date = _cell(row, date_index).strip()
        parsed = parse_sheet_name(raw_name)
        if parsed is None:
            if raw_name:
                issues.append(f"Spreadsheet row {row_number}: could not read a referee name from {raw_name!r}.")
            else:
                issues.append(f"Spreadsheet row {row_number}: name cell is empty.")
            continue

        first, last, comma_form = parsed
        if not comma_form:
            issues.append(
                f"Spreadsheet row {row_number}: {raw_name!r} has no comma. Read as First Last. "
                "The importer skips names it cannot split on a comma."
            )

        cert_date = parse_cert_date(raw_date)
        if not raw_date:
            issues.append(f"Spreadsheet row {row_number}: {display_name(first, last)} has no certification date, so the importer skips this row.")
        elif cert_date is None:
            issues.append(
                f"Spreadsheet row {row_number}: certification date {raw_date!r} for {display_name(first, last)} "
                "is not m/d/YYYY, so the importer skips this row."
            )
        elif cert_date > now:
            issues.append(
                f"Spreadsheet row {row_number}: certification date {raw_date} for {display_name(first, last)} "
                "is in the future, so the importer skips this row."
            )

        recent = bool(cert_date and is_recent_certification(cert_date, now))
        people.append(Person(
            source=SOURCE_SHEET,
            first=first,
            last=last,
            year=ussf_year(cert_date) if cert_date else None,
            recent=recent,
            importable=comma_form and recent,
            sheet_row=row_number,
            cert_text=raw_date,
            stored_first=raw_name,
            stored_last="",
        ))

    detail = [
        f"Spreadsheet: {SPREADSHEET_NAME} / {WORKSHEET_NAME}",
        f"  Name column {column_letter(name_index)} ({name_header}), certification column {column_letter(date_index)} ({date_header}).",
        f"  {len(rows) - 1} response rows, {len(people)} readable referees.",
        "  The importer inserts a row only when the name is Last, First, the date is m/d/YYYY, and the date is in the last 182 days.",
    ]
    return people, issues, detail


def _canonicalize_msl_name(full_name: str) -> str:
    text = full_name.replace("\xa0", " ").replace("[VYS]", "").replace("[vys]", "")
    text = re.sub(r"\s+", " ", text).strip()
    # Same exception as MySoccerLeague.getAllReferees.
    if text.startswith("Marco"):
        return "Marco Tulio Montanes"
    return text


def load_mysoccerleague() -> tuple[list[Person], list[str], list[str]]:
    from refWebSites import MySoccerLeague, split_referee_name

    print(
        "Opening a browser window for MySoccerLeague. "
        "If Cloudflare asks, check \"Verify you are human\" and leave the window open.",
        file=sys.stderr,
    )
    site = MySoccerLeague()
    try:
        page = site._browser.open(site._referee_roster_url())
    finally:
        site.close()

    title = page.soup.title.string if page.soup.title and page.soup.title.string else ""
    if "500" in title or "Internal Server Error" in title:
        raise RuntimeError(f"Referee roster page returned {title} ({page.url})")
    if "Guest Home" in title:
        raise RuntimeError(f"Referee roster opened the guest home page ({page.url})")

    entries = page.soup.find_all("tr", {"class": "trstyle1"}) + page.soup.find_all("tr", {"class": "trstyle2"})
    people: list[Person] = []
    issues: list[str] = []
    short_rows = 0
    for entry in entries:
        cells = entry.find_all("td")
        if len(cells) < 5:
            short_rows += 1
            continue
        raw_name = _canonicalize_msl_name(cells[4].text)
        if not raw_name or raw_name.lower() in {"none", "not used"}:
            continue
        try:
            first, last = split_referee_name(raw_name)
        except ValueError:
            issues.append(f"MySoccerLeague name {raw_name!r} could not be split.")
            continue
        first = normalize_piece(first)
        last = normalize_piece(last)
        people.append(Person(
            source=SOURCE_MSL,
            first=first,
            last=last,
            stored_first=raw_name,
            stored_last="",
        ))

    if short_rows:
        issues.append(f"{short_rows} MySoccerLeague roster rows had no name cell and were skipped.")
    detail = [
        "MySoccerLeague: show-all referee roster",
        f"  {len(entries)} roster rows, {len(people)} readable referees.",
    ]
    return people, issues, detail


def _is_vys(org: dict) -> bool:
    slug = (org.get("slug") or "").lower()
    name = (org.get("name") or "").lower()
    return slug == "vys" or name == "vys" or "vys" in name.split()


def select_organization(orgs: list[dict], selector: str | None, all_orgs: bool) -> dict | None:
    if all_orgs:
        return None
    if selector is None:
        matches = [org for org in orgs if _is_vys(org)]
        label = "VYS"
    elif selector.isdigit():
        matches = [org for org in orgs if str(org["id"]) == selector]
        label = selector
    else:
        wanted = selector.lower()
        matches = [org for org in orgs if org["slug"].lower() == wanted or org["name"].lower() == wanted]
        if not matches:
            matches = [org for org in orgs if wanted in org["slug"].lower() or wanted in org["name"].lower()]
        label = selector
    listing = "\n".join(f"  {org['name']} ({org['slug']})" for org in orgs) or "  (none)"
    if len(matches) == 1:
        return matches[0]
    if not matches:
        abort(f"No organization matches {label!r}. Organizations:\n{listing}")
    abort(f"{label!r} matches more than one organization. Pass --org with a name or slug:\n{listing}")


def cross_org_notes(people: list[Person]) -> list[str]:
    by_key: dict[tuple[str, str], list[Person]] = defaultdict(list)
    for person in people:
        key = loose_key(person.first, person.last)
        if key != ("", ""):
            by_key[key].append(person)
    notes = []
    for key, group in sorted(by_key.items(), key=lambda item: (item[0][1], item[0][0])):
        orgs = {person.org_label for person in group}
        if len(orgs) < 2:
            continue
        detail = ", ".join(sorted(orgs))
        notes.append(f"{display_name(*key)} is in more than one organization: {detail}.")
    return notes


def load_cockroach(selector: str | None, all_orgs: bool) -> tuple[list[Person], list[str], list[str], list[str]]:
    """Return referees in scope, row issues, cross-organization notes, and report lines."""
    import psycopg

    url = (os.environ.get("db_url") or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        abort("Set db_url to the Mentor Database connection string.")
    if url.startswith("sqlite:"):
        abort("db_url points at SQLite. This check reads the Mentor Database.")

    query = """
        SELECT r.id,
               COALESCE(r.firstname, ''),
               COALESCE(r.lastname, ''),
               r.year_certified,
               r.organization_id,
               COALESCE(o.name, ''),
               COALESCE(o.slug, ''),
               (SELECT COUNT(*) FROM mentor_sessions ms WHERE ms.mentee = r.id)
        FROM referees r
        LEFT JOIN organizations o ON o.id = r.organization_id
        ORDER BY o.name, r.lastname, r.firstname, r.id
    """
    with psycopg.connect(url) as connection:
        connection.read_only = True
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, name, COALESCE(slug, '') FROM organizations ORDER BY name")
            organizations = [
                {"id": row[0], "name": row[1], "slug": row[2]}
                for row in cursor.fetchall()
            ]
            cursor.execute(query)
            raw_rows = cursor.fetchall()

    everyone: list[Person] = []
    issues: list[str] = []
    for row in raw_rows:
        db_id, stored_first, stored_last, year, org_id, org_name, org_slug, sessions = row
        first = normalize_piece(stored_first)
        last = normalize_piece(stored_last)
        if loose_key(first, last) == ("", ""):
            issues.append(f"Mentor Database referee {stored_first!r} {stored_last!r} has no usable name.")
            continue
        year_value = int(year) if year is not None else None
        label = org_name or org_slug or (str(org_id) if org_id is not None else "")
        everyone.append(Person(
            source=SOURCE_DB,
            first=first,
            last=last,
            year=year_value,
            db_id=int(db_id),
            sessions=int(sessions or 0),
            org_id=int(org_id) if org_id is not None else None,
            org_label=label,
            stored_first=stored_first,
            stored_last=stored_last,
        ))

    notes = cross_org_notes(everyone)
    org = select_organization(organizations, selector, all_orgs)
    if org is None:
        scoped = everyone
        scope_text = "all organizations"
    else:
        scoped = [person for person in everyone if person.org_id == org["id"]]
        scope_text = f"{org['name']} (slug {org['slug'] or 'none'})"
    detail = [
        f"Mentor Database: referees in {scope_text}",
        f"  {len(scoped)} referees in scope, {len(everyone)} in the table, {len(organizations)} organizations.",
    ]
    return scoped, issues, notes, detail


def require_environment() -> None:
    missing = [
        name for name in ("GOOGLE_SERVICE_ACCOUNT_JSON", "mslUsername", "mslPassword", "db_url")
        if not os.environ.get(name)
    ]
    if missing:
        abort("Missing environment variables: " + ", ".join(missing))


def build_preamble(sheet_detail: list[str], msl_detail: list[str], db_detail: list[str]) -> list[str]:
    lines = [
        "Referee roster integrity",
        "Identity is the first word of the first name plus the last word of the last name.",
        "Middle names, suffixes (Jr, Sr, II, III, IV), periods, and letter case are ignored.",
        "",
    ]
    lines.extend(sheet_detail)
    lines.append("")
    lines.extend(msl_detail)
    lines.append("")
    lines.extend(db_detail)
    return lines


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare referee rosters across the spreadsheet, MySoccerLeague, and Mentor Database.")
    parser.add_argument("--org", help="Organization id, slug, or name. Default: VYS.")
    parser.add_argument("--all-orgs", action="store_true", help="Compare every Mentor Database organization. The spreadsheet and MySoccerLeague lists are still the VYS roster.")
    parser.add_argument("--output", help="Also write the text report to this path.")
    parser.add_argument("--json", help="Write a JSON copy of the report to this path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    output_path = Path(args.output).resolve() if args.output else None
    json_path = Path(args.json).resolve() if args.json else None
    require_environment()

    print("Reading the certification spreadsheet...", file=sys.stderr)
    sheet, sheet_issues, sheet_detail = load_spreadsheet()
    print("Reading the MySoccerLeague roster...", file=sys.stderr)
    msl, msl_issues, msl_detail = load_mysoccerleague()
    print("Reading Mentor Database referees...", file=sys.stderr)
    scoped, db_issues, db_notes, db_detail = load_cockroach(args.org, args.all_orgs)

    if not sheet:
        sheet_issues.append("The spreadsheet produced no readable referees.")
    if not msl:
        msl_issues.append("MySoccerLeague produced no readable referees.")
    if not scoped:
        db_issues.append("Mentor Database produced no readable referees in scope.")

    updates = planned_certification_updates(sheet, scoped)
    if updates:
        print(f"Updating {len(updates)} Mentor Database certification years from the spreadsheet...", file=sys.stderr)
        apply_certification_updates(updates)
        updated_ids = {item.db_id: item.new_year for item in updates}
        for person in scoped:
            if person.db_id in updated_ids:
                person.year = updated_ids[person.db_id]

    analysis = analyze(
        sheet,
        msl,
        scoped,
        extra_conflicts=[*sheet_issues, *msl_issues, *db_issues],
        extra_notes=db_notes,
    )
    preamble = build_preamble(sheet_detail, msl_detail, db_detail)
    if args.all_orgs:
        preamble.append("  The spreadsheet and MySoccerLeague roster are the VYS lists, so referees from other organizations show up as Mentor Database only.")
    report = render_report(analysis, preamble, updates)
    print(report)
    if output_path is not None:
        output_path.write_text(report)
        print(f"Wrote {output_path}", file=sys.stderr)
    if json_path is not None:
        json_path.write_text(json.dumps(analysis_to_json(analysis, preamble, updates), indent=2) + "\n")
        print(f"Wrote {json_path}", file=sys.stderr)
    return 1 if has_problems(analysis) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as ex:
        print(f"Could not finish the referee integrity check: {ex}", file=sys.stderr)
        sys.exit(2)
