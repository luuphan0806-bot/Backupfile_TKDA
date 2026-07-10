from pathlib import Path

from scan_backup_manager.db import Database
from scan_backup_manager.models import Project
from scan_backup_manager.service_core import JOB_SCAN, JOB_VERIFY, BackupJobService


def test_schedule_due_projects_enqueues_daily_verify_once(tmp_path: Path) -> None:
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
    service = BackupJobService(db, instance_id="test")

    service.schedule_due_projects()
    service.schedule_due_projects()

    jobs = db.list_jobs(project_id, limit=10)
    job_types = [row["job_type"] for row in jobs]
    assert job_types.count(JOB_SCAN) == 1
    assert job_types.count(JOB_VERIFY) == 1
    with db.connect() as conn:
        scheduled_types = [
            row["job_type"]
            for row in conn.execute(
                "SELECT job_type FROM backup_jobs WHERE project_id=? ORDER BY id",
                (project_id,),
            )
        ]
    assert scheduled_types == [JOB_SCAN, JOB_VERIFY]
