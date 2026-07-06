from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import shutil
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .constants import DEFAULT_POLL_INTERVAL_SECONDS, DEFAULT_STABILITY_WAIT_SECONDS
from .models import (
    Client,
    DirectoryLevel,
    MapfileProfile,
    Personnel,
    Project,
    ProjectSettings,
    ProjectTask,
)


SCHEMA_VERSION = 4
DEFAULT_ADMIN_PASSWORD = "Admin@123"
PBKDF2_ITERATIONS = 600_000

DEFAULT_SETTINGS_KEYS = {
    "poll_interval_seconds": "default_poll_interval_seconds",
    "stability_wait_seconds": "default_stability_wait_seconds",
    "numeric_sequence_check": "default_numeric_sequence_check",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(assignee_id) REFERENCES project_personnel(id),
                UNIQUE(project_id, task_code)
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
            if project.id is not None:
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
                return project.id
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
        return project_id

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
                allowed = sorted({
                    value.strip().upper() for value in level.allowed_values if value.strip()
                })
                if level.validation_type == "ENUM" and not allowed:
                    raise ValueError(f"Allowed values are required for {display_name}")
                conn.execute(
                    """
                    INSERT INTO project_directory_levels(
                        project_id, position, display_name, validation_type, allowed_values_json
                    ) VALUES(?, ?, ?, ?, ?)
                    """,
                    (
                        project_id, position, display_name, level.validation_type,
                        json.dumps(allowed, ensure_ascii=False),
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
            conn.execute(
                """
                INSERT INTO project_tasks(
                    project_id, task_code, title, description, assignee_id, due_date,
                    priority, status, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, task_code) DO UPDATE SET
                    title=excluded.title, description=excluded.description,
                    assignee_id=excluded.assignee_id, due_date=excluded.due_date,
                    priority=excluded.priority, status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    task.project_id, task.task_code.strip().upper(), task.title.strip(),
                    task.description.strip(), task.assignee_id, task.due_date.strip(),
                    task.priority, task.status, now, now,
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
    ) -> int:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO backup_files(
                    project_id, client_code, source_path, project_code,
                    relative_project_path, dest_path, file_size, source_mtime,
                    hash_sha256, status, error_message, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, client_code, source_path) DO UPDATE SET
                    project_code=excluded.project_code,
                    relative_project_path=excluded.relative_project_path,
                    dest_path=excluded.dest_path, file_size=excluded.file_size,
                    source_mtime=excluded.source_mtime,
                    hash_sha256=COALESCE(excluded.hash_sha256, backup_files.hash_sha256),
                    status=excluded.status, error_message=excluded.error_message
                """,
                (
                    project_id, client_code, source_path, project_code,
                    relative_project_path, dest_path, file_size, source_mtime,
                    hash_sha256, status, error_message, now,
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

    def get_backup_file(self, backup_file_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM backup_files WHERE id=?", (backup_file_id,)).fetchone()

    def find_backup_file_by_relative_path(
        self, project_id: int, relative_path: str
    ) -> sqlite3.Row | None:
        """Look up an already-backed-up file for 1 mapfile row without loading the
        whole backup_files table (used by MapfileService.reconcile_row)."""
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM backup_files
                WHERE project_id=? AND (project_code || '/' || relative_project_path)=?
                    AND status IN ('HASH_PENDING', 'VERIFIED_HASH', 'LOCKED', 'ALREADY_EXISTS')
                ORDER BY id DESC LIMIT 1
                """,
                (project_id, relative_path.replace("\\", "/")),
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
                    row_number, import_id, raw_json, expected_relative_path
                ) VALUES(?, ?, ?, ?)
                """,
                [
                    (number, import_id, json.dumps(raw, ensure_ascii=False), expected)
                    for number, raw, expected in rows
                ],
            )
            conn.execute(
                "UPDATE mapfile_imports SET row_count=? WHERE id=?", (len(rows), import_id)
            )

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
