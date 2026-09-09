"""
Filesystem cache for assignment-provider data (match schedule, workload).

Intended for a shared volume on Fly.io (e.g. /data/cache) written by sync_worker
and read by the NiceGUI app process.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

MATCH_SCHEDULE_FILE = 'match_schedule.json'
WORKLOAD_OUTPUT_FILE = 'workload_output.txt'
WORKLOAD_RESULTS_FILE = 'workload_results.json'
META_FILE = 'meta.json'


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def allow_live_fetch() -> bool:
    """When false, the UI only reads cached files (production / worker mode)."""
    return _env_truthy('ALLOW_LIVE_FETCH', default=False)


def get_cache_dir() -> Path:
    """
    Root directory for per-organization cache files.

    DATA_CACHE_DIR overrides everything (use /data/cache on Fly with a volume mount).
  Fallback for local dev: <repo>/.data/cache
    """
    configured = os.environ.get('DATA_CACHE_DIR', '').strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / '.data' / 'cache'


def org_dir(organization_id: int) -> Path:
    return get_cache_dir() / f'org_{organization_id}'


def _atomic_write(path: Path, write_fn) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    write_fn(tmp)
    tmp.replace(path)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_meta(organization_id: int) -> Optional[dict]:
    path = org_dir(organization_id) / META_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return None


def save_meta(organization_id: int, **fields: Any) -> dict:
    meta = load_meta(organization_id) or {'organization_id': organization_id}
    meta.update(fields)
    meta['updated_at'] = _utc_now_iso()

    def _write(tmp: Path) -> None:
        tmp.write_text(json.dumps(meta, indent=2), encoding='utf-8')

    _atomic_write(org_dir(organization_id) / META_FILE, _write)
    return meta


def save_match_schedule(organization_id: int, data: dict) -> None:
    def _write(tmp: Path) -> None:
        tmp.write_text(json.dumps(data), encoding='utf-8')

    _atomic_write(org_dir(organization_id) / MATCH_SCHEDULE_FILE, _write)
    save_meta(
        organization_id,
        match_schedule_updated_at=_utc_now_iso(),
        match_schedule_error=None,
        match_schedule_dates=len(data) if data else 0,
    )


def load_match_schedule(organization_id: int) -> Optional[dict]:
    path = org_dir(organization_id) / MATCH_SCHEDULE_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return None


def has_match_schedule(organization_id: int) -> bool:
    return load_match_schedule(organization_id) is not None


def save_workload(organization_id: int, output: str, results: dict) -> None:
    org_path = org_dir(organization_id)

    def _write_output(tmp: Path) -> None:
        tmp.write_text(output or '', encoding='utf-8')

    def _write_results(tmp: Path) -> None:
        tmp.write_text(json.dumps(results), encoding='utf-8')

    _atomic_write(org_path / WORKLOAD_OUTPUT_FILE, _write_output)
    _atomic_write(org_path / WORKLOAD_RESULTS_FILE, _write_results)
    save_meta(
        organization_id,
        workload_updated_at=_utc_now_iso(),
        workload_error=None,
    )


def load_workload(organization_id: int) -> Optional[tuple[str, dict]]:
    org_path = org_dir(organization_id)
    output_path = org_path / WORKLOAD_OUTPUT_FILE
    results_path = org_path / WORKLOAD_RESULTS_FILE
    if not output_path.is_file() and not results_path.is_file():
        return None
    try:
        output = output_path.read_text(encoding='utf-8') if output_path.is_file() else ''
        results = json.loads(results_path.read_text(encoding='utf-8')) if results_path.is_file() else {}
        return output, results
    except (json.JSONDecodeError, OSError):
        return None


def has_workload(organization_id: int) -> bool:
    return load_workload(organization_id) is not None


def record_sync_error(organization_id: int, *, match_error: str = None, workload_error: str = None) -> None:
    fields = {}
    if match_error is not None:
        fields['match_schedule_error'] = match_error
        fields['match_schedule_updated_at'] = _utc_now_iso()
    if workload_error is not None:
        fields['workload_error'] = workload_error
        fields['workload_updated_at'] = _utc_now_iso()
    if fields:
        save_meta(organization_id, **fields)
