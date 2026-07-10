from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import shutil
import sqlite3
import unicodedata
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .constants import (
    COUNTABLE_BACKUP_STATUSES,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_STABILITY_WAIT_SECONDS,
    FINAL_OK_STATUSES,
)
from .models import (
    Client,
    DirectoryLevel,
    MapfileProfile,
    PaperFormat,
    JobType,
    Personnel,
    Project,
    ProjectSettings,
    ProjectTask,
)


SCHEMA_VERSION = 6
DEFAULT_ADMIN_PASSWORD = "Admin@123"
PBKDF2_ITERATIONS = 600_000

DEFAULT_SETTINGS_KEYS = {
    "poll_interval_seconds": "default_poll_interval_seconds",
    "stability_wait_seconds": "default_stability_wait_seconds",
    "numeric_sequence_check": "default_numeric_sequence_check",
}
PAPER_SCAN_STATUSES = {
    "UNKNOWN",
    "NOT_PRESENT",
    "PENDING_SCAN",
    "SCANNED",
    "CHECKED",
    "RESCAN_REQUIRED",
}
RECORD_WORKFLOW_STATUSES = {
    "NOT_STARTED",
    "SCANNING",
    "PENDING_PAPER",
    "PENDING_CHECK",
    "COMPLETED",
    "RESCAN_REQUIRED",
}
MANUAL_RECORD_STATUSES = {"COMPLETED", "RESCAN_REQUIRED"}
# SQL fragment kept in sync with constants.COUNTABLE_BACKUP_STATUSES (values are
# trusted module constants, safe to inline).
_COUNTABLE_SQL = ", ".join(f"'{status}'" for status in sorted(COUNTABLE_BACKUP_STATUSES))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_system_date(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"{label} phải có định dạng dd/mm/yyyy.")


