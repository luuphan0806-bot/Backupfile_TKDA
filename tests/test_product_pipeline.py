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


def test_v5_to_v6_migration_reverts_force_completed_records(tmp_path: Path) -> None:
    db, project_id, _source = configured_db(tmp_path)
    scanner_id = db.save_personnel(
        Personnel(None, project_id, "NV01", "Nguyễn Văn A", "Scanner", True)
    )
    checker_id = db.save_personnel(
        Personnel(None, project_id, "NV02", "Nguyễn Văn B", "Checker", True)
    )
    formats = {item.code: item for item in db.list_paper_formats(project_id)}

    def scanned(code: str, pages: int) -> dict:
        return {
            "paper_format_id": formats[code].id,
            "scanner_id": scanner_id,
            "scan_date": "2026-07-01",
            "scan_status": "SCANNED",
            "scan_pages": pages,
            "scan_files": 1,
            "check_pages": 0,
            "notes": "",
        }

    def pending(code: str) -> dict:
        return {
            "paper_format_id": formats[code].id,
            "scanner_id": None,
            "scan_date": "",
            "scan_status": "PENDING_SCAN",
            "scan_pages": 0,
            "scan_files": 0,
            "check_pages": 0,
            "notes": "",
        }

    common = dict(project_id=project_id, checker_id=None, check_date="",
                  check_pages=0, check_files=0, record_status="COMPLETED", notes="")
    # Force-completed, all required papers scanned -> should surface as PENDING_CHECK.
    db.save_record_workflow(
        record_key="2026/HS/A", scanner_id=scanner_id, scan_date="2026-07-01",
        paper_statuses=[scanned("A4", 10)], **common,
    )
    # Force-completed but an A3 is still pending -> PENDING_PAPER.
    db.save_record_workflow(
        record_key="2026/HS/B", scanner_id=scanner_id, scan_date="2026-07-01",
        paper_statuses=[scanned("A4", 5), pending("A3")], **common,
    )
    # Force-completed without any scan data -> back to SCANNING.
    db.save_record_workflow(
        record_key="2026/HS/C", scanner_id=scanner_id, scan_date="",
        paper_statuses=[], **common,
    )
    # Genuinely checked record -> stays COMPLETED.
    db.save_record_workflow(
        project_id=project_id, record_key="2026/HS/D", scanner_id=scanner_id,
        scan_date="2026-07-01", checker_id=checker_id, check_date="2026-07-02",
        check_pages=10, check_files=1, record_status="COMPLETED", notes="",
        paper_statuses=[scanned("A4", 10)],
    )
    db_path = db.db_path
    with sqlite3.connect(db_path) as conn:
        # Legacy task: record key only lives in the description text.
        conn.execute(
            """
            INSERT INTO project_tasks(
                project_id, task_code, title, description, assignee_id, due_date,
                priority, status, record_key, task_kind, created_at, updated_at
            ) VALUES(?, 'LEGACY_TASK', 'Scan A4', 'Thư mục hồ sơ: 2026/HS/A', ?, '',
                'NORMAL', 'NEW', '', '', '2026-07-01', '2026-07-01')
            """,
            (project_id, scanner_id),
        )
        conn.execute("UPDATE app_meta SET value='5' WHERE key='schema_version'")

    migrated = Database(db_path)

    statuses = {
        key: migrated.get_record_workflow(project_id, key)["record_status"]
        for key in ("2026/HS/A", "2026/HS/B", "2026/HS/C", "2026/HS/D")
    }
    assert statuses == {
        "2026/HS/A": "PENDING_CHECK",
        "2026/HS/B": "PENDING_PAPER",
        "2026/HS/C": "SCANNING",
        "2026/HS/D": "COMPLETED",
    }
    legacy_task = next(
        row for row in migrated.list_tasks(project_id) if row["task_code"] == "LEGACY_TASK"
    )
    assert legacy_task["record_key"] == "2026/HS/A"
    assert legacy_task["task_kind"] == "SCAN"


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
