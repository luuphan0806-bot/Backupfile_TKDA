from pathlib import Path

from openpyxl import load_workbook

from scan_backup_manager.db import Database
from scan_backup_manager.models import Personnel, Project, ProjectTask
from scan_backup_manager.reports import ReportService
from scan_backup_manager.statistics import StatisticsService


def test_job_quantity_by_day_groups_by_date_and_job(tmp_path: Path) -> None:
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
    person_id = db.save_personnel(
        Personnel(None, project_id, "NV01", "Nguyen Van A", "Scanner")
    )
    db.save_task(
        ProjectTask(
            None,
            project_id,
            "SCAN_A4_001",
            "Scan A4",
            "Record 001",
            person_id,
            "",
            record_key="2025/BAN_VE/001",
            task_kind="SCAN",
        )
    )
    db.save_task(
        ProjectTask(
            None,
            project_id,
            "SCAN_A3_001",
            "Scan A3",
            "Record 001",
            person_id,
            "",
            record_key="2025/BAN_VE/001-A3",
            task_kind="SCAN",
        )
    )
    db.save_task(
        ProjectTask(
            None,
            project_id,
            "CHECK_001",
            "Check Scan",
            "Record 001",
            person_id,
            "",
            status="COMPLETED",
            record_key="2025/BAN_VE/001",
            task_kind="CHECK",
        )
    )

    rows = StatisticsService(db).job_quantity_by_day(
        project_id, "2000-01-01", "2999-12-31"
    )

    by_job = {(row.task_kind, row.job_title): row for row in rows}
    assert by_job[("SCAN", "Scan A4")].quantity == 1
    assert by_job[("SCAN", "Scan A3")].quantity == 1
    assert by_job[("CHECK", "Check Scan")].quantity == 1
    assert by_job[("CHECK", "Check Scan")].completed_count == 1

    details = StatisticsService(db).personnel_daily_job_details(
        project_id, "2000-01-01", "2999-12-31"
    )
    assert [row.sequence_number for row in details] == [1, 2, 3]
    assert [(row.job_title, row.quantity) for row in details] == [
        ("Scan A4", 1),
        ("Scan A3", 1),
        ("Check Scan", 1),
    ]
    assert all(row.started_at for row in details)

    output = ReportService(db).export_attendance_report(
        project_id, "2000-01-01", "2999-12-31", tmp_path / "reports"
    )
    workbook = load_workbook(output)
    assert workbook.sheetnames == ["Cham cong", "Tong hop"]
    attendance = workbook["Cham cong"]
    rows = list(attendance.iter_rows(values_only=True))
    assert rows[0][:5] == (
        "day",
        "personnel_code",
        "full_name",
        "sequence_number",
        "job_title",
    )
    assert len(rows) == 4
    assert {row[4] for row in rows[1:]} == {"Scan A4", "Scan A3", "Check Scan"}
