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

    db.delete_project(project_id)

    assert db.get_project(project_id) is None
    assert not project_db.exists()
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM project_tasks").fetchone()[0] == 0
