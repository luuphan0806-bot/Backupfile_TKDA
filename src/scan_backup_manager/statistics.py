from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .db import Database


@dataclass(slots=True)
class DailyProductivity:
    day: str
    done_count: int
    backed_up_count: int


@dataclass(slots=True)
class PersonnelProductivity:
    personnel_code: str
    full_name: str
    done_count: int


@dataclass(slots=True)
class CompletionRatio:
    total_rows: int
    done_count: int
    matched_count: int
    done_pct: float
    matched_pct: float


@dataclass(slots=True)
class LatencyStats:
    sample_count: int
    average_hours: float | None
    median_hours: float | None
    bucket_under_1h: int
    bucket_1_to_4h: int
    bucket_4_to_24h: int
    bucket_over_24h: int


@dataclass(slots=True)
class PaperSizeSummary:
    paper_code: str
    page_count: int
    file_count: int


@dataclass(slots=True)
class JobQuantityByDay:
    day: str
    job_title: str
    task_kind: str
    quantity: int
    completed_count: int
    personnel_count: int


@dataclass(slots=True)
class PersonnelDailyJobDetail:
    day: str
    personnel_code: str
    full_name: str
    sequence_number: int
    job_title: str
    task_kind: str
    quantity: int
    completed_count: int
    started_at: str
    last_updated_at: str


