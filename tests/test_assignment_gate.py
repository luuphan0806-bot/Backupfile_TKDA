from datetime import date
from pathlib import Path

from scan_backup_manager.db import Database
from scan_backup_manager.models import Personnel, Project, ProjectTask


def _project_person(db: Database, tmp_path: Path) -> tuple[int, int]:
    pid = db.create_project(
        Project(
            None,
            "DEMO",
            "Demo",
            str(tmp_path / "b"),
            str(tmp_path / "s"),
            str(tmp_path / "c"),
            str(tmp_path / "r"),
        )
    )
    per = db.save_personnel(Personnel(None, pid, "NV001", "Nguyễn Văn A", "Scan"))
    return pid, per


def _task(db: Database, pid: int, per: int, code: str, day: str, *, status: str = "NEW") -> int:
    return db.save_task(
        ProjectTask(
            None,
            pid,
            code,
            f"Scan {code}",
            "",
            per,
            "",
            "NORMAL",
            status,
            record_key=f"HS/{code}",
            task_kind="SCAN",
            work_date=day,
        )
    )


def test_list_open_tasks_only_returns_open(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    pid, per = _project_person(db, tmp_path)
    day = date.today().isoformat()
    _task(db, pid, per, "T1", day, status="NEW")
    _task(db, pid, per, "T2", day, status="IN_PROGRESS")
    _task(db, pid, per, "T3", day, status="COMPLETED")

    open_tasks = db.list_open_tasks_for_assignee(pid, per)
    codes = {t["task_code"] for t in open_tasks}
    assert codes == {"T1", "T2"}
    assert all(t["record_key"].startswith("HS/") for t in open_tasks)


def test_complete_task_closes_and_reports_record(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    pid, per = _project_person(db, tmp_path)
    day = date.today().isoformat()
    task_id = _task(db, pid, per, "T1", day, status="NEW")

    result = db.complete_task(pid, task_id)
    assert result["record_key"] == "HS/T1"
    assert result["kind"] == "SCAN"
    # After completion the person has no open task -> gate is clear.
    assert db.list_open_tasks_for_assignee(pid, per) == []
    # Re-completing an already-closed task is rejected.
    try:
        db.complete_task(pid, task_id)
    except ValueError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError re-completing a closed task")


def test_pending_paper_formats_flags_missing(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    pid, per = _project_person(db, tmp_path)
    day = date.today().isoformat()
    _task(db, pid, per, "T1", day, status="NEW")

    # Mark that the record has an extra A3 sheet still needing a scan pass.
    db.save_record_assignment(
        project_id=pid,
        record_key="HS/T1",
        personnel_id=per,
        work_date=date.today().strftime("%d/%m/%Y"),
        assignment_kind="scan",
        paper_presence={"A3": True},
    )
    pending = db.record_pending_paper_formats(pid, "HS/T1")
    codes = {item["code"]: item["done"] for item in pending}
    # A3 was marked present but has no scan data yet -> "còn khổ chưa làm".
    assert "A3" in codes
    assert codes["A3"] is False
