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