class StatisticsService:
    """Aggregate queries for the per-project "Thống kê" tab.

    Kept separate from db.py (which stays CRUD/query-only) so the composed
    business metrics (productivity, completion ratio, Done->Backup latency)
    have a dedicated home.
    """

    def __init__(self, db: Database):
        self.db = db

    def productivity_by_day(
        self, project_id: int, date_from: str, date_to: str
    ) -> list[DailyProductivity]:
        with self.db.connect() as conn:
            done_rows = conn.execute(
                """
                SELECT substr(r.done_at, 1, 10) AS day, COUNT(*) AS count
                FROM mapfile_rows r
                JOIN mapfile_imports i ON i.id = r.import_id
                WHERE i.project_id=? AND r.is_done=1
                    AND substr(r.done_at, 1, 10) BETWEEN ? AND ?
                GROUP BY day
                """,
                (project_id, date_from, date_to),
            ).fetchall()
            backup_rows = conn.execute(
                """
                SELECT substr(locked_at, 1, 10) AS day, COUNT(*) AS count
                FROM backup_files
                WHERE project_id=? AND locked_at IS NOT NULL
                    AND substr(locked_at, 1, 10) BETWEEN ? AND ?
                GROUP BY day
                """,
                (project_id, date_from, date_to),
            ).fetchall()
        done_by_day = {row["day"]: row["count"] for row in done_rows}
        backup_by_day = {row["day"]: row["count"] for row in backup_rows}
        days = sorted(set(done_by_day) | set(backup_by_day))
        return [
            DailyProductivity(day, done_by_day.get(day, 0), backup_by_day.get(day, 0))
            for day in days
        ]

    def productivity_by_personnel(
        self, project_id: int, date_from: str, date_to: str
    ) -> list[PersonnelProductivity]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.personnel_code, p.full_name, COUNT(*) AS count
                FROM mapfile_rows r
                JOIN mapfile_imports i ON i.id = r.import_id
                JOIN project_personnel p ON p.id = r.done_by
                WHERE i.project_id=? AND r.is_done=1
                    AND substr(r.done_at, 1, 10) BETWEEN ? AND ?
                GROUP BY p.id
                ORDER BY count DESC
                """,
                (project_id, date_from, date_to),
            ).fetchall()
        return [
            PersonnelProductivity(row["personnel_code"], row["full_name"], row["count"])
            for row in rows
        ]

    def completion_ratio(self, project_id: int) -> CompletionRatio:
        import_id = self.db.latest_mapfile_import_id(project_id)
        if import_id is None:
            return CompletionRatio(0, 0, 0, 0.0, 0.0)
        with self.db.connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS count FROM mapfile_rows WHERE import_id=?", (import_id,)
            ).fetchone()["count"]
            done = conn.execute(
                "SELECT COUNT(*) AS count FROM mapfile_rows WHERE import_id=? AND is_done=1",
                (import_id,),
            ).fetchone()["count"]
            matched = conn.execute(
                "SELECT COUNT(*) AS count FROM mapfile_rows WHERE import_id=? AND status='MATCHED'",
                (import_id,),
            ).fetchone()["count"]
        done_pct = (done / total * 100) if total else 0.0
        matched_pct = (matched / total * 100) if total else 0.0
        return CompletionRatio(total, done, matched, done_pct, matched_pct)

    def done_to_backup_latency(
        self, project_id: int, date_from: str, date_to: str
    ) -> LatencyStats:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.done_at AS done_at, b.locked_at AS locked_at
                FROM mapfile_rows r
                JOIN mapfile_imports i ON i.id = r.import_id
                JOIN backup_files b
                    ON (b.project_code || '/' || b.relative_project_path) = r.expected_relative_path
                    AND b.project_id = i.project_id
                WHERE i.project_id=? AND r.status='MATCHED'
                    AND b.locked_at IS NOT NULL AND r.done_at IS NOT NULL
                    AND substr(r.done_at, 1, 10) BETWEEN ? AND ?
                """,
                (project_id, date_from, date_to),
            ).fetchall()
        hours: list[float] = []
        for row in rows:
            try:
                done_dt = datetime.fromisoformat(row["done_at"])
                locked_dt = datetime.fromisoformat(row["locked_at"])
            except ValueError:
                continue
            delta_hours = (locked_dt - done_dt).total_seconds() / 3600
            if delta_hours >= 0:
                hours.append(delta_hours)
        if not hours:
            return LatencyStats(0, None, None, 0, 0, 0, 0)
        hours.sort()
        count = len(hours)
        average = sum(hours) / count
        middle = count // 2
        median = hours[middle] if count % 2 == 1 else (hours[middle - 1] + hours[middle]) / 2
        buckets = {"<1h": 0, "1-4h": 0, "4-24h": 0, ">24h": 0}
        for value in hours:
            if value < 1:
                buckets["<1h"] += 1
            elif value < 4:
                buckets["1-4h"] += 1
            elif value < 24:
                buckets["4-24h"] += 1
            else:
                buckets[">24h"] += 1
        return LatencyStats(
            count, average, median,
            buckets["<1h"], buckets["1-4h"], buckets["4-24h"], buckets[">24h"],
        )

    def paper_size_summary(
        self, project_id: int, date_from: str, date_to: str
    ) -> list[PaperSizeSummary]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.paper_code,
                    SUM(s.page_count) AS page_count,
                    COUNT(DISTINCT s.backup_file_id) AS file_count
                FROM backup_file_paper_sizes s
                JOIN backup_files b ON b.id=s.backup_file_id
                WHERE b.project_id=?
                    AND b.status IN ('HASH_PENDING', 'VERIFIED_HASH', 'LOCKED', 'ALREADY_EXISTS')
                    AND substr(COALESCE(b.locked_at, b.verified_at, b.copied_at, b.created_at), 1, 10)
                        BETWEEN ? AND ?
                GROUP BY s.paper_code
                ORDER BY
                    CASE s.paper_code
                        WHEN 'A0' THEN 0
                        WHEN 'A1' THEN 1
                        WHEN 'A2' THEN 2
                        WHEN 'A3' THEN 3
                        WHEN 'A4' THEN 4
                        WHEN 'A5' THEN 5
                        ELSE 99
                    END,
                    s.paper_code
                """,
                (project_id, date_from, date_to),
            ).fetchall()
        return [
            PaperSizeSummary(
                row["paper_code"],
                int(row["page_count"] or 0),
                int(row["file_count"] or 0),
            )
            for row in rows
        ]

    def job_quantity_by_day(
        self, project_id: int, date_from: str, date_to: str
    ) -> list[JobQuantityByDay]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    substr(t.created_at, 1, 10) AS day,
                    t.title AS job_title,
                    COALESCE(NULLIF(t.task_kind, ''), 'SCAN') AS task_kind,
                    COUNT(DISTINCT COALESCE(NULLIF(t.record_key, ''), CAST(t.id AS TEXT))) AS quantity,
                    SUM(CASE WHEN t.status='COMPLETED' THEN 1 ELSE 0 END) AS completed_count,
                    COUNT(DISTINCT t.assignee_id) AS personnel_count
                FROM project_tasks t
                WHERE t.project_id=?
                    AND substr(t.created_at, 1, 10) BETWEEN ? AND ?
                GROUP BY day, t.title, task_kind
                ORDER BY day DESC, task_kind, t.title
                """,
                (project_id, date_from, date_to),
            ).fetchall()
        return [
            JobQuantityByDay(
                row["day"],
                row["job_title"],
                row["task_kind"],
                int(row["quantity"] or 0),
                int(row["completed_count"] or 0),
                int(row["personnel_count"] or 0),
            )
            for row in rows
        ]

    def personnel_daily_job_details(
        self, project_id: int, date_from: str, date_to: str
    ) -> list[PersonnelDailyJobDetail]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    substr(t.created_at, 1, 10) AS day,
                    p.personnel_code,
                    p.full_name,
                    t.title AS job_title,
                    COALESCE(NULLIF(t.task_kind, ''), 'SCAN') AS task_kind,
                    COUNT(DISTINCT COALESCE(NULLIF(t.record_key, ''), CAST(t.id AS TEXT))) AS quantity,
                    SUM(CASE WHEN t.status='COMPLETED' THEN 1 ELSE 0 END) AS completed_count,
                    MIN(t.created_at) AS started_at,
                    MAX(t.updated_at) AS last_updated_at,
                    MIN(t.id) AS first_task_id
                FROM project_tasks t
                JOIN project_personnel p ON p.id=t.assignee_id
                WHERE t.project_id=?
                    AND substr(t.created_at, 1, 10) BETWEEN ? AND ?
                GROUP BY day, p.id, t.title, task_kind
                ORDER BY day DESC, p.full_name, started_at, first_task_id
                """,
                (project_id, date_from, date_to),
            ).fetchall()
        details: list[PersonnelDailyJobDetail] = []
        sequence_by_person_day: dict[tuple[str, str], int] = {}
        for row in rows:
            key = (row["day"], row["personnel_code"])
            sequence_by_person_day[key] = sequence_by_person_day.get(key, 0) + 1
            details.append(
                PersonnelDailyJobDetail(
                    row["day"],
                    row["personnel_code"],
                    row["full_name"],
                    sequence_by_person_day[key],
                    row["job_title"],
                    row["task_kind"],
                    int(row["quantity"] or 0),
                    int(row["completed_count"] or 0),
                    row["started_at"],
                    row["last_updated_at"],
                )
            )
        return details
