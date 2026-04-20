#!/usr/bin/env python3
"""
Read venvRequirements.txt (one PEP 508-ish requirement per line) and query the
current Python environment for each package (importlib.metadata).

With --sync-newer, rewrite lines pinned with == when the installed version is
greater than the pinned version (PEP 440 compare via packaging).
"""
from __future__ import annotations

import argparse
import importlib.metadata
import re
import sys
from pathlib import Path

try:
    from packaging.version import Version
except ImportError:  # pragma: no cover
    Version = None  # type: ignore[misc, assignment]


def parse_requirement_line(line: str) -> tuple[str, str] | None:
    """
    Parse a single non-comment requirement line.
    Returns (distribution_name, version_or_constraint_from_file) or None to skip.
    The file column is the remainder after the name (e.g. '==25.1.0', '>=1,<2') or '-'.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "#" in line:
        line = line[: line.index("#")].strip()
    line = line.split(";", 1)[0].strip()
    if not line:
        return None
    # Name, optional [extras], then version specifiers / whitespace
    m = re.match(
        r"^([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[^\]]+\])?\s*(.*)$",
        line,
    )
    if not m:
        return None
    name = m.group(1)
    rest = m.group(2).strip()
    file_spec = rest if rest else "-"
    return name, file_spec


def find_installed_version(name: str) -> tuple[str | None, str | None]:
    """
    Return (canonical_name, version) or (None, None) if not installed.
    Match is case-insensitive on distribution Name metadata.
    """
    try:
        v = importlib.metadata.version(name)
        return name, v
    except importlib.metadata.PackageNotFoundError:
        pass

    lowered = name.lower()
    for dist in importlib.metadata.distributions():
        meta_name = dist.metadata.get("Name")
        if meta_name and meta_name.lower() == lowered:
            return meta_name, dist.version

    return None, None


def _pinned_equals_version(file_spec: str) -> str | None:
    m = re.match(r"^==\s*(.+)$", file_spec.strip())
    return m.group(1).strip() if m else None


def sync_newer_pins(path: Path) -> int:
    """Rewrite == pins to installed version when installed > pinned. Returns exit code."""
    if Version is None:
        print("Error: the 'packaging' package is required for --sync-newer", file=sys.stderr)
        print("  pip install packaging", file=sys.stderr)
        return 1

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    changed = 0
    for raw in lines:
        if raw.strip().startswith("#") or not raw.strip():
            out.append(raw)
            continue
        parsed = parse_requirement_line(raw)
        if parsed is None:
            out.append(raw)
            continue
        name, file_spec = parsed
        pin = _pinned_equals_version(file_spec)
        if pin is None:
            out.append(raw)
            continue
        _, installed = find_installed_version(name)
        if installed is None:
            out.append(raw)
            continue
        try:
            if Version(installed) > Version(pin):
                lead = len(raw) - len(raw.lstrip(" \t"))
                prefix = raw[:lead]
                if raw.endswith("\r\n"):
                    nl = "\r\n"
                elif raw.endswith("\n"):
                    nl = "\n"
                elif raw.endswith("\r"):
                    nl = "\r"
                else:
                    nl = ""
                out.append(f"{prefix}{name}=={installed}{nl}")
                changed += 1
                print(f"updated {name}: =={pin} -> =={installed}")
            else:
                out.append(raw)
        except Exception as e:  # noqa: BLE001
            print(f"skip {name}: {e}", file=sys.stderr)
            out.append(raw)

    if changed:
        path.write_text("".join(out), encoding="utf-8")
        print(f"\nWrote {changed} update(s) to {path.resolve()}")
    else:
        print("No == pins needed updating (none installed newer than file).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parent / "venvRequirements.txt",
        help="Requirements file (default: venvRequirements.txt next to this script)",
    )
    parser.add_argument(
        "--sync-newer",
        action="store_true",
        help="Rewrite == pins to match installed when installed version is greater",
    )
    args = parser.parse_args()
    path: Path = args.file

    if not path.is_file():
        print(f"Error: not a file: {path}", file=sys.stderr)
        return 1

    if args.sync_newer:
        return sync_newer_pins(path)

    print(f"Python: {sys.executable}")
    print(f"File:   {path.resolve()}")
    print()

    rows: list[tuple[str, str, str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        parsed = parse_requirement_line(raw)
        if parsed is None:
            continue
        name, file_spec = parsed
        canon, installed = find_installed_version(name)
        if installed is None:
            rows.append((name, file_spec, "-", "NOT INSTALLED"))
        else:
            rows.append((name, file_spec, installed, canon or name))

    w0 = max(len(r[0]) for r in rows) if rows else 10
    w1 = max(len(r[1]) for r in rows) if rows else 12
    w2 = max(len(r[2]) for r in rows) if rows else 10
    header = (
        f"{'Requirement name':<{w0}}  "
        f"{'From file':<{w1}}  "
        f"{'Installed':<{w2}}  "
        f"Distribution name"
    )
    print(header)
    print("-" * len(header))
    for name, file_spec, installed, canon in rows:
        print(f"{name:<{w0}}  {file_spec:<{w1}}  {installed:<{w2}}  {canon}")

    missing = sum(1 for r in rows if r[2] == "-")
    if missing:
        print(f"\n{missing} package(s) not found in this environment.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
