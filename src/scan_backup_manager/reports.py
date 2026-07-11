from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from .db import Database
from .statistics import StatisticsService


def _write_rows(sheet: Worksheet, headers: list[str], rows: Iterable[dict[str, object]]) -> None:
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")
    for row in rows:
        sheet.append([row.get(header, "") for header in headers])
    for column_cells in sheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 12), 60)


def _kind_label(kind: str) -> str:
    return "Check" if kind == "CHECK" else "Scan"


class ReportService:
    def __init__(self, db: Database):
        self.db = db

    def export_daily_report(self, project_id: int, output_dir: Path | None = None) -> Path:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        output_dir = output_dir or Path(project.reports_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        report_rows = self.db.list_report_rows(project_id)

        summary = workbook.active
        summary.title = "Summary"
        counts = self.db.dashboard_counts(project_id)
        summary.append(["Metric", "Value"])
        for cell in summary[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="D9EAF7")
        for key in sorted(counts):
            summary.append([key, counts[key]])
        summary.append(["project_code", project.project_code])
        summary.append(["project_name", project.display_name])
        summary.column_dimensions["A"].width = 28
        summary.column_dimensions["B"].width = 16

        backups = workbook.create_sheet("Backup Files")
        _write_rows(
            backups,
            [
                "id",
                "client_code",
                "project_code",
                "relative_project_path",
                "dest_path",
                "file_size",
                "status",
                "error_message",
                "created_at",
                "copied_at",
                "verified_at",
            ],
            [dict(row) for row in report_rows["backup_files"]],
        )

        conflicts = workbook.create_sheet("Conflicts")
        _write_rows(
            conflicts,
            [
                "id",
                "client_code",
                "source_path",
                "dest_path",
                "status",
                "resolution",
                "archive_path",
                "created_at",
                "resolved_at",
            ],
            [dict(row) for row in report_rows["conflicts"]],
        )

        mapfile = workbook.create_sheet("Mapfile")
        _write_rows(
            mapfile,
            [
                "id", "import_id", "row_number", "expected_relative_path", "status", "message",
                "is_done", "done_at", "done_by",
            ],
            [dict(row) for row in report_rows["mapfile_rows"]],
        )

        personnel = workbook.create_sheet("Personnel")
        _write_rows(
            personnel,
            ["id", "personnel_code", "full_name", "role_name", "enabled", "created_at", "updated_at"],
            [dict(row) for row in report_rows["personnel"]],
        )

        tasks = workbook.create_sheet("Tasks")
        _write_rows(
            tasks,
            [
                "id", "task_code", "title", "description", "personnel_code",
                "assignee_name", "due_date", "priority", "status", "created_at", "updated_at",
            ],
            [dict(row) for row in report_rows["tasks"]],
        )

        output = output_dir / f"scan_backup_report_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        workbook.save(output)
        self.db.record_audit(
            "REPORT_EXPORTED", f"Exported report to {output}", project_id=project_id
        )
        return output

    def export_statistics_report(
        self, project_id: int, date_from: str, date_to: str, output_dir: Path | None = None
    ) -> Path:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        output_dir = output_dir or Path(project.reports_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        stats = StatisticsService(self.db)
        workbook = Workbook()

        daily = workbook.active
        daily.title = "Daily"
        _write_rows(
            daily,
            ["day", "done_count", "backed_up_count"],
            [
                {"day": row.day, "done_count": row.done_count, "backed_up_count": row.backed_up_count}
                for row in stats.productivity_by_day(project_id, date_from, date_to)
            ],
        )

        personnel = workbook.create_sheet("Personnel")
        _write_rows(
            personnel,
            ["personnel_code", "full_name", "done_count"],
            [
                {
                    "personnel_code": row.personnel_code,
                    "full_name": row.full_name,
                    "done_count": row.done_count,
                }
                for row in stats.productivity_by_personnel(project_id, date_from, date_to)
            ],
        )

        paper_sizes = workbook.create_sheet("Paper Sizes")
        _write_rows(
            paper_sizes,
            ["paper_code", "page_count", "file_count"],
            [
                {
                    "paper_code": row.paper_code,
                    "page_count": row.page_count,
                    "file_count": row.file_count,
                }
                for row in stats.paper_size_summary(project_id, date_from, date_to)
            ],
        )

        ratio = stats.completion_ratio(project_id)
        latency = stats.done_to_backup_latency(project_id, date_from, date_to)
        summary = workbook.create_sheet("Summary")
        summary.append(["Metric", "Value"])
        for cell in summary[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="D9EAF7")
        summary.append(["date_from", date_from])
        summary.append(["date_to", date_to])
        summary.append(["total_rows", ratio.total_rows])
        summary.append(["done_count", ratio.done_count])
        summary.append(["matched_count", ratio.matched_count])
        summary.append(["done_pct", round(ratio.done_pct, 1)])
        summary.append(["matched_pct", round(ratio.matched_pct, 1)])
        summary.append(["latency_sample_count", latency.sample_count])
        summary.append([
            "latency_average_hours",
            round(latency.average_hours, 2) if latency.average_hours is not None else "",
        ])
        summary.append([
            "latency_median_hours",
            round(latency.median_hours, 2) if latency.median_hours is not None else "",
        ])
        summary.append(["latency_bucket_under_1h", latency.bucket_under_1h])
        summary.append(["latency_bucket_1_to_4h", latency.bucket_1_to_4h])
        summary.append(["latency_bucket_4_to_24h", latency.bucket_4_to_24h])
        summary.append(["latency_bucket_over_24h", latency.bucket_over_24h])
        summary.column_dimensions["A"].width = 28
        summary.column_dimensions["B"].width = 16

        output = (
            output_dir
            / f"statistics_report_{date_from}_{date_to}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        )
        workbook.save(output)
        self.db.record_audit(
            "STATISTICS_REPORT_EXPORTED", f"Exported statistics report to {output}",
            project_id=project_id,
        )
        return output

    def export_attendance_report(
        self, project_id: int, date_from: str, date_to: str, output_dir: Path | None = None
    ) -> Path:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        output_dir = output_dir or Path(project.reports_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        stats = StatisticsService(self.db)
        details = stats.personnel_daily_job_details(project_id, date_from, date_to)
        workbook = Workbook()

        sheet = workbook.active
        sheet.title = "Cham cong"
        _write_rows(
            sheet,
            [
                "day",
                "personnel_code",
                "full_name",
                "sequence_number",
                "job_title",
                "task_kind",
                "quantity",
                "completed_count",
                "started_at",
                "last_updated_at",
            ],
            [
                {
                    "day": row.day,
                    "personnel_code": row.personnel_code,
                    "full_name": row.full_name,
                    "sequence_number": row.sequence_number,
                    "job_title": row.job_title,
                    "task_kind": _kind_label(row.task_kind),
                    "quantity": row.quantity,
                    "completed_count": row.completed_count,
                    "started_at": row.started_at,
                    "last_updated_at": row.last_updated_at,
                }
                for row in details
            ],
        )

        summary: dict[tuple[str, str, str], dict[str, object]] = {}
        for row in details:
            key = (row.day, row.personnel_code, row.full_name)
            bucket = summary.setdefault(
                key,
                {
                    "day": row.day,
                    "personnel_code": row.personnel_code,
                    "full_name": row.full_name,
                    "job_count": 0,
                    "total_quantity": 0,
                    "completed_count": 0,
                    "first_started_at": row.started_at,
                },
            )
            bucket["job_count"] = int(bucket["job_count"]) + 1
            bucket["total_quantity"] = int(bucket["total_quantity"]) + row.quantity
            bucket["completed_count"] = int(bucket["completed_count"]) + row.completed_count
            first_started = str(bucket["first_started_at"] or "")
            if row.started_at and (not first_started or row.started_at < first_started):
                bucket["first_started_at"] = row.started_at

        summary_sheet = workbook.create_sheet("Tong hop")
        _write_rows(
            summary_sheet,
            [
                "day",
                "personnel_code",
                "full_name",
                "job_count",
                "total_quantity",
                "completed_count",
                "first_started_at",
            ],
            [
                summary[key]
                for key in sorted(summary, key=lambda item: (item[0], item[2], item[1]))
            ],
        )

        raw_entries = self.db.list_attendance_entries(project_id, date_from, date_to)
        raw_sheet = workbook.create_sheet("San luong tho")
        _write_rows(
            raw_sheet,
            [
                "id",
                "work_date",
                "personnel_code",
                "full_name",
                "record_key",
                "job_title",
                "task_kind",
                "quantity",
                "completed_count",
                "status",
                "task_status",
                "record_status",
                "approved_by",
                "approved_at",
                "override_reason",
                "notes",
            ],
            [
                {
                    "id": row["id"],
                    "work_date": row["work_date"],
                    "personnel_code": row["personnel_code"],
                    "full_name": row["full_name"],
                    "record_key": row["record_key"],
                    "job_title": row["job_title"],
                    "task_kind": _kind_label(row["task_kind"]),
                    "quantity": row["quantity"],
                    "completed_count": row["completed_count"],
                    "status": row["status"],
                    "task_status": row["task_status"] or "",
                    "record_status": row["record_status"],
                    "approved_by": row["approved_by"],
                    "approved_at": row["approved_at"],
                    "override_reason": row["override_reason"],
                    "notes": row["notes"],
                }
                for row in raw_entries
            ],
        )

        exception_sheet = workbook.create_sheet("Ngoai le")
        _write_rows(
            exception_sheet,
            [
                "id",
                "work_date",
                "personnel_code",
                "full_name",
                "record_key",
                "job_title",
                "task_kind",
                "status",
                "task_status",
                "record_status",
                "has_scan_backup",
                "check_pages",
                "check_files",
                "notes",
            ],
            [
                {
                    "id": row["id"],
                    "work_date": row["work_date"],
                    "personnel_code": row["personnel_code"],
                    "full_name": row["full_name"],
                    "record_key": row["record_key"],
                    "job_title": row["job_title"],
                    "task_kind": _kind_label(row["task_kind"]),
                    "status": row["status"],
                    "task_status": row["task_status"] or "",
                    "record_status": row["record_status"],
                    "has_scan_backup": int(row["has_scan_backup"] or 0),
                    "check_pages": row["check_pages"],
                    "check_files": row["check_files"],
                    "notes": row["notes"],
                }
                for row in raw_entries
                if row["status"] != "APPROVED"
                or row["override_reason"]
                or (row["task_kind"] == "SCAN" and not row["has_scan_backup"])
                or (row["task_kind"] == "CHECK" and row["record_status"] != "COMPLETED")
            ],
        )

        with self.db.connect() as conn:
            audit_rows = conn.execute(
                """
                SELECT action, message, created_at FROM audit_logs
                WHERE project_id=?
                    AND action IN (
                        'ATTENDANCE_APPROVED',
                        'ATTENDANCE_REJECTED',
                        'ATTENDANCE_REPORT_EXPORTED'
                    )
                    AND substr(created_at, 1, 10) BETWEEN ? AND ?
                ORDER BY created_at DESC
                """,
                (project_id, date_from, date_to),
            ).fetchall()
        audit_sheet = workbook.create_sheet("Audit chinh sua")
        _write_rows(
            audit_sheet,
            ["created_at", "action", "message"],
            [
                {
                    "created_at": row["created_at"],
                    "action": row["action"],
                    "message": row["message"],
                }
                for row in audit_rows
            ],
        )

        output = (
            output_dir
            / f"attendance_report_{date_from}_{date_to}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        )
        workbook.save(output)
        self.db.record_audit(
            "ATTENDANCE_REPORT_EXPORTED",
            f"Exported attendance report to {output}",
            project_id=project_id,
        )
        return output
