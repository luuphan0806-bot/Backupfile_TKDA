from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scan_backup_manager.backup import BackupManager
from scan_backup_manager.constants import STATUS_LOCKED
from scan_backup_manager.db import Database
from scan_backup_manager.models import Client, DirectoryLevel, Personnel, Project, ProjectSettings
from scan_backup_manager.service_core import BackupJobService, JOB_SCAN


def configured_db(tmp_path: Path) -> tuple[Database, int, Path]:
    db = Database(tmp_path / "app.sqlite3")
    project_id = db.create_project(
        Project(
            None, "PROJECT_ALPHA", "Alpha", str(tmp_path / "backup"),
            str(tmp_path / "staging"), str(tmp_path / "conflicts"),
            str(tmp_path / "reports"),
        )
    )
    db.save_project_settings(ProjectSettings(project_id, 300, 0, False))
    db.save_directory_levels(
        project_id, [DirectoryLevel(None, project_id, 1, "Năm", "YEAR4", [])]
    )
    share = tmp_path / "share"
    source = share / "PROJECT_ALPHA" / "2026" / "1.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"pdf")
    db.save_client(Client(None, project_id, "SCAN01", "", str(share)))
    return db, project_id, source


def test_v3_to_v4_migration_preserves_project(tmp_path: Path) -> None:
    db, project_id, _source = configured_db(tmp_path)
    db_path = db.db_path
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE app_meta SET value='3' WHERE key='schema_version'")
        for table in ("backup_jobs", "operation_locks", "service_heartbeat", "personnel_credentials"):
            conn.execute(f"DROP TABLE {table}")

    migrated = Database(db_path)

    assert migrated.get_project(project_id).project_code == "PROJECT_ALPHA"
    assert migrated.migration_backup_path is not None
    assert migrated.migration_backup_path.exists()


def test_job_claim_prevents_parallel_project_job(tmp_path: Path) -> None:
    db, project_id, _source = configured_db(tmp_path)
    first = db.enqueue_job(project_id, JOB_SCAN, deduplicate=False)
    db.enqueue_job(project_id, JOB_SCAN, deduplicate=False)

    claimed = db.claim_next_job("worker-a")

    assert claimed["id"] == first
    assert db.claim_next_job("worker-b") is None


def test_service_processes_durable_scan_job(tmp_path: Path) -> None:
    db, project_id, _source = configured_db(tmp_path)
    job_id = db.enqueue_job(project_id, JOB_SCAN)

    assert BackupJobService(db, instance_id="test").process_one()

    job = next(row for row in db.list_jobs(project_id) if row["id"] == job_id)
    assert job["status"] == "SUCCEEDED"


def test_integrity_verification_no_longer_needs_source(tmp_path: Path) -> None:
    db, project_id, source = configured_db(tmp_path)
    BackupManager(db).run_all_enabled(project_id)
    source.unlink()

    assert BackupManager(db).verify_hash_pending(project_id) == 1
    assert db.list_backup_files(project_id)[0]["status"] == STATUS_LOCKED


def test_personnel_pin_lock_and_reset(tmp_path: Path) -> None:
    db, project_id, _source = configured_db(tmp_path)
    personnel_id = db.save_personnel(
        Personnel(None, project_id, "NV01", "Nguyễn Văn A", "Nhân sự", True)
    )
    db.set_personnel_pin(personnel_id, "123456")

    assert db.verify_personnel_pin("PROJECT_ALPHA", "NV01", "123456") is not None
    for _ in range(5):
        assert db.verify_personnel_pin("PROJECT_ALPHA", "NV01", "000000") is None
    with pytest.raises(ValueError, match="PERSONNEL_LOCKED"):
        db.verify_personnel_pin("PROJECT_ALPHA", "NV01", "123456")

    db.set_personnel_pin(personnel_id, "654321")
    assert db.verify_personnel_pin("PROJECT_ALPHA", "NV01", "654321") is not None
