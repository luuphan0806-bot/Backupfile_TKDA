from __future__ import annotations

from pathlib import Path
import os
import shutil

APP_NAME = "Scan Backup Manager"
DEFAULT_BACKUP_ROOT = r"D:\BACKUP"
DEFAULT_POLL_INTERVAL_SECONDS = 300
DEFAULT_STABILITY_WAIT_SECONDS = 20
DEFAULT_DB_PATH = Path("data") / "scan_backup_manager.sqlite3"
DEFAULT_REPORTS_DIR = Path("data") / "reports"
DEFAULT_STAGING_DIR = Path("data") / "staging"
DEFAULT_CONFLICT_ARCHIVE_DIR = Path("data") / "conflict_archive"


def runtime_data_dir() -> Path:
    override = os.environ.get("SCAN_BACKUP_DATA_DIR")
    if override:
        return Path(override)
    program_data = os.environ.get("PROGRAMDATA")
    return Path(program_data) / "ScanBackupManager" if program_data else Path("data")


def runtime_db_path() -> Path:
    target = runtime_data_dir() / "scan_backup_manager.sqlite3"
    target.parent.mkdir(parents=True, exist_ok=True)
    legacy = DEFAULT_DB_PATH
    if (
        not os.environ.get("SCAN_BACKUP_DATA_DIR")
        and not target.exists()
        and legacy.exists()
        and target.resolve() != legacy.resolve()
    ):
        shutil.copy2(legacy, target)
    return target

STATUS_DISCOVERED = "DISCOVERED"
STATUS_INVALID_STRUCTURE = "INVALID_STRUCTURE"
STATUS_WAITING_STABLE = "WAITING_STABLE"
STATUS_COPYING = "COPYING"
STATUS_COPIED = "COPIED"
STATUS_VERIFIED_SIZE = "VERIFIED_SIZE"
STATUS_HASH_PENDING = "HASH_PENDING"
STATUS_VERIFIED_HASH = "VERIFIED_HASH"
STATUS_LOCKED = "LOCKED"
STATUS_ALREADY_EXISTS = "ALREADY_EXISTS"
STATUS_CONFLICT = "CONFLICT"
STATUS_ERROR = "ERROR"

FINAL_OK_STATUSES = {
    STATUS_VERIFIED_SIZE,
    STATUS_HASH_PENDING,
    STATUS_VERIFIED_HASH,
    STATUS_LOCKED,
    STATUS_ALREADY_EXISTS,
}

# Single source of truth for "counts as backed up" — used by the SQL
# backup_summary, scan/check page counting, and mapfile reconcile alike.
# Includes VERIFIED_SIZE so every consumer agrees with the BACKED_UP
# semantics of the system mapfile summary.
COUNTABLE_BACKUP_STATUSES = frozenset(FINAL_OK_STATUSES)