def record_key_from_relative_path(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").strip("/")
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[0] if "/" in normalized else normalized


def record_key_from_expected_path(expected_path: str) -> str:
    parent = record_key_from_relative_path(expected_path)
    parts = parent.split("/")
    return "/".join(parts[1:]) if len(parts) > 1 else parent


def _strip_diacritics(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def record_key_from_task_description(description: str) -> str:
    """Legacy fallback: extract the record key from the human-readable task
    description ("Thư mục hồ sơ: <key>"). New tasks carry record_key as a
    dedicated column; this parse only serves rows created before schema v6."""
    for line in str(description or "").splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        if "thu muc ho so" in _strip_diacritics(label.lower()):
            return value.strip().replace("\\", "/").strip("/")
    return ""


def _password_hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    ).hex()


class Database:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.migration_backup_path: Path | None = None
        self.initialize()

    # ------------------------------------------------------------------
    # Schema bootstrap / migration
    # ------------------------------------------------------------------
    def _read_existing_schema_version(self) -> int | None:
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return None
        try:
            with closing(sqlite3.connect(self.db_path)) as conn:
                has_tables = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1"
                ).fetchone()
                if not has_tables:
                    return None
                has_meta = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'"
                ).fetchone()
                if not has_meta:
                    return None
                row = conn.execute(
                    "SELECT value FROM app_meta WHERE key='schema_version'"
                ).fetchone()
                return int(row[0]) if row else None
        except (sqlite3.DatabaseError, ValueError):
            return None

    def _timestamped_backup_path(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.db_path.with_name(f"{self.db_path.name}.bak-{stamp}")
        counter = 1
        while backup.exists():
            backup = self.db_path.with_name(f"{self.db_path.name}.bak-{stamp}-{counter}")
            counter += 1
        return backup

    def initialize(self) -> None:
        current_version = self._read_existing_schema_version()

        if self.db_path.exists() and self.db_path.stat().st_size > 0 and current_version is None:
            # Pre-versioned or unreadable database: no reliable migration path.
            # Preserve a copy for manual recovery, then start fresh.
            backup = self._timestamped_backup_path()
            shutil.copy2(self.db_path, backup)
            self.db_path.unlink()
            self.migration_backup_path = backup

        needs_migration = current_version is not None and current_version < SCHEMA_VERSION
        if needs_migration:
            # Non-destructive: copy only, keep migrating the original file in place.
            self.migration_backup_path = self._timestamped_backup_path()
            shutil.copy2(self.db_path, self.migration_backup_path)

        with self.connect() as conn:
            self._create_schema(conn)
            if needs_migration and current_version is not None and current_version < 3:
                self._migrate_v2_to_v3(conn)
            # Idempotent so partially upgraded databases can repair themselves.
            self._migrate_to_v5(conn)
            self._migrate_to_v6(conn, current_version)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_backup_project_record
                ON backup_files(project_id, record_key, status)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_map_rows_record
                ON mapfile_rows(import_id, record_key)
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO app_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._ensure_defaults(conn)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 10000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_meta(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admin_auth(
                id INTEGER PRIMARY KEY CHECK(id = 1),
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                must_change_password INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects(
                id INTEGER PRIMARY KEY,
                project_code TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                backup_root TEXT NOT NULL,
                staging_dir TEXT NOT NULL,
                conflict_archive_dir TEXT NOT NULL,
                reports_dir TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_settings(
                project_id INTEGER PRIMARY KEY,
                poll_interval_seconds INTEGER NOT NULL DEFAULT 300,
                stability_wait_seconds INTEGER NOT NULL DEFAULT 20,
                numeric_sequence_check INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS project_directory_levels(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                validation_type TEXT NOT NULL
                    CHECK(validation_type IN ('YEAR4', 'ENUM', 'INTEGER', 'TEXT')),
                allowed_values_json TEXT NOT NULL DEFAULT '[]',
                show_in_mapfile INTEGER NOT NULL DEFAULT 1,
                mapfile_position INTEGER NOT NULL DEFAULT 0,
                require_catalog_selection INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, position)
            );

            CREATE TABLE IF NOT EXISTS clients(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                client_code TEXT NOT NULL,
                share_path TEXT NOT NULL,
                staff_name TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                notes TEXT NOT NULL DEFAULT '',
                last_seen_at TEXT,
                last_backup_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, client_code)
            );

            CREATE TABLE IF NOT EXISTS project_personnel(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                personnel_code TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role_name TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, personnel_code)
            );

            CREATE TABLE IF NOT EXISTS project_tasks(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                task_code TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                assignee_id INTEGER NOT NULL,
                due_date TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL DEFAULT 'NORMAL'
                    CHECK(priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')),
                status TEXT NOT NULL DEFAULT 'NEW'
                    CHECK(status IN ('NEW', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')),
                record_key TEXT NOT NULL DEFAULT '',
                task_kind TEXT NOT NULL DEFAULT ''
                    CHECK(task_kind IN ('', 'SCAN', 'CHECK')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(assignee_id) REFERENCES project_personnel(id),
                UNIQUE(project_id, task_code)
            );

            CREATE TABLE IF NOT EXISTS paper_formats(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                display_name TEXT NOT NULL,
                requires_separate_scan INTEGER NOT NULL DEFAULT 1,
                requires_check INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, code)
            );

            CREATE TABLE IF NOT EXISTS project_job_types(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                job_code TEXT NOT NULL,
                display_name TEXT NOT NULL,
                job_kind TEXT NOT NULL DEFAULT 'SCAN'
                    CHECK(job_kind IN ('SCAN', 'CHECK')),
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, job_code)
            );

            CREATE TABLE IF NOT EXISTS record_workflows(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                record_key TEXT NOT NULL,
                scanner_id INTEGER,
                scan_date TEXT NOT NULL DEFAULT '',
                checker_id INTEGER,
                check_date TEXT NOT NULL DEFAULT '',
                check_pages INTEGER NOT NULL DEFAULT 0,
                check_files INTEGER NOT NULL DEFAULT 0,
                record_status TEXT NOT NULL DEFAULT 'NOT_STARTED',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(scanner_id) REFERENCES project_personnel(id) ON DELETE SET NULL,
                FOREIGN KEY(checker_id) REFERENCES project_personnel(id) ON DELETE SET NULL,
                UNIQUE(project_id, record_key)
            );

            CREATE TABLE IF NOT EXISTS record_paper_statuses(
                id INTEGER PRIMARY KEY,
                record_id INTEGER NOT NULL,
                paper_format_id INTEGER NOT NULL,
                scanner_id INTEGER,
                scan_date TEXT NOT NULL DEFAULT '',
                scan_status TEXT NOT NULL DEFAULT 'UNKNOWN',
                scan_pages INTEGER NOT NULL DEFAULT 0,
                scan_files INTEGER NOT NULL DEFAULT 0,
                check_pages INTEGER NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                FOREIGN KEY(record_id) REFERENCES record_workflows(id) ON DELETE CASCADE,
                FOREIGN KEY(paper_format_id) REFERENCES paper_formats(id) ON DELETE CASCADE,
                FOREIGN KEY(scanner_id) REFERENCES project_personnel(id) ON DELETE SET NULL,
                UNIQUE(record_id, paper_format_id)
            );

            CREATE TABLE IF NOT EXISTS record_check_assignments(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                record_key TEXT NOT NULL,
                checker_id INTEGER NOT NULL,
                client_code TEXT NOT NULL,
                folder_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ASSIGNED'
                    CHECK(status IN ('ASSIGNED', 'RECORDED', 'CANCELLED')),
                assigned_at TEXT NOT NULL,
                recorded_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(checker_id) REFERENCES project_personnel(id),
                UNIQUE(project_id, record_key, folder_path)
            );

            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS backup_files(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                client_code TEXT NOT NULL,
                source_path TEXT NOT NULL,
                project_code TEXT NOT NULL,
                relative_project_path TEXT NOT NULL,
                record_key TEXT NOT NULL DEFAULT '',
                file_kind TEXT NOT NULL DEFAULT 'SCAN'
                    CHECK(file_kind IN ('SCAN', 'CHECK')),
                dest_path TEXT NOT NULL,
                file_size INTEGER,
                source_mtime TEXT,
                hash_sha256 TEXT,
                status TEXT NOT NULL,
                error_message TEXT,
                created_at TEXT NOT NULL,
                copied_at TEXT,
                verified_at TEXT,
                locked_at TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, client_code, source_path)
            );

            CREATE TABLE IF NOT EXISTS backup_file_paper_sizes(
                backup_file_id INTEGER NOT NULL,
                paper_code TEXT NOT NULL,
                page_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(backup_file_id, paper_code),
                FOREIGN KEY(backup_file_id) REFERENCES backup_files(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_backup_files_status ON backup_files(status);
            CREATE INDEX IF NOT EXISTS idx_backup_files_dest ON backup_files(dest_path);

            CREATE TABLE IF NOT EXISTS audit_logs(
                id INTEGER PRIMARY KEY,
                project_id INTEGER,
                action TEXT NOT NULL,
                client_code TEXT,
                source_path TEXT,
                dest_path TEXT,
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS conflicts(
                id INTEGER PRIMARY KEY,
                backup_file_id INTEGER,
                client_code TEXT NOT NULL,
                source_path TEXT NOT NULL,
                dest_path TEXT NOT NULL,
                source_hash TEXT,
                dest_hash TEXT,
                status TEXT NOT NULL DEFAULT 'OPEN',
                resolution TEXT,
                archive_path TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY(backup_file_id) REFERENCES backup_files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS mapfile_profiles(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                sheet_name TEXT NOT NULL DEFAULT '',
                project_column TEXT NOT NULL,
                year_column TEXT NOT NULL,
                case_type_column TEXT NOT NULL,
                case_number_column TEXT NOT NULL,
                file_name_column TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, name)
            );

            CREATE TABLE IF NOT EXISTS mapfile_imports(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                profile_id INTEGER,
                file_path TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(profile_id) REFERENCES mapfile_profiles(id)
            );

            CREATE TABLE IF NOT EXISTS mapfile_rows(
                id INTEGER PRIMARY KEY,
                import_id INTEGER NOT NULL,
                row_number INTEGER NOT NULL,
                raw_json TEXT NOT NULL,
                expected_relative_path TEXT NOT NULL,
                record_key TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'EXPECTED',
                message TEXT NOT NULL DEFAULT '',
                is_done INTEGER NOT NULL DEFAULT 0,
                done_at TEXT,
                done_by INTEGER,
                FOREIGN KEY(import_id) REFERENCES mapfile_imports(id) ON DELETE CASCADE,
                FOREIGN KEY(done_by) REFERENCES project_personnel(id)
            );

            CREATE TABLE IF NOT EXISTS personnel_credentials(
                personnel_id INTEGER PRIMARY KEY,
                salt TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                must_change_pin INTEGER NOT NULL DEFAULT 1,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(personnel_id) REFERENCES project_personnel(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS backup_jobs(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                requested_by_type TEXT NOT NULL DEFAULT 'SYSTEM',
                requested_by_id INTEGER,
                payload_json TEXT NOT NULL DEFAULT '{}',
                counters_json TEXT NOT NULL DEFAULT '{}',
                error_code TEXT,
                error_detail TEXT,
                scheduled_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                lease_owner TEXT,
                lease_expires_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS operation_locks(
                resource_key TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS service_heartbeat(
                instance_id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                started_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_claim
                ON backup_jobs(status, scheduled_at, lease_expires_at);
            CREATE INDEX IF NOT EXISTS idx_jobs_project_created
                ON backup_jobs(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_project_created
                ON audit_logs(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_map_rows_import_status
                ON mapfile_rows(import_id, status, is_done);
            CREATE INDEX IF NOT EXISTS idx_backup_project_path
                ON backup_files(project_id, relative_project_path, status);
            CREATE INDEX IF NOT EXISTS idx_record_workflows_project
                ON record_workflows(project_id, record_key);
            CREATE INDEX IF NOT EXISTS idx_paper_formats_project
                ON paper_formats(project_id, enabled, sort_order);
            """
        )

    def _migrate_v2_to_v3(self, conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys=OFF")

        project_columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "singleton" in project_columns:
            conn.executescript(
                """
                CREATE TABLE projects_new(
                    id INTEGER PRIMARY KEY,
                    project_code TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    backup_root TEXT NOT NULL,
                    staging_dir TEXT NOT NULL,
                    conflict_archive_dir TEXT NOT NULL,
                    reports_dir TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO projects_new(
                    id, project_code, display_name, backup_root, staging_dir,
                    conflict_archive_dir, reports_dir, enabled, created_at, updated_at
                )
                SELECT id, project_code, display_name, backup_root, staging_dir,
                    conflict_archive_dir, reports_dir, enabled, created_at, updated_at
                FROM projects;
                DROP TABLE projects;
                ALTER TABLE projects_new RENAME TO projects;
                """
            )

        existing_project_ids = [row[0] for row in conn.execute("SELECT id FROM projects").fetchall()]
        if existing_project_ids:
            old_poll = conn.execute(
                "SELECT value FROM settings WHERE key='poll_interval_seconds'"
            ).fetchone()
            old_stability = conn.execute(
                "SELECT value FROM settings WHERE key='stability_wait_seconds'"
            ).fetchone()
            old_numeric = conn.execute(
                "SELECT value FROM settings WHERE key='numeric_sequence_check'"
            ).fetchone()
            now = utc_now()
            for project_id in existing_project_ids:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO project_settings(
                        project_id, poll_interval_seconds, stability_wait_seconds,
                        numeric_sequence_check, updated_at
                    ) VALUES(?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        int(old_poll[0]) if old_poll else DEFAULT_POLL_INTERVAL_SECONDS,
                        int(old_stability[0]) if old_stability else DEFAULT_STABILITY_WAIT_SECONDS,
                        int(old_numeric[0]) if old_numeric else 0,
                        now,
                    ),
                )

        profile_columns = {row[1] for row in conn.execute("PRAGMA table_info(mapfile_profiles)").fetchall()}
        if "project_id" not in profile_columns:
            conn.execute("ALTER TABLE mapfile_profiles ADD COLUMN project_id INTEGER")
            first_project = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()
            if first_project:
                conn.execute(
                    "UPDATE mapfile_profiles SET project_id=? WHERE project_id IS NULL",
                    (first_project[0],),
                )
            conn.executescript(
                """
                CREATE TABLE mapfile_profiles_new(
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    sheet_name TEXT NOT NULL DEFAULT '',
                    project_column TEXT NOT NULL,
                    year_column TEXT NOT NULL,
                    case_type_column TEXT NOT NULL,
                    case_number_column TEXT NOT NULL,
                    file_name_column TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, name)
                );
                INSERT INTO mapfile_profiles_new(
                    id, project_id, name, sheet_name, project_column, year_column,
                    case_type_column, case_number_column, file_name_column, created_at, updated_at
                )
                SELECT id, project_id, name, sheet_name, project_column, year_column,
                    case_type_column, case_number_column, file_name_column, created_at, updated_at
                FROM mapfile_profiles WHERE project_id IS NOT NULL;
                DROP TABLE mapfile_profiles;
                ALTER TABLE mapfile_profiles_new RENAME TO mapfile_profiles;
                """
            )

        for old_key, new_key in DEFAULT_SETTINGS_KEYS.items():
            row = conn.execute("SELECT value FROM settings WHERE key=?", (old_key,)).fetchone()
            if row is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (new_key, row[0])
                )
                conn.execute("DELETE FROM settings WHERE key=?", (old_key,))

        row_columns = {row[1] for row in conn.execute("PRAGMA table_info(mapfile_rows)").fetchall()}
        if "is_done" not in row_columns:
            conn.execute("ALTER TABLE mapfile_rows ADD COLUMN is_done INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE mapfile_rows ADD COLUMN done_at TEXT")
            conn.execute("ALTER TABLE mapfile_rows ADD COLUMN done_by INTEGER")

        conn.execute("PRAGMA foreign_keys=ON")

    def _migrate_to_v5(self, conn: sqlite3.Connection) -> None:
        backup_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(backup_files)").fetchall()
        }
        if "record_key" not in backup_columns:
            conn.execute(
                "ALTER TABLE backup_files ADD COLUMN record_key TEXT NOT NULL DEFAULT ''"
            )
        rows = conn.execute(
            "SELECT id, relative_project_path FROM backup_files WHERE record_key=''"
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE backup_files SET record_key=? WHERE id=?",
                (record_key_from_relative_path(row["relative_project_path"]), row["id"]),
            )
        mapfile_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(mapfile_rows)").fetchall()
        }
        if "record_key" not in mapfile_columns:
            conn.execute(
                "ALTER TABLE mapfile_rows ADD COLUMN record_key TEXT NOT NULL DEFAULT ''"
            )
        mapfile_rows = conn.execute(
            "SELECT id, expected_relative_path FROM mapfile_rows WHERE record_key=''"
        ).fetchall()
        for row in mapfile_rows:
            conn.execute(
                "UPDATE mapfile_rows SET record_key=? WHERE id=?",
                (
                    record_key_from_expected_path(row["expected_relative_path"]),
                    row["id"],
                ),
            )
        paper_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(record_paper_statuses)").fetchall()
        }
        if "scanner_id" not in paper_columns:
            conn.execute("ALTER TABLE record_paper_statuses ADD COLUMN scanner_id INTEGER")
        if "scan_date" not in paper_columns:
            conn.execute("ALTER TABLE record_paper_statuses ADD COLUMN scan_date TEXT NOT NULL DEFAULT ''")
        if "scan_files" not in paper_columns:
            conn.execute("ALTER TABLE record_paper_statuses ADD COLUMN scan_files INTEGER NOT NULL DEFAULT 0")
        workflow_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(record_workflows)").fetchall()
        }
        if "check_pages" not in workflow_columns:
            conn.execute("ALTER TABLE record_workflows ADD COLUMN check_pages INTEGER NOT NULL DEFAULT 0")
        if "check_files" not in workflow_columns:
            conn.execute("ALTER TABLE record_workflows ADD COLUMN check_files INTEGER NOT NULL DEFAULT 0")
        level_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(project_directory_levels)").fetchall()
        }
        if "show_in_mapfile" not in level_columns:
            conn.execute("ALTER TABLE project_directory_levels ADD COLUMN show_in_mapfile INTEGER NOT NULL DEFAULT 1")
        if "mapfile_position" not in level_columns:
            conn.execute("ALTER TABLE project_directory_levels ADD COLUMN mapfile_position INTEGER NOT NULL DEFAULT 0")
        if "require_catalog_selection" not in level_columns:
            conn.execute("ALTER TABLE project_directory_levels ADD COLUMN require_catalog_selection INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            UPDATE project_directory_levels
            SET mapfile_position=position
            WHERE mapfile_position IS NULL OR mapfile_position=0
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_job_types(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                job_code TEXT NOT NULL,
                display_name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, job_code)
            )
            """
        )
        self._seed_paper_formats(conn)

    def _migrate_to_v6(self, conn: sqlite3.Connection, current_version: int | None) -> None:
        job_type_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(project_job_types)").fetchall()
        }
        job_kind_added = "job_kind" not in job_type_columns
        if job_kind_added:
            conn.execute(
                """
                ALTER TABLE project_job_types ADD COLUMN job_kind TEXT NOT NULL DEFAULT 'SCAN'
                    CHECK(job_kind IN ('SCAN', 'CHECK'))
                """
            )
            # One-time default: infer the kind from the name the way the UI
            # heuristic used to, so existing check jobs stay check jobs.
            conn.execute(
                """
                UPDATE project_job_types SET job_kind='CHECK'
                WHERE instr(lower(job_code || ' ' || display_name), 'check') > 0
                """
            )

        task_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(project_tasks)").fetchall()
        }
        if "record_key" not in task_columns:
            conn.execute(
                "ALTER TABLE project_tasks ADD COLUMN record_key TEXT NOT NULL DEFAULT ''"
            )
        if "task_kind" not in task_columns:
            conn.execute(
                """
                ALTER TABLE project_tasks ADD COLUMN task_kind TEXT NOT NULL DEFAULT ''
                    CHECK(task_kind IN ('', 'SCAN', 'CHECK'))
                """
            )
        for row in conn.execute(
            "SELECT id, title, description FROM project_tasks WHERE record_key=''"
        ).fetchall():
            record_key = record_key_from_task_description(row["description"])
            if not record_key:
                continue
            task_kind = "CHECK" if "check" in str(row["title"] or "").lower() else "SCAN"
            conn.execute(
                "UPDATE project_tasks SET record_key=?, task_kind=? WHERE id=?",
                (record_key, task_kind, row["id"]),
            )

        backup_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(backup_files)").fetchall()
        }
        if "file_kind" not in backup_columns:
            conn.execute(
                """
                ALTER TABLE backup_files ADD COLUMN file_kind TEXT NOT NULL DEFAULT 'SCAN'
                    CHECK(file_kind IN ('SCAN', 'CHECK'))
                """
            )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS record_check_assignments(
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                record_key TEXT NOT NULL,
                checker_id INTEGER NOT NULL,
                client_code TEXT NOT NULL,
                folder_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ASSIGNED'
                    CHECK(status IN ('ASSIGNED', 'RECORDED', 'CANCELLED')),
                assigned_at TEXT NOT NULL,
                recorded_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(checker_id) REFERENCES project_personnel(id),
                UNIQUE(project_id, record_key, folder_path)
            )
            """
        )

        if current_version is not None and current_version < 6:
            self._migrate_v6_record_statuses(conn)

        # Seeding needs job_kind to exist, so it happens here rather than in v5.
        self._seed_job_types(conn)

    @staticmethod
    def _migrate_v6_record_statuses(conn: sqlite3.Connection) -> None:
        """One-time repair for records force-completed by the old "chốt việc"
        shortcut: COMPLETED without any check data means scanning was closed
        out, not that the record was checked. Move them back to the state the
        new lifecycle expects so they surface in the check-assignment list."""
        rows = conn.execute(
            """
            SELECT rw.id, rw.scanner_id,
                EXISTS(
                    SELECT 1 FROM record_paper_statuses rps
                    WHERE rps.record_id=rw.id AND (rps.scan_pages>0 OR rps.scan_files>0)
                ) AS has_scan_data,
                EXISTS(
                    SELECT 1 FROM record_paper_statuses rps
                    WHERE rps.record_id=rw.id AND rps.scan_status='PENDING_SCAN'
                ) AS has_pending_paper
            FROM record_workflows rw
            WHERE rw.record_status='COMPLETED'
                AND rw.checker_id IS NULL
                AND COALESCE(rw.check_date, '')=''
                AND COALESCE(rw.check_pages, 0)=0
                AND COALESCE(rw.check_files, 0)=0
            """
        ).fetchall()
        if not rows:
            return
        now = utc_now()
        moved: dict[str, int] = {}
        for row in rows:
            if row["has_scan_data"]:
                new_status = "PENDING_PAPER" if row["has_pending_paper"] else "PENDING_CHECK"
            else:
                new_status = "SCANNING" if row["scanner_id"] is not None else "NOT_STARTED"
            conn.execute(
                "UPDATE record_workflows SET record_status=?, updated_at=? WHERE id=?",
                (new_status, now, row["id"]),
            )
            moved[new_status] = moved.get(new_status, 0) + 1
        summary = ", ".join(f"{status}: {count}" for status, count in sorted(moved.items()))
        conn.execute(
            """
            INSERT INTO audit_logs(project_id, action, message, created_at)
            VALUES(NULL, 'MIGRATION_V6_RECORD_STATUS', ?, ?)
            """,
            (
                f"Reverted {len(rows)} force-completed record(s) without check data ({summary})",
                now,
            ),
        )

    @staticmethod
    def _seed_paper_formats(
        conn: sqlite3.Connection, project_id: int | None = None
    ) -> None:
        if project_id is None:
            project_ids = [
                int(row["id"]) for row in conn.execute("SELECT id FROM projects")
            ]
        else:
            project_ids = [project_id]
        now = utc_now()
        for current_project_id in project_ids:
            for code, name, order in (
                ("A4", "Khổ A4", 10),
                ("A3", "Khổ A3", 20),
                ("A0", "Khổ A0", 30),
            ):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO paper_formats(
                        project_id, code, display_name, requires_separate_scan,
                        requires_check, enabled, sort_order, created_at, updated_at
                    ) VALUES(?, ?, ?, 1, 1, 1, ?, ?, ?)
                    """,
                    (current_project_id, code, name, order, now, now),
                )

    @staticmethod
    def _seed_job_types(
        conn: sqlite3.Connection, project_id: int | None = None
    ) -> None:
        if project_id is None:
            project_ids = [
                int(row["id"]) for row in conn.execute("SELECT id FROM projects")
            ]
        else:
            project_ids = [project_id]
        now = utc_now()
        for current_project_id in project_ids:
            for code, name, order, kind in (
                ("SCAN_A4", "Scan A4", 10, "SCAN"),
                ("SCAN_A3", "Scan A3 (mới)", 20, "SCAN"),
                ("SCAN_A3_OLD", "Scan A3 (cũ)", 30, "SCAN"),
                ("SCAN_A0", "Scan A0", 40, "SCAN"),
                ("CHECK", "Check Scan", 50, "CHECK"),
            ):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO project_job_types(
                        project_id, job_code, display_name, job_kind, enabled,
                        sort_order, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (current_project_id, code, name, kind, order, now, now),
                )
            conn.execute(
                """
                UPDATE project_job_types
                SET display_name='Scan A3 (mới)', updated_at=?
                WHERE project_id=? AND job_code='SCAN_A3' AND display_name='Scan A3'
                """,
                (now, current_project_id),
            )
            conn.execute(
                """
                UPDATE project_job_types
                SET display_name='Check Scan', updated_at=?
                WHERE project_id=? AND job_code='CHECK' AND display_name='Check hồ sơ'
                """,
                (now, current_project_id),
            )

    def _ensure_defaults(self, conn: sqlite3.Connection) -> None:
        defaults = {
            "default_poll_interval_seconds": str(DEFAULT_POLL_INTERVAL_SECONDS),
            "default_stability_wait_seconds": str(DEFAULT_STABILITY_WAIT_SECONDS),
            "default_numeric_sequence_check": "0",
            "language": "vi",
            "theme_mode": "dark",
        }
        for key, value in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (key, value))

        if not conn.execute("SELECT 1 FROM admin_auth WHERE id=1").fetchone():
            salt = secrets.token_bytes(16)
            conn.execute(
                """
                INSERT INTO admin_auth(id, salt, password_hash, must_change_password, updated_at)
                VALUES(1, ?, ?, 1, ?)
                """,
                (salt.hex(), _password_hash(DEFAULT_ADMIN_PASSWORD, salt), utc_now()),
            )
        self._seed_paper_formats(conn)

    # ------------------------------------------------------------------
    # Authentication and settings (global, not project-scoped)
    # ------------------------------------------------------------------
    def verify_admin_password(self, password: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT salt, password_hash FROM admin_auth WHERE id=1").fetchone()
        if not row:
            return False
        actual = _password_hash(password, bytes.fromhex(row["salt"]))
        return hmac.compare_digest(actual, row["password_hash"])

    def admin_must_change_password(self) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT must_change_password FROM admin_auth WHERE id=1"
            ).fetchone()
            return bool(row["must_change_password"]) if row else True

    def change_admin_password(self, current_password: str, new_password: str) -> None:
        if not self.verify_admin_password(current_password):
            raise ValueError("Current password is incorrect")
        if len(new_password) < 8:
            raise ValueError("New password must contain at least 8 characters")
        salt = secrets.token_bytes(16)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE admin_auth
                SET salt=?, password_hash=?, must_change_password=0, updated_at=?
                WHERE id=1
                """,
                (salt.hex(), _password_hash(new_password, salt), utc_now()),
            )

    def get_setting(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def list_settings(self) -> dict[str, str]:
        with self.connect() as conn:
            return {row["key"]: row["value"] for row in conn.execute("SELECT key,value FROM settings")}

    def export_backup(self, dest_dir: Path) -> Path:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = dest_dir / f"{self.db_path.stem}.manual-bak-{stamp}{self.db_path.suffix}"
        shutil.copy2(self.db_path, destination)
        return destination

    def project_database_path(self, project_code: str) -> Path:
        code = project_code.strip().upper()
        return self.db_path.parent / "project_databases" / f"{code}.sqlite3"

    def ensure_project_database(self, project_id: int) -> Path:
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        destination = self.project_database_path(project.project_code)
        destination.parent.mkdir(parents=True, exist_ok=True)
        now = utc_now()
        with closing(sqlite3.connect(destination)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_metadata(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            rows = {
                "project_id": str(project.id or ""),
                "project_code": project.project_code,
                "display_name": project.display_name,
                "central_db_path": str(self.db_path),
            }
            for key, value in rows.items():
                conn.execute(
                    """
                    INSERT INTO project_metadata(key, value, updated_at) VALUES(?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                    """,
                    (key, value, now),
                )
            conn.commit()
        return destination

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Project:
        return Project(
            row["id"], row["project_code"], row["display_name"], row["backup_root"],
            row["staging_dir"], row["conflict_archive_dir"], row["reports_dir"],
            bool(row["enabled"]),
        )

    def list_projects(self) -> list[Project]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY display_name").fetchall()
        return [self._row_to_project(row) for row in rows]

    def get_project(self, project_id: int) -> Project | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return self._row_to_project(row) if row else None

    def save_project(self, project: Project) -> int:
        code = project.project_code.strip().upper()
        if not code or any(char in code for char in r'\/:*?"<>|'):
            raise ValueError("Project code is required and cannot contain path separators")
        if not project.display_name.strip():
            raise ValueError("Project display name is required")
        if not all(
            value.strip()
            for value in (
                project.backup_root,
                project.staging_dir,
                project.conflict_archive_dir,
                project.reports_dir,
            )
        ):
            raise ValueError("All project directories are required")
        now = utc_now()
        with self.connect() as conn:
            duplicate = conn.execute(
                """
                SELECT id FROM projects
                WHERE project_code=? AND (? IS NULL OR id<>?)
                """,
                (code, project.id, project.id),
            ).fetchone()
            if duplicate:
                raise ValueError(f"Mã dự án '{code}' đã tồn tại.")
            if project.id is not None:
                try:
                    conn.execute(
                        """
                        UPDATE projects SET project_code=?, display_name=?, backup_root=?,
                            staging_dir=?, conflict_archive_dir=?, reports_dir=?, enabled=?, updated_at=?
                        WHERE id=?
                        """,
                        (
                            code, project.display_name.strip(), project.backup_root.strip(),
                            project.staging_dir.strip(), project.conflict_archive_dir.strip(),
                            project.reports_dir.strip(), int(project.enabled), now, project.id,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError(f"Mã dự án '{code}' đã tồn tại.") from exc
                return project.id
            try:
                cur = conn.execute(
                    """
                    INSERT INTO projects(
                        project_code, display_name, backup_root, staging_dir,
                        conflict_archive_dir, reports_dir, enabled, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code, project.display_name.strip(), project.backup_root.strip(),
                        project.staging_dir.strip(), project.conflict_archive_dir.strip(),
                        project.reports_dir.strip(), int(project.enabled), now, now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Mã dự án '{code}' đã tồn tại.") from exc
            return int(cur.lastrowid)

    def create_project(self, project: Project) -> int:
        """Create a brand-new project and seed its per-project settings/mapfile profile."""
        project_id = self.save_project(project)
        now = utc_now()
        with self.connect() as conn:
            defaults = {
                row["key"]: row["value"]
                for row in conn.execute(
                    "SELECT key, value FROM settings WHERE key IN (?, ?, ?)",
                    tuple(DEFAULT_SETTINGS_KEYS.values()),
                )
            }
            conn.execute(
                """
                INSERT OR IGNORE INTO project_settings(
                    project_id, poll_interval_seconds, stability_wait_seconds,
                    numeric_sequence_check, updated_at
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    int(defaults.get("default_poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS)),
                    int(defaults.get("default_stability_wait_seconds", DEFAULT_STABILITY_WAIT_SECONDS)),
                    int(defaults.get("default_numeric_sequence_check", "0")),
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO mapfile_profiles(
                    project_id, name, sheet_name, project_column, year_column, case_type_column,
                    case_number_column, file_name_column, created_at, updated_at
                ) VALUES(?, 'Default', '', 'project', 'year', 'case_type', 'case_number', 'file_name', ?, ?)
                """,
                (project_id, now, now),
            )
            self._seed_paper_formats(conn, project_id)
            self._seed_job_types(conn, project_id)
        self.ensure_project_database(project_id)
        return project_id

    def delete_project(self, project_id: int) -> None:
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        project_db_path = self.project_database_path(project.project_code)
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            if cur.rowcount == 0:
                raise ValueError(f"Project not found: {project_id}")
        try:
            project_db_path.unlink()
        except FileNotFoundError:
            pass
        self.record_audit(
            "PROJECT_DELETED",
            f"Deleted project {project.project_code} - {project.display_name}",
            project_id=None,
        )

    def get_project_settings(self, project_id: int) -> ProjectSettings:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM project_settings WHERE project_id=?", (project_id,)
            ).fetchone()
            if row is None:
                defaults = {
                    r["key"]: r["value"]
                    for r in conn.execute(
                        "SELECT key, value FROM settings WHERE key IN (?, ?, ?)",
                        tuple(DEFAULT_SETTINGS_KEYS.values()),
                    )
                }
                now = utc_now()
                conn.execute(
                    """
                    INSERT INTO project_settings(
                        project_id, poll_interval_seconds, stability_wait_seconds,
                        numeric_sequence_check, updated_at
                    ) VALUES(?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        int(defaults.get("default_poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS)),
                        int(defaults.get("default_stability_wait_seconds", DEFAULT_STABILITY_WAIT_SECONDS)),
                        int(defaults.get("default_numeric_sequence_check", "0")),
                        now,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM project_settings WHERE project_id=?", (project_id,)
                ).fetchone()
        return ProjectSettings(
            row["project_id"], int(row["poll_interval_seconds"]),
            int(row["stability_wait_seconds"]), bool(row["numeric_sequence_check"]),
        )

    def save_project_settings(self, settings: ProjectSettings) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO project_settings(
                    project_id, poll_interval_seconds, stability_wait_seconds,
                    numeric_sequence_check, updated_at
                ) VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    poll_interval_seconds=excluded.poll_interval_seconds,
                    stability_wait_seconds=excluded.stability_wait_seconds,
                    numeric_sequence_check=excluded.numeric_sequence_check,
                    updated_at=excluded.updated_at
                """,
                (
                    settings.project_id, settings.poll_interval_seconds,
                    settings.stability_wait_seconds, int(settings.numeric_sequence_check),
                    utc_now(),
                ),
            )

    def list_directory_levels(self, project_id: int) -> list[DirectoryLevel]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM project_directory_levels
                WHERE project_id=? ORDER BY position
                """,
                (project_id,),
            ).fetchall()
        return [
            DirectoryLevel(
                row["id"], row["project_id"], row["position"], row["display_name"],
                row["validation_type"], json.loads(row["allowed_values_json"]),
                bool(row["show_in_mapfile"]),
                int(row["mapfile_position"] or row["position"]),
                bool(row["require_catalog_selection"]),
            )
            for row in rows
        ]

    def save_directory_levels(self, project_id: int, levels: list[DirectoryLevel]) -> None:
        if not levels:
            raise ValueError("At least one directory level is required")
        with self.connect() as conn:
            conn.execute("DELETE FROM project_directory_levels WHERE project_id=?", (project_id,))
            for position, level in enumerate(levels, start=1):
                display_name = level.display_name.strip()
                if not display_name:
                    raise ValueError("Directory level name is required")
                if level.validation_type not in {"YEAR4", "ENUM", "INTEGER", "TEXT"}:
                    raise ValueError(f"Unsupported directory validation type: {level.validation_type}")
                allowed_by_key: dict[str, str] = {}
                for value in level.allowed_values:
                    clean_value = value.strip()
                    if not clean_value:
                        continue
                    key = clean_value.upper() if level.validation_type == "ENUM" else clean_value
                    allowed_by_key.setdefault(key, clean_value)
                allowed = sorted(allowed_by_key.values())
                if level.require_catalog_selection and not allowed:
                    raise ValueError(
                        f"{display_name} bắt buộc chọn từ danh mục nhưng chưa có giá trị."
                    )
                conn.execute(
                    """
                    INSERT INTO project_directory_levels(
                        project_id, position, display_name, validation_type,
                        allowed_values_json, show_in_mapfile, mapfile_position,
                        require_catalog_selection
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id, position, display_name, level.validation_type,
                        json.dumps(allowed, ensure_ascii=False),
                        int(level.show_in_mapfile),
                        int(level.mapfile_position or position),
                        int(level.require_catalog_selection),
                    ),
                )

    # ------------------------------------------------------------------
    # Workstations
    # ------------------------------------------------------------------
    def list_clients(self, project_id: int) -> list[Client]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM clients WHERE project_id=? ORDER BY client_code",
                (project_id,),
            ).fetchall()
        return [
            Client(
                row["id"], row["project_id"], row["client_code"], row["staff_name"],
                row["share_path"], bool(row["enabled"]), row["notes"],
            )
            for row in rows
        ]

    def save_client(self, client: Client) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO clients(
                    project_id, client_code, share_path, staff_name, enabled, notes,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, client_code) DO UPDATE SET
                    share_path=excluded.share_path, staff_name=excluded.staff_name,
                    enabled=excluded.enabled, notes=excluded.notes, updated_at=excluded.updated_at
                """,
                (
                    client.project_id, client.client_code.strip().upper(), client.share_path.strip(),
                    client.staff_name.strip(), int(client.enabled), client.notes.strip(), now, now,
                ),
            )

    def delete_client(self, project_id: int, client_code: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM clients WHERE project_id=? AND client_code=?",
                (project_id, client_code),
            )

    # ------------------------------------------------------------------
    # Personnel and project tasks
    # ------------------------------------------------------------------
    def list_personnel(self, project_id: int, enabled_only: bool = False) -> list[Personnel]:
        sql = "SELECT * FROM project_personnel WHERE project_id=?"
        if enabled_only:
            sql += " AND enabled=1"
        sql += " ORDER BY personnel_code"
        with self.connect() as conn:
            rows = conn.execute(sql, (project_id,)).fetchall()
        return [
            Personnel(
                row["id"], row["project_id"], row["personnel_code"], row["full_name"],
                row["role_name"], bool(row["enabled"]),
            )
            for row in rows
        ]

    def save_personnel(self, person: Personnel) -> int:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO project_personnel(
                    project_id, personnel_code, full_name, role_name, enabled,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, personnel_code) DO UPDATE SET
                    full_name=excluded.full_name, role_name=excluded.role_name,
                    enabled=excluded.enabled, updated_at=excluded.updated_at
                """,
                (
                    person.project_id, person.personnel_code.strip().upper(),
                    person.full_name.strip(), person.role_name.strip(), int(person.enabled), now, now,
                ),
            )
            row = conn.execute(
                """
                SELECT id FROM project_personnel
                WHERE project_id=? AND personnel_code=?
                """,
                (person.project_id, person.personnel_code.strip().upper()),
            ).fetchone()
            return int(row["id"])

    def delete_personnel(self, personnel_id: int) -> None:
        with self.connect() as conn:
            used = conn.execute(
                "SELECT 1 FROM project_tasks WHERE assignee_id=? LIMIT 1", (personnel_id,)
            ).fetchone()
            if used:
                conn.execute(
                    "UPDATE project_personnel SET enabled=0, updated_at=? WHERE id=?",
                    (utc_now(), personnel_id),
                )
                return
            conn.execute("DELETE FROM project_personnel WHERE id=?", (personnel_id,))

    # ------------------------------------------------------------------
    # Paper formats
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_paper_format(row: sqlite3.Row) -> PaperFormat:
        return PaperFormat(
            row["id"],
            row["project_id"],
            row["code"],
            row["display_name"],
            bool(row["requires_separate_scan"]),
            bool(row["requires_check"]),
            bool(row["enabled"]),
            int(row["sort_order"]),
        )

    def list_paper_formats(
        self, project_id: int, *, enabled_only: bool = False
    ) -> list[PaperFormat]:
        sql = "SELECT * FROM paper_formats WHERE project_id=?"
        if enabled_only:
            sql += " AND enabled=1"
        sql += " ORDER BY sort_order, code"
        with self.connect() as conn:
            rows = conn.execute(sql, (project_id,)).fetchall()
        return [self._row_to_paper_format(row) for row in rows]

    def save_paper_format(self, paper_format: PaperFormat) -> int:
        code = paper_format.code.strip().upper()
        display_name = paper_format.display_name.strip()
        if not code or any(char in code for char in r'\/:*?"<>|'):
            raise ValueError("Mã khổ giấy không hợp lệ.")
        if not display_name:
            raise ValueError("Cần nhập tên hiển thị của khổ giấy.")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_formats(
                    project_id, code, display_name, requires_separate_scan,
                    requires_check, enabled, sort_order, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, code) DO UPDATE SET
                    display_name=excluded.display_name,
                    requires_separate_scan=excluded.requires_separate_scan,
                    requires_check=excluded.requires_check,
                    enabled=excluded.enabled,
                    sort_order=excluded.sort_order,
                    updated_at=excluded.updated_at
                """,
                (
                    paper_format.project_id,
                    code,
                    display_name,
                    int(paper_format.requires_separate_scan),
                    int(paper_format.requires_check),
                    int(paper_format.enabled),
                    max(0, int(paper_format.sort_order)),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM paper_formats WHERE project_id=? AND code=?",
                (paper_format.project_id, code),
            ).fetchone()
            return int(row["id"])

    # ------------------------------------------------------------------
    # Job types
    # ------------------------------------------------------------------
    def list_job_types(self, project_id: int, *, enabled_only: bool = False) -> list[JobType]:
        sql = "SELECT * FROM project_job_types WHERE project_id=?"
        if enabled_only:
            sql += " AND enabled=1"
        sql += " ORDER BY sort_order, job_code"
        with self.connect() as conn:
            rows = conn.execute(sql, (project_id,)).fetchall()
            if not rows:
                self._seed_job_types(conn, project_id)
                rows = conn.execute(sql, (project_id,)).fetchall()
        return [
            JobType(
                row["id"],
                row["project_id"],
                row["job_code"],
                row["display_name"],
                bool(row["enabled"]),
                int(row["sort_order"]),
                str(row["job_kind"] or "SCAN"),
            )
            for row in rows
        ]

    def save_job_type(self, job_type: JobType) -> int:
        code = job_type.job_code.strip().upper()
        display_name = job_type.display_name.strip()
        job_kind = (job_type.job_kind or "SCAN").strip().upper()
        if not code or any(char in code for char in r'\/:*?"<>|'):
            raise ValueError("Mã công việc không hợp lệ.")
        if not display_name:
            raise ValueError("Cần nhập tên công việc.")
        if job_kind not in {"SCAN", "CHECK"}:
            raise ValueError("Loại công việc phải là SCAN hoặc CHECK.")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO project_job_types(
                    project_id, job_code, display_name, job_kind, enabled,
                    sort_order, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, job_code) DO UPDATE SET
                    display_name=excluded.display_name,
                    job_kind=excluded.job_kind,
                    enabled=excluded.enabled,
                    sort_order=excluded.sort_order,
                    updated_at=excluded.updated_at
                """,
                (
                    job_type.project_id,
                    code,
                    display_name,
                    job_kind,
                    int(job_type.enabled),
                    max(0, int(job_type.sort_order)),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM project_job_types WHERE project_id=? AND job_code=?",
                (job_type.project_id, code),
            ).fetchone()
            return int(row["id"])

    def list_tasks(self, project_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT t.*, p.personnel_code, p.full_name AS assignee_name
                FROM project_tasks t
                JOIN project_personnel p ON p.id=t.assignee_id
                WHERE t.project_id=? ORDER BY t.id DESC
                """,
                (project_id,),
            ).fetchall()

    def save_task(self, task: ProjectTask) -> int:
        with self.connect() as conn:
            assignee = conn.execute(
                """
                SELECT enabled FROM project_personnel
                WHERE id=? AND project_id=?
                """,
                (task.assignee_id, task.project_id),
            ).fetchone()
            if not assignee or not assignee["enabled"]:
                raise ValueError("Tasks can only be assigned to active personnel")
            now = utc_now()
            record_key = task.record_key.strip().replace("\\", "/").strip("/")
            task_kind = (task.task_kind or "").strip().upper()
            if task_kind not in {"", "SCAN", "CHECK"}:
                raise ValueError("Loại nhiệm vụ phải là SCAN hoặc CHECK.")
            conn.execute(
                """
                INSERT INTO project_tasks(
                    project_id, task_code, title, description, assignee_id, due_date,
                    priority, status, record_key, task_kind, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, task_code) DO UPDATE SET
                    title=excluded.title, description=excluded.description,
                    assignee_id=excluded.assignee_id, due_date=excluded.due_date,
                    priority=excluded.priority, status=excluded.status,
                    record_key=excluded.record_key, task_kind=excluded.task_kind,
                    updated_at=excluded.updated_at
                """,
                (
                    task.project_id, task.task_code.strip().upper(), task.title.strip(),
                    task.description.strip(), task.assignee_id, task.due_date.strip(),
                    task.priority, task.status, record_key, task_kind, now, now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM project_tasks WHERE project_id=? AND task_code=?",
                (task.project_id, task.task_code.strip().upper()),
            ).fetchone()
            return int(row["id"])

    def delete_task(self, task_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM project_tasks WHERE id=?", (task_id,))

    def complete_open_tasks_for_assignee(
        self, project_id: int, assignee_id: int
    ) -> list[dict[str, Any]]:
        """Mark a person's open tasks complete and return the affected records
        as ``{"task_id", "record_key", "kind"}`` dicts (kind: SCAN/CHECK/'').

        Closing a task no longer mutates record_workflows directly — the caller
        drives the follow-up backup, whose automated sync owns the status."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, description, record_key, task_kind FROM project_tasks
                WHERE project_id=? AND assignee_id=? AND status IN ('NEW', 'IN_PROGRESS')
                """,
                (project_id, assignee_id),
            ).fetchall()
            if not rows:
                return []
            task_ids = [int(row["id"]) for row in rows]
            now = utc_now()
            conn.execute(
                f"""
                UPDATE project_tasks
                SET status='COMPLETED', updated_at=?
                WHERE id IN ({', '.join('?' for _ in task_ids)})
                """,
                [now, *task_ids],
            )
            completed: list[dict[str, Any]] = []
            seen_keys: set[str] = set()
            for row in rows:
                record_key = str(row["record_key"] or "").strip()
                if not record_key:
                    record_key = record_key_from_task_description(row["description"])
                if not record_key or record_key in seen_keys:
                    continue
                seen_keys.add(record_key)
                kind = str(row["task_kind"] or "").strip().upper()
                if not kind:
                    kind = "CHECK" if "check" in str(row["title"] or "").lower() else "SCAN"
                completed.append(
                    {"task_id": int(row["id"]), "record_key": record_key, "kind": kind}
                )
            return completed

    # ------------------------------------------------------------------
    # Audit and backup records
    # ------------------------------------------------------------------
    def record_audit(
        self,
        action: str,
        message: str = "",
        client_code: str | None = None,
        source_path: str | None = None,
        dest_path: str | None = None,
        *,
        project_id: int | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs(
                    project_id, action, client_code, source_path, dest_path, message, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, action, client_code, source_path, dest_path, message, utc_now()),
            )

    def list_audit_logs(
        self,
        project_id: int | None = None,
        action: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        client_code: str | None = None,
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            clauses.append("project_id=?")
            params.append(project_id)
        if action:
            clauses.append("action=?")
            params.append(action)
        if client_code:
            clauses.append("client_code=?")
            params.append(client_code)
        if date_from:
            clauses.append("created_at>=?")
            params.append(date_from)
        if date_to:
            clauses.append("created_at<=?")
            params.append(date_to)
        sql = "SELECT * FROM audit_logs"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def upsert_backup_file(
        self,
        *,
        project_id: int,
        client_code: str,
        source_path: str,
        project_code: str,
        relative_project_path: str,
        dest_path: str,
        file_size: int | None,
        source_mtime: str | None,
        status: str,
        error_message: str = "",
        hash_sha256: str | None = None,
        file_kind: str = "SCAN",
    ) -> int:
        if file_kind not in {"SCAN", "CHECK"}:
            raise ValueError("file_kind phải là SCAN hoặc CHECK.")
        now = utc_now()
        record_key = record_key_from_relative_path(relative_project_path)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO backup_files(
                    project_id, client_code, source_path, project_code,
                    relative_project_path, record_key, file_kind, dest_path, file_size,
                    source_mtime, hash_sha256, status, error_message, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, client_code, source_path) DO UPDATE SET
                    project_code=excluded.project_code,
                    relative_project_path=excluded.relative_project_path,
                    record_key=excluded.record_key,
                    file_kind=excluded.file_kind,
                    dest_path=excluded.dest_path, file_size=excluded.file_size,
                    source_mtime=excluded.source_mtime,
                    hash_sha256=COALESCE(excluded.hash_sha256, backup_files.hash_sha256),
                    status=excluded.status, error_message=excluded.error_message
                """,
                (
                    project_id, client_code, source_path, project_code,
                    relative_project_path, record_key, file_kind, dest_path, file_size,
                    source_mtime, hash_sha256, status, error_message, now,
                ),
            )
            row = conn.execute(
                """
                SELECT id FROM backup_files
                WHERE project_id=? AND client_code=? AND source_path=?
                """,
                (project_id, client_code, source_path),
            ).fetchone()
            return int(row["id"])

    def update_backup_status(
        self,
        backup_file_id: int,
        status: str,
        error_message: str = "",
        *,
        hash_sha256: str | None = None,
        copied: bool = False,
        verified: bool = False,
        locked: bool = False,
    ) -> None:
        assignments = ["status=?", "error_message=?"]
        params: list[Any] = [status, error_message]
        if hash_sha256 is not None:
            assignments.append("hash_sha256=?")
            params.append(hash_sha256)
        now = utc_now()
        for flag, column in ((copied, "copied_at"), (verified, "verified_at"), (locked, "locked_at")):
            if flag:
                assignments.append(f"{column}=COALESCE({column}, ?)")
                params.append(now)
        params.append(backup_file_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE backup_files SET {', '.join(assignments)} WHERE id=?", params
            )

    def save_backup_file_paper_sizes(
        self, backup_file_id: int, exact_pages: dict[str, int]
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM backup_file_paper_sizes WHERE backup_file_id=?",
                (backup_file_id,),
            )
            conn.executemany(
                """
                INSERT INTO backup_file_paper_sizes(
                    backup_file_id, paper_code, page_count, updated_at
                ) VALUES(?, ?, ?, ?)
                """,
                [
                    (backup_file_id, code, max(0, int(page_count)), now)
                    for code, page_count in sorted(exact_pages.items())
                    if int(page_count) > 0
                ],
            )

    def get_backup_file(self, backup_file_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM backup_files WHERE id=?", (backup_file_id,)).fetchone()

    def find_backup_file_by_relative_path(
        self, project_id: int, relative_path: str
    ) -> sqlite3.Row | None:
        """Look up an already-backed-up file for 1 mapfile row without loading the
        whole backup_files table (used by MapfileService.reconcile_row)."""
        status_list = sorted(COUNTABLE_BACKUP_STATUSES)
        with self.connect() as conn:
            return conn.execute(
                f"""
                SELECT * FROM backup_files
                WHERE project_id=? AND (project_code || '/' || relative_project_path)=?
                    AND status IN ({', '.join('?' for _ in status_list)})
                ORDER BY id DESC LIMIT 1
                """,
                (project_id, relative_path.replace("\\", "/"), *status_list),
            ).fetchone()

    def list_backup_files(
        self,
        project_id: int,
        statuses: Iterable[str] | None = None,
        limit: int | None = 500,
    ) -> list[sqlite3.Row]:
        params: list[Any] = [project_id]
        sql = "SELECT * FROM backup_files WHERE project_id=?"
        if statuses:
            status_list = list(statuses)
            sql += f" AND status IN ({', '.join('?' for _ in status_list)})"
            params.extend(status_list)
        sql += " ORDER BY id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def list_backup_files_for_record(
        self,
        project_id: int,
        record_key: str,
        statuses: Iterable[str] | None = None,
        file_kind: str | None = None,
    ) -> list[sqlite3.Row]:
        params: list[Any] = [project_id, record_key.strip().replace("\\", "/").strip("/")]
        sql = "SELECT * FROM backup_files WHERE project_id=? AND record_key=?"
        if statuses:
            status_list = list(statuses)
            sql += f" AND status IN ({', '.join('?' for _ in status_list)})"
            params.extend(status_list)
        if file_kind is not None:
            sql += " AND file_kind=?"
            params.append(file_kind)
        sql += " ORDER BY id DESC"
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def has_existing_backup_file_for_record(
        self, project_id: int, record_key: str
    ) -> bool:
        rows = self.list_backup_files_for_record(
            project_id,
            record_key,
            statuses=FINAL_OK_STATUSES,
            file_kind="SCAN",
        )
        for row in rows:
            for path_key in ("dest_path", "source_path"):
                path_value = str(row[path_key] or "").strip()
                if path_value and Path(path_value).is_file():
                    return True
        return False

    def list_backup_files_page(
        self,
        project_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        search: str = "",
    ) -> tuple[list[sqlite3.Row], int]:
        where = ["project_id=?"]
        params: list[Any] = [project_id]
        if status:
            where.append("status=?")
            params.append(status)
        if search.strip():
            term = f"%{search.strip()}%"
            where.append(
                """
                (client_code LIKE ? OR source_path LIKE ?
                 OR relative_project_path LIKE ? OR dest_path LIKE ?
                 OR COALESCE(hash_sha256, '') LIKE ?)
                """
            )
            params.extend([term, term, term, term, term])
        clause = " AND ".join(where)
        with self.connect() as conn:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM backup_files WHERE {clause}", params
                ).fetchone()[0]
            )
            rows = conn.execute(
                f"""
                SELECT * FROM backup_files
                WHERE {clause}
                ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
            return rows, total

    @staticmethod
    def _system_records_filter(
        project_id: int,
        *,
        search: str = "",
        filters: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, Any], str]:
        where = ["rk.record_key<>''"]
        params: dict[str, Any] = {"project_id": project_id}
        active_filters = {
            key: str(value).strip()
            for key, value in (filters or {}).items()
            if str(value).strip()
        }
        if search.strip():
            term = f"%{search.strip()}%"
            where.append(
                """
                (rk.record_key LIKE :search
                 OR COALESCE(bs.client_codes, '') LIKE :search
                 OR COALESCE(bs.source_paths, '') LIKE :search
                 OR COALESCE(bs.dest_paths, '') LIKE :search)
                """
            )
            params["search"] = term
        if active_filters.get("record_key"):
            where.append("rk.record_key LIKE :record_key_filter")
            params["record_key_filter"] = f"%{active_filters['record_key']}%"
        if active_filters.get("client_code"):
            where.append("COALESCE(bs.client_codes, '') LIKE :client_code_filter")
            params["client_code_filter"] = f"%{active_filters['client_code']}%"
        if active_filters.get("record_status"):
            where.append("COALESCE(rw.record_status, 'NOT_STARTED')=:record_status_filter")
            params["record_status_filter"] = active_filters["record_status"]
        if active_filters.get("backup_status"):
            where.append("COALESCE(bs.backup_status, 'NOT_BACKED_UP')=:backup_status_filter")
            params["backup_status_filter"] = active_filters["backup_status"]
        for key, value in active_filters.items():
            if not key.startswith("level_"):
                continue
            where.append("('/' || rk.record_key || '/') LIKE :%s" % key)
            params[key] = f"%/{value}%"
        clause = " AND ".join(where)
        cte = f"""
            WITH latest_import AS (
                SELECT id FROM mapfile_imports
                WHERE project_id=:project_id
                ORDER BY id DESC LIMIT 1
            ),
            record_key_sources AS (
                SELECT record_key, 1000000000 + MIN(id) AS sort_order
                FROM backup_files
                WHERE project_id=:project_id AND record_key<>''
                GROUP BY record_key
                UNION ALL
                SELECT r.record_key, r.row_number AS sort_order
                FROM mapfile_rows r
                JOIN latest_import i ON i.id=r.import_id
                WHERE r.record_key<>''
            ),
            record_keys AS (
                SELECT record_key, MIN(sort_order) AS sort_order
                FROM record_key_sources
                GROUP BY record_key
            ),
            backup_summary AS (
                SELECT
                    record_key,
                    MIN(project_code) AS project_code,
                    GROUP_CONCAT(DISTINCT client_code) AS client_codes,
                    GROUP_CONCAT(source_path, ' | ') AS source_paths,
                    GROUP_CONCAT(dest_path, ' | ') AS dest_paths,
                    COUNT(*) AS file_count,
                    COALESCE(SUM(file_size), 0) AS total_size,
                    MAX(created_at) AS last_seen_at,
                    MAX(dest_path) AS sample_dest_path,
                    CASE
                        WHEN SUM(CASE WHEN status='ERROR' THEN 1 ELSE 0 END) > 0
                            THEN 'ERROR'
                        WHEN SUM(CASE WHEN status='CONFLICT' THEN 1 ELSE 0 END) > 0
                            THEN 'CONFLICT'
                        WHEN SUM(CASE WHEN status NOT IN (
                            {_COUNTABLE_SQL}
                        ) THEN 1 ELSE 0 END) > 0
                            THEN 'IN_PROGRESS'
                        ELSE 'BACKED_UP'
                    END AS backup_status
                FROM backup_files
                WHERE project_id=:project_id AND record_key<>''
                GROUP BY record_key
            )
        """
        return clause, params, cte

    def list_system_records_page(
        self,
        project_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
        search: str = "",
        filters: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        clause, params, cte = self._system_records_filter(
            project_id, search=search, filters=filters
        )
        params["limit"] = limit
        params["offset"] = offset
        with self.connect() as conn:
            total = int(
                conn.execute(
                    f"{cte} SELECT COUNT(*) FROM record_keys rk "
                    f"LEFT JOIN backup_summary bs ON bs.record_key=rk.record_key "
                    f"LEFT JOIN record_workflows rw "
                    f"ON rw.project_id=:project_id AND rw.record_key=rk.record_key "
                    f"WHERE {clause}",
                    params,
                ).fetchone()[0]
            )
            rows = conn.execute(
                f"""{cte}
                SELECT
                    rk.record_key,
                    COALESCE(bs.project_code, project.project_code) AS project_code,
                    COALESCE(bs.client_codes, '') AS client_codes,
                    COALESCE(bs.file_count, 0) AS file_count,
                    COALESCE(bs.total_size, 0) AS total_size,
                    COALESCE(bs.last_seen_at, '') AS last_seen_at,
                    bs.sample_dest_path,
                    rw.id AS workflow_id,
                    rw.scanner_id,
                    scanner.full_name AS scanner_name,
                    rw.scan_date,
                    rw.checker_id,
                    checker.full_name AS checker_name,
                    rw.check_date,
                    COALESCE(rw.check_pages, 0) AS check_pages,
                    COALESCE(rw.check_files, 0) AS check_files,
                    COALESCE(rw.record_status, 'NOT_STARTED') AS record_status,
                    COALESCE(rw.notes, '') AS workflow_notes,
                    COALESCE(bs.backup_status, 'NOT_BACKED_UP') AS backup_status
                FROM record_keys rk
                JOIN projects project ON project.id=:project_id
                LEFT JOIN backup_summary bs ON bs.record_key=rk.record_key
                LEFT JOIN record_workflows rw
                    ON rw.project_id=:project_id AND rw.record_key=rk.record_key
                LEFT JOIN project_personnel scanner ON scanner.id=rw.scanner_id
                LEFT JOIN project_personnel checker ON checker.id=rw.checker_id
                WHERE {clause}
                ORDER BY rk.sort_order, rk.record_key
                LIMIT :limit OFFSET :offset
                """,
                params,
            ).fetchall()
            result = [dict(row) for row in rows]
            workflow_ids = [
                int(row["workflow_id"])
                for row in result
                if row["workflow_id"] is not None
            ]
            statuses_by_record: dict[int, dict[str, dict[str, Any]]] = {}
            if workflow_ids:
                placeholders = ", ".join("?" for _ in workflow_ids)
                status_rows = conn.execute(
                    f"""
                    SELECT rps.*, pf.code, pf.display_name,
                        scanner.full_name AS scanner_name
                    FROM record_paper_statuses rps
                    JOIN paper_formats pf ON pf.id=rps.paper_format_id
                    LEFT JOIN project_personnel scanner ON scanner.id=rps.scanner_id
                    WHERE rps.record_id IN ({placeholders})
                        AND pf.enabled=1
                    ORDER BY pf.sort_order, pf.code
                    """,
                    workflow_ids,
                ).fetchall()
                for status_row in status_rows:
                    record_id = int(status_row["record_id"])
                    statuses_by_record.setdefault(record_id, {})[
                        status_row["code"]
                    ] = dict(status_row)
            for row in result:
                workflow_id = row["workflow_id"]
                row["paper_statuses"] = (
                    statuses_by_record.get(int(workflow_id), {})
                    if workflow_id is not None
                    else {}
                )
            return result, total

    def list_check_ready_system_records(
        self, project_id: int, *, limit: int = 5000
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        rows, _total = self.list_system_records_page(
            project_id,
            limit=limit,
            offset=0,
        )
        for row in rows:
            record_key = str(row.get("record_key") or "")
            if not record_key or record_key in seen:
                continue
            record_status = str(row.get("record_status") or "NOT_STARTED")
            paper_statuses = row.get("paper_statuses") or {}
            has_scan_data = any(
                int(paper.get("scan_pages", 0) or 0) > 0
                or int(paper.get("scan_files", 0) or 0) > 0
                for paper in paper_statuses.values()
            )
            has_existing_scan_backup = self.has_existing_backup_file_for_record(
                project_id, record_key
            )
            has_check_data = (
                row.get("checker_id") is not None
                or bool(str(row.get("check_date") or "").strip())
                or int(row.get("check_pages", 0) or 0) > 0
                or int(row.get("check_files", 0) or 0) > 0
            )
            is_legacy_backup_only = (
                row.get("workflow_id") is None and has_existing_scan_backup
            )
            is_ready_status = (
                record_status == "PENDING_CHECK"
                or (record_status == "COMPLETED" and not has_check_data)
                or is_legacy_backup_only
            )
            if (
                is_ready_status
                and (has_scan_data or has_existing_scan_backup)
                and not has_check_data
                and row.get("backup_status") == "BACKED_UP"
                and has_existing_scan_backup
            ):
                records.append(row)
                seen.add(record_key)
        return records[:limit]

    def get_system_records_summary(
        self,
        project_id: int,
        *,
        search: str = "",
        filters: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Aggregate stats over the entire filtered record set (not just the
        current page), used for the mapfile table's per-column header totals."""
        clause, params, cte = self._system_records_filter(
            project_id, search=search, filters=filters
        )
        with self.connect() as conn:
            record_keys = [
                row["record_key"]
                for row in conn.execute(
                    f"""{cte}
                    SELECT rk.record_key
                    FROM record_keys rk
                    LEFT JOIN backup_summary bs ON bs.record_key=rk.record_key
                    LEFT JOIN record_workflows rw
                        ON rw.project_id=:project_id AND rw.record_key=rk.record_key
                    WHERE {clause}
                    """,
                    params,
                ).fetchall()
            ]
            check_row = conn.execute(
                f"""{cte}
                SELECT
                    COALESCE(SUM(rw.check_pages), 0) AS check_pages,
                    COALESCE(SUM(rw.check_files), 0) AS check_files
                FROM record_keys rk
                LEFT JOIN backup_summary bs ON bs.record_key=rk.record_key
                LEFT JOIN record_workflows rw
                    ON rw.project_id=:project_id AND rw.record_key=rk.record_key
                WHERE {clause}
                """,
                params,
            ).fetchone()
            paper_rows = conn.execute(
                f"""{cte}
                SELECT
                    pf.code AS code,
                    COALESCE(SUM(rps.scan_pages), 0) AS scan_pages,
                    COALESCE(SUM(rps.scan_files), 0) AS scan_files
                FROM record_keys rk
                LEFT JOIN backup_summary bs ON bs.record_key=rk.record_key
                LEFT JOIN record_workflows rw
                    ON rw.project_id=:project_id AND rw.record_key=rk.record_key
                LEFT JOIN record_paper_statuses rps ON rps.record_id=rw.id
                LEFT JOIN paper_formats pf
                    ON pf.id=rps.paper_format_id AND pf.project_id=:project_id AND pf.enabled=1
                WHERE {clause}
                GROUP BY pf.code
                """,
                params,
            ).fetchall()
        return {
            "record_keys": record_keys,
            "check_pages": int(check_row["check_pages"]),
            "check_files": int(check_row["check_files"]),
            "paper_totals": {
                row["code"]: {
                    "scan_pages": int(row["scan_pages"]),
                    "scan_files": int(row["scan_files"]),
                }
                for row in paper_rows
                if row["code"] is not None
            },
        }

    def get_record_workflow(
        self, project_id: int, record_key: str
    ) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT rw.*, scanner.full_name AS scanner_name,
                    checker.full_name AS checker_name
                FROM record_workflows rw
                LEFT JOIN project_personnel scanner ON scanner.id=rw.scanner_id
                LEFT JOIN project_personnel checker ON checker.id=rw.checker_id
                WHERE rw.project_id=? AND rw.record_key=?
                """,
                (project_id, record_key),
            ).fetchone()
            workflow: dict[str, Any] = (
                dict(row)
                if row is not None
                else {
                    "id": None,
                    "project_id": project_id,
                    "record_key": record_key,
                    "scanner_id": None,
                    "scan_date": "",
                    "checker_id": None,
                    "check_date": "",
                    "check_pages": 0,
                    "check_files": 0,
                    "record_status": "NOT_STARTED",
                    "notes": "",
                }
            )
            paper_rows = conn.execute(
                """
                SELECT pf.id AS paper_format_id, pf.code, pf.display_name,
                    rps.scanner_id,
                    scanner.full_name AS scanner_name,
                    COALESCE(rps.scan_date, '') AS scan_date,
                    COALESCE(rps.scan_status, 'UNKNOWN') AS scan_status,
                    COALESCE(rps.scan_pages, 0) AS scan_pages,
                    COALESCE(rps.scan_files, 0) AS scan_files,
                    COALESCE(rps.check_pages, 0) AS check_pages,
                    COALESCE(rps.notes, '') AS notes
                FROM paper_formats pf
                LEFT JOIN record_paper_statuses rps
                    ON rps.paper_format_id=pf.id AND rps.record_id=?
                LEFT JOIN project_personnel scanner ON scanner.id=rps.scanner_id
                WHERE pf.project_id=? AND pf.enabled=1
                ORDER BY pf.sort_order, pf.code
                """,
                (workflow["id"], project_id),
            ).fetchall()
            workflow["paper_statuses"] = [dict(paper_row) for paper_row in paper_rows]
            return workflow

    def save_record_assignment(
        self,
        *,
        project_id: int,
        record_key: str,
        personnel_id: int,
        work_date: str,
        assignment_kind: str = "scan",
        paper_presence: dict[str, bool] | None = None,
    ) -> int:
        record_key = record_key.strip().replace("\\", "/").strip("/")
        if not record_key:
            raise ValueError("Không xác định được mã hồ sơ.")
        normalize_system_date(work_date, "Ngày giao việc")
        if assignment_kind not in {"scan", "check"}:
            raise ValueError("Loại phân công không hợp lệ.")
        now = utc_now()
        with self.connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM project_personnel WHERE id=? AND project_id=? AND enabled=1",
                (personnel_id, project_id),
            ).fetchone()
            if not exists:
                raise ValueError("Nhân sự được chọn không thuộc dự án hoặc đang tắt.")
            workflow = conn.execute(
                """
                SELECT id FROM record_workflows
                WHERE project_id=? AND record_key=?
                """,
                (project_id, record_key),
            ).fetchone()
            if workflow is None:
                scanner_id = personnel_id if assignment_kind == "scan" else None
                checker_id = personnel_id if assignment_kind == "check" else None
                initial_status = "SCANNING" if assignment_kind == "scan" else "NOT_STARTED"
                conn.execute(
                    """
                    INSERT INTO record_workflows(
                        project_id, record_key, scanner_id, scan_date, checker_id,
                        check_date, check_pages, check_files, record_status, notes, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, 0, 0, ?, '', ?, ?)
                    """,
                    (
                        project_id,
                        record_key,
                        scanner_id,
                        "",
                        checker_id,
                        "",
                        initial_status,
                        now,
                        now,
                    ),
                )
            elif assignment_kind == "check":
                conn.execute(
                    """
                    UPDATE record_workflows
                    SET checker_id=?, updated_at=?
                    WHERE id=?
                    """,
                    (personnel_id, now, workflow["id"]),
                )
            else:
                # A fresh scan assignment starts the record (and re-opens a
                # RESCAN_REQUIRED pin so the automated sync can progress again),
                # but never downgrades records already past scanning.
                conn.execute(
                    """
                    UPDATE record_workflows
                    SET scanner_id=?,
                        record_status=CASE
                            WHEN record_status IN ('NOT_STARTED', 'RESCAN_REQUIRED')
                            THEN 'SCANNING' ELSE record_status
                        END,
                        updated_at=?
                    WHERE id=?
                    """,
                    (personnel_id, now, workflow["id"]),
                )
            workflow_id = int(
                conn.execute(
                    """
                    SELECT id FROM record_workflows
                    WHERE project_id=? AND record_key=?
                    """,
                    (project_id, record_key),
                ).fetchone()["id"]
            )
            if paper_presence:
                formats = {
                    row["code"]: int(row["id"])
                    for row in conn.execute(
                        """
                        SELECT id, code FROM paper_formats
                        WHERE project_id=? AND enabled=1
                        """,
                        (project_id,),
                    ).fetchall()
                }
                for code, present in paper_presence.items():
                    format_id = formats.get(code)
                    if format_id is None:
                        continue
                    conn.execute(
                        """
                        INSERT INTO record_paper_statuses(
                            record_id, paper_format_id, scanner_id, scan_date, scan_status,
                            scan_pages, scan_files, check_pages, notes, updated_at
                        ) VALUES(?, ?, NULL, '', ?, 0, 0, 0, '', ?)
                        ON CONFLICT(record_id, paper_format_id) DO UPDATE SET
                            scan_status=CASE
                                WHEN record_paper_statuses.scan_pages>0
                                    OR record_paper_statuses.scan_files>0
                                THEN record_paper_statuses.scan_status
                                ELSE excluded.scan_status
                            END,
                            updated_at=excluded.updated_at
                        """,
                        (
                            workflow_id,
                            format_id,
                            "PENDING_SCAN" if present else "NOT_PRESENT",
                            now,
                        ),
                    )
            return workflow_id

    # ------------------------------------------------------------------
    # Check assignments (thư mục check của người check trên máy trạm)
    # ------------------------------------------------------------------
    def save_check_assignment(
        self,
        *,
        project_id: int,
        record_key: str,
        checker_id: int,
        client_code: str,
        folder_path: str,
    ) -> int:
        record_key = record_key.strip().replace("\\", "/").strip("/")
        folder_path = str(Path(folder_path))
        if not record_key or not folder_path:
            raise ValueError("Cần mã hồ sơ và thư mục check.")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO record_check_assignments(
                    project_id, record_key, checker_id, client_code, folder_path,
                    status, assigned_at, recorded_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, 'ASSIGNED', ?, NULL, ?)
                ON CONFLICT(project_id, record_key, folder_path) DO UPDATE SET
                    checker_id=excluded.checker_id,
                    client_code=excluded.client_code,
                    status='ASSIGNED',
                    assigned_at=excluded.assigned_at,
                    recorded_at=NULL,
                    updated_at=excluded.updated_at
                """,
                (project_id, record_key, checker_id, client_code, folder_path, now, now),
            )
            row = conn.execute(
                """
                SELECT id FROM record_check_assignments
                WHERE project_id=? AND record_key=? AND folder_path=?
                """,
                (project_id, record_key, folder_path),
            ).fetchone()
            return int(row["id"])

    def list_check_assignments(
        self,
        project_id: int,
        *,
        record_key: str | None = None,
        statuses: Iterable[str] = ("ASSIGNED", "RECORDED"),
    ) -> list[sqlite3.Row]:
        status_list = list(statuses)
        sql = "SELECT * FROM record_check_assignments WHERE project_id=?"
        params: list[Any] = [project_id]
        if status_list:
            sql += f" AND status IN ({', '.join('?' for _ in status_list)})"
            params.extend(status_list)
        if record_key is not None:
            sql += " AND record_key=?"
            params.append(record_key.strip().replace("\\", "/").strip("/"))
        sql += " ORDER BY id DESC"
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def mark_check_assignment_recorded(self, assignment_id: int) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE record_check_assignments
                SET status='RECORDED', recorded_at=?, updated_at=?
                WHERE id=?
                """,
                (now, now, assignment_id),
            )

    def save_automated_check_counts(
        self,
        *,
        project_id: int,
        record_key: str,
        pages: int,
        files: int,
        checker_id: int | None = None,
    ) -> None:
        """Record the checker's output counted from their backed-up check
        folder, and close the record (PENDING_CHECK → COMPLETED) once real
        check data exists. A manual RESCAN_REQUIRED pin always wins."""
        record_key = record_key.strip().replace("\\", "/").strip("/")
        if not record_key:
            raise ValueError("Không xác định được mã hồ sơ.")
        now = utc_now()
        check_date = datetime.now().strftime("%Y-%m-%d")
        with self.connect() as conn:
            workflow = conn.execute(
                """
                SELECT id, record_status FROM record_workflows
                WHERE project_id=? AND record_key=?
                """,
                (project_id, record_key),
            ).fetchone()
            if workflow is None:
                return
            conn.execute(
                """
                UPDATE record_workflows
                SET check_pages=?, check_files=?,
                    check_date=COALESCE(NULLIF(check_date, ''), ?),
                    checker_id=COALESCE(checker_id, ?),
                    updated_at=?
                WHERE id=?
                """,
                (max(0, int(pages)), max(0, int(files)), check_date, checker_id, now, workflow["id"]),
            )
            if (pages > 0 or files > 0) and workflow["record_status"] != "RESCAN_REQUIRED":
                conn.execute(
                    """
                    UPDATE record_workflows
                    SET record_status='COMPLETED', updated_at=?
                    WHERE id=?
                    """,
                    (now, workflow["id"]),
                )
            conn.execute(
                """
                INSERT INTO audit_logs(project_id, action, message, created_at)
                VALUES(?, 'RECORD_CHECK_RECORDED', ?, ?)
                """,
                (
                    project_id,
                    f"Recorded check counts for {record_key}: {pages} page(s), {files} file(s)",
                    now,
                ),
            )

    def save_record_workflow(
        self,
        *,
        project_id: int,
        record_key: str,
        scanner_id: int | None,
        scan_date: str,
        checker_id: int | None,
        check_date: str,
        check_pages: int | str = 0,
        check_files: int | str = 0,
        record_status: str,
        notes: str,
        paper_statuses: list[dict[str, Any]],
    ) -> int:
        record_key = record_key.strip().replace("\\", "/").strip("/")
        if not record_key:
            raise ValueError("Không xác định được mã hồ sơ.")
        if record_status not in RECORD_WORKFLOW_STATUSES:
            raise ValueError("Trạng thái hồ sơ không hợp lệ.")
        scan_date = normalize_system_date(scan_date, "Ngày Scan")
        check_date = normalize_system_date(check_date, "Ngày Check")
        try:
            normalized_check_pages = int(check_pages or 0)
            normalized_check_files = int(check_files or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("Số trang/số file check phải là số nguyên.") from exc
        if normalized_check_pages < 0 or normalized_check_files < 0:
            raise ValueError("Số trang/số file check không được âm.")
        format_ids = {int(item["paper_format_id"]) for item in paper_statuses}
        with self.connect() as conn:
            valid_formats = {
                int(row["id"]): row["code"]
                for row in conn.execute(
                    "SELECT id, code FROM paper_formats WHERE project_id=?",
                    (project_id,),
                )
                if int(row["id"]) in format_ids
            }
            if len(valid_formats) != len(format_ids):
                raise ValueError("Danh mục khổ giấy không thuộc dự án.")

            statuses_by_code: dict[str, str] = {}
            normalized_papers: list[tuple[int, int | None, str, str, int, int, int, str]] = []
            for item in paper_statuses:
                format_id = int(item["paper_format_id"])
                paper_scanner_id = (
                    int(item["scanner_id"])
                    if str(item.get("scanner_id") or "").strip()
                    else None
                )
                paper_scan_date = normalize_system_date(
                    str(item.get("scan_date", "")),
                    f"Ngày Scan của {valid_formats[format_id]}",
                )
                scan_status = str(item.get("scan_status", "UNKNOWN"))
                if scan_status not in PAPER_SCAN_STATUSES:
                    raise ValueError("Trạng thái scan khổ giấy không hợp lệ.")
                try:
                    scan_pages = int(item.get("scan_pages") or 0)
                    scan_files = int(item.get("scan_files") or 0)
                    check_pages = int(item.get("check_pages") or 0)
                except (TypeError, ValueError) as exc:
                    raise ValueError("Số trang scan phải là số nguyên.") from exc
                if scan_pages < 0 or scan_files < 0 or check_pages < 0:
                    raise ValueError("Số trang scan không được âm.")
                if (scan_pages > 0 or scan_files > 0) and not paper_scan_date:
                    raise ValueError(f"{valid_formats[format_id]} đã có dữ liệu scan nhưng chưa nhập Ngày Scan.")
                if scan_status in {"UNKNOWN", "NOT_PRESENT"} and (scan_pages or scan_files):
                    raise ValueError(
                        f"{valid_formats[format_id]} chưa có dữ liệu nhưng số trang/số file khác 0."
                    )
                if scan_status in {"SCANNED", "CHECKED"} and scan_pages == 0 and scan_files == 0:
                    raise ValueError(
                        f"{valid_formats[format_id]} đã scan nhưng chưa nhập số trang hoặc số file Scan."
                    )
                statuses_by_code[valid_formats[format_id]] = scan_status
                normalized_papers.append(
                    (
                        format_id,
                        paper_scanner_id,
                        paper_scan_date,
                        scan_status,
                        scan_pages,
                        scan_files,
                        check_pages,
                        str(item.get("notes", "")).strip(),
                    )
                )

            for personnel_id in (
                scanner_id,
                checker_id,
                *[paper_scanner_id for _format_id, paper_scanner_id, *_rest in normalized_papers],
            ):
                if personnel_id is None:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM project_personnel WHERE id=? AND project_id=?",
                    (personnel_id, project_id),
                ).fetchone()
                if not exists:
                    raise ValueError("Nhân sự được chọn không thuộc dự án.")

            now = utc_now()
            conn.execute(
                """
                INSERT INTO record_workflows(
                    project_id, record_key, scanner_id, scan_date, checker_id,
                    check_date, check_pages, check_files, record_status, notes, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, record_key) DO UPDATE SET
                    scanner_id=excluded.scanner_id,
                    scan_date=excluded.scan_date,
                    checker_id=excluded.checker_id,
                    check_date=excluded.check_date,
                    check_pages=excluded.check_pages,
                    check_files=excluded.check_files,
                    record_status=excluded.record_status,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    project_id,
                    record_key,
                    scanner_id,
                    scan_date.strip(),
                    checker_id,
                    check_date.strip(),
                    normalized_check_pages,
                    normalized_check_files,
                    record_status,
                    notes.strip(),
                    now,
                    now,
                ),
            )
            workflow_id = int(
                conn.execute(
                    """
                    SELECT id FROM record_workflows
                    WHERE project_id=? AND record_key=?
                    """,
                    (project_id, record_key),
                ).fetchone()["id"]
            )
            for format_id, paper_scanner_id, paper_scan_date, status, scan_pages, scan_files, check_pages, paper_notes in normalized_papers:
                conn.execute(
                    """
                    INSERT INTO record_paper_statuses(
                        record_id, paper_format_id, scanner_id, scan_date, scan_status, scan_pages,
                        scan_files, check_pages, notes, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(record_id, paper_format_id) DO UPDATE SET
                        scanner_id=excluded.scanner_id,
                        scan_date=excluded.scan_date,
                        scan_status=excluded.scan_status,
                        scan_pages=excluded.scan_pages,
                        scan_files=excluded.scan_files,
                        check_pages=excluded.check_pages,
                        notes=excluded.notes,
                        updated_at=excluded.updated_at
                    """,
                    (
                        workflow_id,
                        format_id,
                        paper_scanner_id,
                        paper_scan_date,
                        status,
                        scan_pages,
                        scan_files,
                        check_pages,
                        paper_notes,
                        now,
                    ),
                )
            conn.execute(
                """
                INSERT INTO audit_logs(
                    project_id, action, message, created_at
                ) VALUES(?, 'RECORD_WORKFLOW_UPDATED', ?, ?)
                """,
                (project_id, f"Updated workflow for {record_key}", now),
            )
            return workflow_id

    def save_automated_scan_counts(
        self,
        *,
        project_id: int,
        record_key: str,
        paper_counts: dict[str, dict[str, int]],
    ) -> int:
        record_key = record_key.strip().replace("\\", "/").strip("/")
        if not record_key:
            raise ValueError("Không xác định được mã hồ sơ.")
        now = utc_now()
        scan_date = datetime.now().strftime("%Y-%m-%d")
        with self.connect() as conn:
            workflow = conn.execute(
                """
                SELECT * FROM record_workflows
                WHERE project_id=? AND record_key=?
                """,
                (project_id, record_key),
            ).fetchone()
            if workflow is None:
                conn.execute(
                    """
                    INSERT INTO record_workflows(
                        project_id, record_key, scanner_id, scan_date, checker_id,
                        check_date, check_pages, check_files, record_status, notes, created_at, updated_at
                    ) VALUES(?, ?, NULL, '', NULL, '', 0, 0, 'NOT_STARTED', '', ?, ?)
                    """,
                    (project_id, record_key, now, now),
                )
            elif any(
                int(counts.get("pages", 0) or 0) > 0 or int(counts.get("files", 0) or 0) > 0
                for counts in paper_counts.values()
            ):
                conn.execute(
                    """
                    UPDATE record_workflows
                    SET scan_date=COALESCE(NULLIF(scan_date, ''), ?),
                        updated_at=?
                    WHERE id=?
                    """,
                    (scan_date, now, workflow["id"]),
                )
            workflow_id = int(
                conn.execute(
                    """
                    SELECT id FROM record_workflows
                    WHERE project_id=? AND record_key=?
                    """,
                    (project_id, record_key),
                ).fetchone()["id"]
            )
            formats = conn.execute(
                """
                SELECT id, code, requires_separate_scan
                FROM paper_formats
                WHERE project_id=? AND enabled=1
                """,
                (project_id,),
            ).fetchall()
            scanned_codes = {
                code
                for code, counts in paper_counts.items()
                if int(counts.get("pages", 0) or 0) > 0
                or int(counts.get("files", 0) or 0) > 0
            }
            has_scan_data = bool(scanned_codes)
            presence_rows = conn.execute(
                """
                SELECT pf.code, rps.scan_status
                FROM paper_formats pf
                LEFT JOIN record_paper_statuses rps
                    ON rps.paper_format_id=pf.id AND rps.record_id=?
                WHERE pf.project_id=? AND pf.enabled=1
                """,
                (workflow_id, project_id),
            ).fetchall()
            pending_scan_codes = {
                row["code"]
                for row in presence_rows
                if row["scan_status"] == "PENDING_SCAN"
            }
            required_codes = scanned_codes | pending_scan_codes
            missing_required_codes = required_codes - scanned_codes
            workflow_row = conn.execute(
                """
                SELECT record_status FROM record_workflows
                WHERE id=?
                """,
                (workflow_id,),
            ).fetchone()
            current_record_status = (
                workflow_row["record_status"] if workflow_row else "NOT_STARTED"
            )
            if has_scan_data and current_record_status not in MANUAL_RECORD_STATUSES:
                next_record_status = (
                    "PENDING_PAPER" if missing_required_codes else "PENDING_CHECK"
                )
                conn.execute(
                    """
                    UPDATE record_workflows
                    SET record_status=?, updated_at=?
                    WHERE id=?
                    """,
                    (next_record_status, now, workflow_id),
                )
            for paper_format in formats:
                code = paper_format["code"]
                counts = paper_counts.get(code, {})
                pages = max(0, int(counts.get("pages", 0) or 0))
                files = max(0, int(counts.get("files", 0) or 0))
                existing_status_row = conn.execute(
                    """
                    SELECT scan_status FROM record_paper_statuses
                    WHERE record_id=? AND paper_format_id=?
                    """,
                    (workflow_id, paper_format["id"]),
                ).fetchone()
                existing_status = (
                    existing_status_row["scan_status"] if existing_status_row else "UNKNOWN"
                )
                status = "SCANNED" if pages or files else existing_status
                conn.execute(
                    """
                    INSERT INTO record_paper_statuses(
                        record_id, paper_format_id, scanner_id, scan_date, scan_status,
                        scan_pages, scan_files, check_pages, notes, updated_at
                    ) VALUES(
                        ?, ?,
                        (SELECT scanner_id FROM record_workflows WHERE id=?),
                        CASE WHEN ?='SCANNED'
                            THEN COALESCE(
                                NULLIF((SELECT scan_date FROM record_paper_statuses
                                    WHERE record_id=? AND paper_format_id=?), ''),
                                ?
                            )
                            ELSE ''
                        END,
                        ?, ?, ?, 0, '', ?
                    )
                    ON CONFLICT(record_id, paper_format_id) DO UPDATE SET
                        scanner_id=COALESCE(record_paper_statuses.scanner_id, excluded.scanner_id),
                        scan_date=excluded.scan_date,
                        scan_status=excluded.scan_status,
                        scan_pages=excluded.scan_pages,
                        scan_files=excluded.scan_files,
                        updated_at=excluded.updated_at
                    """,
                    (
                        workflow_id,
                        paper_format["id"],
                        workflow_id,
                        status,
                        workflow_id,
                        paper_format["id"],
                        scan_date,
                        status,
                        pages,
                        files,
                        now,
                    ),
                )
            conn.execute(
                """
                INSERT INTO audit_logs(project_id, action, message, created_at)
                VALUES(?, 'SCAN_COUNTS_SYNCED', ?, ?)
                """,
                (project_id, f"Synced automated scan counts for {record_key}", now),
            )
            return workflow_id

    def record_conflict(
        self,
        *,
        backup_file_id: int,
        client_code: str,
        source_path: str,
        dest_path: str,
        source_hash: str | None,
        dest_hash: str | None,
    ) -> int:
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM conflicts WHERE backup_file_id=? AND status='OPEN'",
                (backup_file_id,),
            ).fetchone()
            if existing:
                return int(existing["id"])
            cur = conn.execute(
                """
                INSERT INTO conflicts(
                    backup_file_id, client_code, source_path, dest_path,
                    source_hash, dest_hash, status, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, 'OPEN', ?)
                """,
                (
                    backup_file_id, client_code, source_path, dest_path,
                    source_hash, dest_hash, utc_now(),
                ),
            )
            return int(cur.lastrowid)

    def list_conflicts(self, project_id: int, status: str = "OPEN") -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT c.* FROM conflicts c
                JOIN backup_files b ON b.id=c.backup_file_id
                WHERE c.status=? AND b.project_id=? ORDER BY c.id DESC
                """,
                (status, project_id),
            ).fetchall()

    def resolve_conflict(self, conflict_id: int, resolution: str, archive_path: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE conflicts SET status='RESOLVED', resolution=?,
                    archive_path=?, resolved_at=? WHERE id=?
                """,
                (resolution, archive_path, utc_now(), conflict_id),
            )

    def dashboard_counts(self, project_id: int) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) count FROM backup_files WHERE project_id=? GROUP BY status",
                (project_id,),
            ).fetchall()
            counts = {row["status"]: int(row["count"]) for row in rows}
            counts["OPEN_CONFLICTS"] = int(conn.execute(
                """
                SELECT COUNT(*) count FROM conflicts c
                JOIN backup_files b ON b.id=c.backup_file_id
                WHERE c.status='OPEN' AND b.project_id=?
                """,
                (project_id,),
            ).fetchone()["count"])
            return counts

    def dashboard_counts_all_projects(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) count FROM backup_files GROUP BY status"
            ).fetchall()
            counts = {row["status"]: int(row["count"]) for row in rows}
            counts["OPEN_CONFLICTS"] = int(conn.execute(
                "SELECT COUNT(*) count FROM conflicts WHERE status='OPEN'"
            ).fetchone()["count"])
            counts["PROJECTS"] = int(conn.execute(
                "SELECT COUNT(*) count FROM projects"
            ).fetchone()["count"])
            return counts

    # ------------------------------------------------------------------
    # Mapfile
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_mapfile_profile(row: sqlite3.Row) -> MapfileProfile:
        return MapfileProfile(
            row["id"], row["project_id"], row["name"], row["sheet_name"], row["project_column"],
            row["year_column"], row["case_type_column"], row["case_number_column"],
            row["file_name_column"],
        )

    def save_mapfile_profile(self, profile: MapfileProfile) -> int:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO mapfile_profiles(
                    project_id, name, sheet_name, project_column, year_column, case_type_column,
                    case_number_column, file_name_column, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, name) DO UPDATE SET
                    sheet_name=excluded.sheet_name, project_column=excluded.project_column,
                    year_column=excluded.year_column, case_type_column=excluded.case_type_column,
                    case_number_column=excluded.case_number_column,
                    file_name_column=excluded.file_name_column, updated_at=excluded.updated_at
                """,
                (
                    profile.project_id, profile.name, profile.sheet_name, profile.project_column,
                    profile.year_column, profile.case_type_column,
                    profile.case_number_column, profile.file_name_column, now, now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM mapfile_profiles WHERE project_id=? AND name=?",
                (profile.project_id, profile.name),
            ).fetchone()
            return int(row["id"])

    def get_mapfile_profile(self, project_id: int, name: str = "Default") -> MapfileProfile:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM mapfile_profiles WHERE project_id=? AND name=?",
                (project_id, name),
            ).fetchone()
        if not row:
            raise ValueError(f"Mapfile profile not found for project {project_id}: {name}")
        return self._row_to_mapfile_profile(row)

    def create_mapfile_import(self, project_id: int, profile_id: int, file_path: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO mapfile_imports(
                    project_id, profile_id, file_path, imported_at, row_count
                ) VALUES(?, ?, ?, ?, 0)
                """,
                (project_id, profile_id, file_path, utc_now()),
            )
            return int(cur.lastrowid)

    def add_mapfile_rows(self, import_id: int, rows: list[tuple[int, dict[str, Any], str]]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO mapfile_rows(
                    row_number, import_id, raw_json, expected_relative_path, record_key
                ) VALUES(?, ?, ?, ?, ?)
                """,
                [
                    (
                        number,
                        import_id,
                        json.dumps(raw, ensure_ascii=False),
                        expected,
                        record_key_from_expected_path(expected),
                    )
                    for number, raw, expected in rows
                ],
            )
            conn.execute(
                "UPDATE mapfile_imports SET row_count=? WHERE id=?", (len(rows), import_id)
            )

    def append_mapfile_row(
        self,
        import_id: int,
        raw: dict[str, Any],
        expected: str,
        *,
        record_key: str | None = None,
    ) -> int:
        normalized_record_key = (
            record_key.strip().replace("\\", "/").strip("/")
            if record_key is not None
            else record_key_from_expected_path(expected)
        )
        with self.connect() as conn:
            row_number = int(
                conn.execute(
                    "SELECT COALESCE(MAX(row_number), 1) + 1 FROM mapfile_rows WHERE import_id=?",
                    (import_id,),
                ).fetchone()[0]
            )
            cur = conn.execute(
                """
                INSERT INTO mapfile_rows(
                    row_number, import_id, raw_json, expected_relative_path, record_key
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (
                    row_number,
                    import_id,
                    json.dumps(raw, ensure_ascii=False),
                    expected,
                    normalized_record_key,
                ),
            )
            conn.execute(
                "UPDATE mapfile_imports SET row_count=row_count + 1 WHERE id=?",
                (import_id,),
            )
            return int(cur.lastrowid)

    def latest_mapfile_import_id(self, project_id: int) -> int | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM mapfile_imports WHERE project_id=? ORDER BY id DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            return int(row["id"]) if row else None

    def get_mapfile_import(self, import_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM mapfile_imports WHERE id=?", (import_id,)
            ).fetchone()

    def list_mapfile_rows(self, import_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM mapfile_rows WHERE import_id=? ORDER BY row_number",
                (import_id,),
            ).fetchall()

    def get_mapfile_row(self, row_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM mapfile_rows WHERE id=?", (row_id,)).fetchone()

    def update_mapfile_row_status(self, row_id: int, status: str, message: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE mapfile_rows SET status=?, message=? WHERE id=?",
                (status, message, row_id),
            )

    def update_mapfile_row_source(
        self,
        row_id: int,
        raw: dict[str, Any],
        expected_relative_path: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE mapfile_rows
                SET raw_json=?, expected_relative_path=?, record_key=?
                WHERE id=?
                """,
                (
                    json.dumps(raw, ensure_ascii=False),
                    expected_relative_path,
                    record_key_from_expected_path(expected_relative_path),
                    row_id,
                ),
            )

    def update_system_record_source(
        self,
        project_id: int,
        old_record_key: str,
        new_record_key: str,
        raw: dict[str, Any],
        expected_relative_path: str,
    ) -> None:
        old_record_key = old_record_key.strip().replace("\\", "/").strip("/")
        new_record_key = new_record_key.strip().replace("\\", "/").strip("/")
        if not old_record_key or not new_record_key:
            raise ValueError("Record key is required")
        with self.connect() as conn:
            latest_import = conn.execute(
                """
                SELECT id FROM mapfile_imports
                WHERE project_id=? ORDER BY id DESC LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            if latest_import is None:
                raise ValueError("Project has no mapfile import to update")
            import_id = int(latest_import["id"])
            duplicate = conn.execute(
                """
                SELECT 1 FROM mapfile_rows
                WHERE import_id=? AND record_key=? AND record_key<>?
                LIMIT 1
                """,
                (import_id, new_record_key, old_record_key),
            ).fetchone()
            if duplicate:
                raise ValueError(f"Record already exists: {new_record_key}")
            cur = conn.execute(
                """
                UPDATE mapfile_rows
                SET raw_json=?, expected_relative_path=?, record_key=?
                WHERE import_id=? AND record_key=?
                """,
                (
                    json.dumps(raw, ensure_ascii=False),
                    expected_relative_path,
                    new_record_key,
                    import_id,
                    old_record_key,
                ),
            )
            if cur.rowcount == 0:
                raise ValueError(f"Mapfile row not found: {old_record_key}")
            if old_record_key != new_record_key:
                workflow_conflict = conn.execute(
                    """
                    SELECT 1 FROM record_workflows
                    WHERE project_id=? AND record_key=? LIMIT 1
                    """,
                    (project_id, new_record_key),
                ).fetchone()
                if workflow_conflict:
                    raise ValueError(f"Workflow already exists: {new_record_key}")
                conn.execute(
                    """
                    UPDATE record_workflows
                    SET record_key=?, updated_at=?
                    WHERE project_id=? AND record_key=?
                    """,
                    (new_record_key, utc_now(), project_id, old_record_key),
                )
                conn.execute(
                    """
                    UPDATE backup_files
                    SET record_key=?
                    WHERE project_id=? AND record_key=?
                    """,
                    (new_record_key, project_id, old_record_key),
                )
                conn.execute(
                    """
                    UPDATE record_check_assignments
                    SET record_key=?, updated_at=?
                    WHERE project_id=? AND record_key=?
                    """,
                    (new_record_key, utc_now(), project_id, old_record_key),
                )
                conn.execute(
                    """
                    UPDATE project_tasks
                    SET record_key=?, updated_at=?
                    WHERE project_id=? AND record_key=?
                    """,
                    (new_record_key, utc_now(), project_id, old_record_key),
                )

    def delete_system_record(self, project_id: int, record_key: str) -> int:
        record_key = record_key.strip().replace("\\", "/").strip("/")
        if not record_key:
            raise ValueError("Record key is required")
        now = utc_now()
        with self.connect() as conn:
            latest_import = conn.execute(
                """
                SELECT id FROM mapfile_imports
                WHERE project_id=? ORDER BY id DESC LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            deleted_rows = 0
            if latest_import is not None:
                cur = conn.execute(
                    """
                    DELETE FROM mapfile_rows
                    WHERE import_id=? AND record_key=?
                    """,
                    (int(latest_import["id"]), record_key),
                )
                deleted_rows += int(cur.rowcount or 0)
                conn.execute(
                    """
                    UPDATE mapfile_imports
                    SET row_count=(
                        SELECT COUNT(*) FROM mapfile_rows WHERE import_id=?
                    )
                    WHERE id=?
                    """,
                    (int(latest_import["id"]), int(latest_import["id"])),
                )
            workflow = conn.execute(
                """
                SELECT id FROM record_workflows
                WHERE project_id=? AND record_key=?
                """,
                (project_id, record_key),
            ).fetchone()
            if workflow is not None:
                conn.execute("DELETE FROM record_workflows WHERE id=?", (workflow["id"],))
                deleted_rows += 1
            backup_rows = conn.execute(
                """
                SELECT id FROM backup_files
                WHERE project_id=? AND record_key=?
                """,
                (project_id, record_key),
            ).fetchall()
            if backup_rows:
                backup_ids = [int(row["id"]) for row in backup_rows]
                placeholders = ", ".join("?" for _ in backup_ids)
                conn.execute(
                    f"DELETE FROM conflicts WHERE backup_file_id IN ({placeholders})",
                    backup_ids,
                )
                conn.execute(
                    f"DELETE FROM backup_file_paper_sizes WHERE backup_file_id IN ({placeholders})",
                    backup_ids,
                )
                conn.execute(
                    f"DELETE FROM backup_files WHERE id IN ({placeholders})",
                    backup_ids,
                )
                deleted_rows += len(backup_ids)
            conn.execute(
                """
                DELETE FROM record_check_assignments
                WHERE project_id=? AND record_key=?
                """,
                (project_id, record_key),
            )
            conn.execute(
                """
                DELETE FROM project_tasks
                WHERE project_id=? AND (
                    record_key=? OR (record_key='' AND description LIKE ?)
                )
                """,
                (project_id, record_key, f"%{record_key}%"),
            )
            conn.execute(
                """
                INSERT INTO audit_logs(project_id, action, message, created_at)
                VALUES(?, 'SYSTEM_RECORD_DELETED', ?, ?)
                """,
                (project_id, f"Deleted system mapfile record {record_key}", now),
            )
            return deleted_rows

    def mark_mapfile_row_done(
        self, row_id: int, personnel_id: int | None, *, done_at: str | None = None
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE mapfile_rows SET is_done=1, done_at=?, done_by=? WHERE id=?",
                (done_at or utc_now(), personnel_id, row_id),
            )

    def unmark_mapfile_row_done(self, row_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE mapfile_rows SET is_done=0, done_at=NULL, done_by=NULL WHERE id=?",
                (row_id,),
            )

    def list_report_rows(self, project_id: int) -> dict[str, list[sqlite3.Row]]:
        with self.connect() as conn:
            return {
                "projects": conn.execute(
                    "SELECT * FROM projects WHERE id=?", (project_id,)
                ).fetchall(),
                "backup_files": conn.execute(
                    "SELECT * FROM backup_files WHERE project_id=? ORDER BY id DESC",
                    (project_id,),
                ).fetchall(),
                "conflicts": conn.execute(
                    """
                    SELECT c.* FROM conflicts c JOIN backup_files b ON b.id=c.backup_file_id
                    WHERE b.project_id=? ORDER BY c.id DESC
                    """,
                    (project_id,),
                ).fetchall(),
                "mapfile_rows": conn.execute(
                    """
                    SELECT r.* FROM mapfile_rows r
                    JOIN mapfile_imports i ON i.id=r.import_id
                    WHERE i.project_id=? ORDER BY r.id DESC
                    """,
                    (project_id,),
                ).fetchall(),
                "personnel": conn.execute(
                    "SELECT * FROM project_personnel WHERE project_id=? ORDER BY personnel_code",
                    (project_id,),
                ).fetchall(),
                "tasks": conn.execute(
                    """
                    SELECT t.*, p.personnel_code, p.full_name AS assignee_name
                    FROM project_tasks t JOIN project_personnel p ON p.id=t.assignee_id
                    WHERE t.project_id=? ORDER BY t.id DESC
                    """,
                    (project_id,),
                ).fetchall(),
            }

    # ------------------------------------------------------------------
    # Personnel authentication
    # ------------------------------------------------------------------
    def set_personnel_pin(self, personnel_id: int, pin: str, *, must_change: bool = True) -> None:
        if not (pin.isdigit() and len(pin) == 6):
            raise ValueError("PIN must contain exactly 6 digits")
        salt = secrets.token_bytes(16)
        with self.connect() as conn:
            if not conn.execute(
                "SELECT 1 FROM project_personnel WHERE id=?", (personnel_id,)
            ).fetchone():
                raise ValueError("Personnel not found")
            conn.execute(
                """
                INSERT INTO personnel_credentials(
                    personnel_id, salt, pin_hash, must_change_pin,
                    failed_attempts, locked_until, updated_at
                ) VALUES(?, ?, ?, ?, 0, NULL, ?)
                ON CONFLICT(personnel_id) DO UPDATE SET
                    salt=excluded.salt, pin_hash=excluded.pin_hash,
                    must_change_pin=excluded.must_change_pin,
                    failed_attempts=0, locked_until=NULL, updated_at=excluded.updated_at
                """,
                (
                    personnel_id, salt.hex(), _password_hash(pin, salt),
                    int(must_change), utc_now(),
                ),
            )

    def verify_personnel_pin(
        self, project_code: str, personnel_code: str, pin: str
    ) -> sqlite3.Row | None:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT p.*, c.salt, c.pin_hash, c.must_change_pin,
                       c.failed_attempts, c.locked_until
                FROM project_personnel p
                JOIN projects pr ON pr.id=p.project_id
                JOIN personnel_credentials c ON c.personnel_id=p.id
                WHERE UPPER(pr.project_code)=UPPER(?)
                  AND UPPER(p.personnel_code)=UPPER(?) AND p.enabled=1 AND pr.enabled=1
                """,
                (project_code.strip(), personnel_code.strip()),
            ).fetchone()
            if not row:
                return None
            if row["locked_until"] and row["locked_until"] > now:
                raise ValueError("PERSONNEL_LOCKED")
            actual = _password_hash(pin, bytes.fromhex(row["salt"]))
            if not hmac.compare_digest(actual, row["pin_hash"]):
                attempts = int(row["failed_attempts"]) + 1
                locked_until = (
                    (datetime.now(timezone.utc) + timedelta(minutes=15))
                    .replace(microsecond=0).isoformat()
                    if attempts >= 5 else None
                )
                conn.execute(
                    """
                    UPDATE personnel_credentials
                    SET failed_attempts=?, locked_until=?, updated_at=?
                    WHERE personnel_id=?
                    """,
                    (attempts, locked_until, now, row["id"]),
                )
                return None
            conn.execute(
                """
                UPDATE personnel_credentials
                SET failed_attempts=0, locked_until=NULL, updated_at=?
                WHERE personnel_id=?
                """,
                (now, row["id"]),
            )
            return row

    def change_personnel_pin(
        self, project_code: str, personnel_code: str, current_pin: str, new_pin: str
    ) -> sqlite3.Row:
        person = self.verify_personnel_pin(project_code, personnel_code, current_pin)
        if not person:
            raise ValueError("Current PIN is incorrect")
        self.set_personnel_pin(int(person["id"]), new_pin, must_change=False)
        return person

    # ------------------------------------------------------------------
    # Durable jobs, leases, locks and service heartbeat
    # ------------------------------------------------------------------
    def enqueue_job(
        self,
        project_id: int,
        job_type: str,
        *,
        requested_by_type: str = "SYSTEM",
        requested_by_id: int | None = None,
        payload: dict[str, Any] | None = None,
        scheduled_at: str | None = None,
        deduplicate: bool = True,
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            if deduplicate:
                existing = conn.execute(
                    """
                    SELECT id FROM backup_jobs
                    WHERE project_id=? AND job_type=? AND status IN ('PENDING','RUNNING')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (project_id, job_type),
                ).fetchone()
                if existing:
                    return int(existing["id"])
            cur = conn.execute(
                """
                INSERT INTO backup_jobs(
                    project_id, job_type, status, requested_by_type,
                    requested_by_id, payload_json, scheduled_at, created_at
                ) VALUES(?, ?, 'PENDING', ?, ?, ?, ?, ?)
                """,
                (
                    project_id, job_type, requested_by_type, requested_by_id,
                    json.dumps(payload or {}, ensure_ascii=False),
                    scheduled_at or now, now,
                ),
            )
            return int(cur.lastrowid)

    def claim_next_job(self, owner: str, lease_seconds: int = 300) -> sqlite3.Row | None:
        now = utc_now()
        expires = (
            datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        ).replace(microsecond=0).isoformat()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT j.* FROM backup_jobs j
                WHERE j.scheduled_at<=?
                  AND (
                    j.status='PENDING'
                    OR (j.status='RUNNING' AND j.lease_expires_at<?)
                  )
                  AND NOT EXISTS(
                    SELECT 1 FROM backup_jobs active
                    WHERE active.project_id=j.project_id
                      AND active.status='RUNNING'
                      AND active.lease_expires_at>=?
                  )
                ORDER BY j.scheduled_at, j.id LIMIT 1
                """,
                (now, now, now),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """
                UPDATE backup_jobs SET status='RUNNING', started_at=COALESCE(started_at, ?),
                    lease_owner=?, lease_expires_at=?, error_code=NULL, error_detail=NULL
                WHERE id=?
                """,
                (now, owner, expires, row["id"]),
            )
            return conn.execute(
                "SELECT * FROM backup_jobs WHERE id=?", (row["id"],)
            ).fetchone()

    def finish_job(
        self,
        job_id: int,
        status: str,
        *,
        counters: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        if status not in {"SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"}:
            raise ValueError(f"Invalid final job status: {status}")
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE backup_jobs SET status=?, counters_json=?, error_code=?,
                    error_detail=?, finished_at=?, lease_owner=NULL, lease_expires_at=NULL
                WHERE id=?
                """,
                (
                    status, json.dumps(counters or {}, ensure_ascii=False),
                    error_code, error_detail, utc_now(), job_id,
                ),
            )

    def renew_job_lease(self, job_id: int, owner: str, lease_seconds: int = 300) -> None:
        expires = (
            datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        ).replace(microsecond=0).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE backup_jobs SET lease_expires_at=?
                WHERE id=? AND status='RUNNING' AND lease_owner=?
                """,
                (expires, job_id, owner),
            )

    def list_jobs(
        self, project_id: int | None = None, *, limit: int = 50, offset: int = 0
    ) -> list[sqlite3.Row]:
        with self.connect() as conn:
            if project_id is None:
                return conn.execute(
                    "SELECT * FROM backup_jobs ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            return conn.execute(
                """
                SELECT * FROM backup_jobs WHERE project_id=?
                ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                (project_id, limit, offset),
            ).fetchall()

    def acquire_lock(self, resource_key: str, owner: str, lease_seconds: int = 300) -> bool:
        now = utc_now()
        expires = (
            datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        ).replace(microsecond=0).isoformat()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM operation_locks WHERE expires_at<?", (now,))
            try:
                conn.execute(
                    "INSERT INTO operation_locks(resource_key, owner, expires_at) VALUES(?, ?, ?)",
                    (resource_key, owner, expires),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def release_lock(self, resource_key: str, owner: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM operation_locks WHERE resource_key=? AND owner=?",
                (resource_key, owner),
            )

    def update_heartbeat(self, instance_id: str, version: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_heartbeat(instance_id, version, last_seen_at, started_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(instance_id) DO UPDATE SET
                    version=excluded.version, last_seen_at=excluded.last_seen_at
                """,
                (instance_id, version, now, now),
            )

    def latest_heartbeat(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM service_heartbeat ORDER BY last_seen_at DESC LIMIT 1"
            ).fetchone()

    def job_summary(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) count FROM backup_jobs GROUP BY status"
            ).fetchall()
            return {row["status"]: int(row["count"]) for row in rows}

    def list_mapfile_rows_page(
        self,
        import_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        exclude_status: str | None = None,
        done: bool | None = None,
        search: str = "",
    ) -> tuple[list[sqlite3.Row], int]:
        where = ["import_id=?"]
        params: list[Any] = [import_id]
        if status:
            where.append("status=?")
            params.append(status)
        if exclude_status:
            where.append("status<>?")
            params.append(exclude_status)
        if done is not None:
            where.append("is_done=?")
            params.append(int(done))
        if search.strip():
            where.append("(raw_json LIKE ? OR expected_relative_path LIKE ?)")
            term = f"%{search.strip()}%"
            params.extend([term, term])
        clause = " AND ".join(where)
        with self.connect() as conn:
            total = int(conn.execute(
                f"SELECT COUNT(*) FROM mapfile_rows WHERE {clause}", params
            ).fetchone()[0])
            rows = conn.execute(
                f"""
                SELECT * FROM mapfile_rows WHERE {clause}
                ORDER BY row_number LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
            return rows, total
