from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from .constants import runtime_data_dir, runtime_db_path


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _unique_path(path: Path) -> Path:
    candidate = path
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        counter += 1
    return candidate


def _assert_valid_sqlite(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file DB: {path}")
    try:
        with sqlite3.connect(path) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"File không phải SQLite hợp lệ: {path}") from exc
    if not result or str(result[0]).lower() != "ok":
        raise ValueError(f"SQLite integrity_check failed: {result[0] if result else 'unknown'}")


def create_database_snapshot(
    db_path: Path | str | None = None,
    *,
    backup_dir: Path | str | None = None,
    label: str = "manual",
) -> Path:
    """Create a consistent SQLite snapshot with the sqlite backup API.

    Copying the main .sqlite3 file alone is unsafe when WAL mode is active.
    This function asks SQLite to produce a coherent backup even while the app
    has recently written to the database.
    """
    source = Path(db_path) if db_path is not None else runtime_db_path()
    _assert_valid_sqlite(source)
    target_dir = Path(backup_dir) if backup_dir is not None else runtime_data_dir() / "db_backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    clean_label = "".join(char if char.isalnum() or char in "-_" else "_" for char in label).strip("_")
    clean_label = clean_label or "manual"
    target = _unique_path(target_dir / f"{source.stem}-{clean_label}-{_timestamp()}.sqlite3")
    with sqlite3.connect(source) as source_conn:
        with sqlite3.connect(target) as target_conn:
            source_conn.backup(target_conn)
    _assert_valid_sqlite(target)
    return target


def restore_database_snapshot(
    snapshot_path: Path | str,
    db_path: Path | str | None = None,
    *,
    backup_dir: Path | str | None = None,
) -> Path | None:
    """Restore a validated snapshot and preserve the current DB first.

    The app/service should be stopped before this is called in production.
    Return value is the pre-restore snapshot path when a current DB existed.
    """
    snapshot = Path(snapshot_path)
    _assert_valid_sqlite(snapshot)
    target = Path(db_path) if db_path is not None else runtime_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    pre_restore: Path | None = None
    if target.exists() and target.stat().st_size > 0:
        pre_restore = create_database_snapshot(
            target,
            backup_dir=backup_dir,
            label="pre_restore",
        )
        with sqlite3.connect(target) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    with sqlite3.connect(snapshot) as source_conn:
        with sqlite3.connect(target) as target_conn:
            source_conn.backup(target_conn)
    for suffix in ("-wal", "-shm"):
        sidecar = target.with_name(f"{target.name}{suffix}")
        if sidecar.exists():
            try:
                sidecar.unlink()
            except PermissionError:
                pass
    _assert_valid_sqlite(target)
    return pre_restore
