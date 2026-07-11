import sqlite3
from contextlib import closing
from pathlib import Path

from scan_backup_manager.db import Database
from scan_backup_manager.models import Personnel, Project, ProjectTask


def test_create_project_creates_project_sqlite_and_delete_removes_project(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = db.create_project(
        Project(
            None,
            "DEMO",
            "Demo",
            str(tmp_path / "backup"),
            str(tmp_path / "staging"),
            str(tmp_path / "conflicts"),
            str(tmp_path / "reports"),
        )
    )
    project_db = db.project_database_path("DEMO")

    assert project_db.exists()
    with closing(sqlite3.connect(project_db)) as conn:
        row = conn.execute(
            "SELECT value FROM project_metadata WHERE key='project_code'"
        ).fetchone()
    assert row == ("DEMO",)

    person_id = db.save_personnel(
        Personnel(None, project_id, "NV01", "Nguyen Van A", "Scanner")
    )
    db.save_task(
        ProjectTask(
            None,
            project_id,
            "SCAN_001",
            "Scan",
            "Record 001",
            person_id,
            "",
            record_key="2025/BAN_VE/001",
            task_kind="SCAN",
        )
    )
    db.sync_project_database(project_id)

    with closing(sqlite3.connect(project_db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM project_tasks").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM attendance_entries").fetchone()[0] == 1
        sync_row = conn.execute(
            "SELECT value FROM project_sync_status WHERE key='last_synced_at'"
        ).fetchone()
    assert sync_row is not None

    db.delete_project(project_id)

    assert db.get_project(project_id) is None
    assert not project_db.exists()
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM project_tasks").fetchone()[0] == 0


def test_import_project_database_restores_portable_project(tmp_path: Path) -> None:
    source_db = Database(tmp_path / "source.sqlite3")
    project_id = source_db.create_project(
        Project(
            None,
            "DEMO",
            "Demo",
            str(tmp_path / "backup"),
            str(tmp_path / "staging"),
            str(tmp_path / "conflicts"),
            str(tmp_path / "reports"),
        )
    )
    person_id = source_db.save_personnel(
        Personnel(None, project_id, "NV01", "Nguyen Van A", "Scanner")
    )
    source_db.save_task(
        ProjectTask(
            None,
            project_id,
            "SCAN_001",
            "Scan",
            "Record 001",
            person_id,
            "",
            status="COMPLETED",
            record_key="2025/BAN_VE/001",
            task_kind="SCAN",
            work_date="2026-07-11",
        )
    )
    portable_db = source_db.sync_project_database(project_id)

    restored_db = Database(tmp_path / "restored.sqlite3")
    restored_project_id = restored_db.import_project_database(portable_db)
    restored_project = restored_db.get_project(restored_project_id)

    assert restored_project is not None
    assert restored_project.project_code == "DEMO"
    assert len(restored_db.list_personnel(restored_project_id)) == 1
    assert len(restored_db.list_tasks(restored_project_id)) == 1
    entries = restored_db.list_attendance_entries(
        restored_project_id, "2026-07-11", "2026-07-11"
    )
    assert len(entries) == 1
    assert entries[0]["personnel_code"] == "NV01"

    with closing(sqlite3.connect(restored_db.project_database_path("DEMO"))) as conn:
        assert conn.execute("SELECT COUNT(*) FROM project_tasks").fetchone()[0] == 1
