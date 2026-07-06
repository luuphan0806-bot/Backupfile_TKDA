from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .db import Database
from .models import MapfileProfile


def normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_expected_path(
    project: str,
    year: str,
    case_type: str,
    case_number: str,
    file_name: str,
) -> str:
    file_name = file_name if file_name.lower().endswith(".pdf") else f"{file_name}.pdf"
    return str(Path(project.strip()) / year.strip() / case_type.strip().upper() / case_number.strip() / file_name.strip())


class MapfileService:
    def __init__(self, db: Database):
        self.db = db

    def import_excel(
        self, project_id: int, file_path: Path, profile: MapfileProfile | None = None
    ) -> int:
        profile = profile or self.db.get_mapfile_profile(project_id)
        workbook = load_workbook(file_path, read_only=True, data_only=True)
        worksheet = workbook[profile.sheet_name] if profile.sheet_name else workbook.active
        header_row = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True))
        headers = {normalize_cell(value): index for index, value in enumerate(header_row)}
        required = [
            profile.project_column,
            profile.year_column,
            profile.case_type_column,
            profile.case_number_column,
            profile.file_name_column,
        ]
        missing = [column for column in required if column not in headers]
        if missing:
            raise ValueError(f"Missing mapfile columns: {', '.join(missing)}")

        # Carry over the "Done" flag for rows that match a previous import of the
        # same project, so re-importing an updated mapfile doesn't force personnel
        # to re-tick rows they already marked as scanned.
        previous_import_id = self.db.latest_mapfile_import_id(project_id)
        done_by_path: dict[str, tuple[bool, str, int | None]] = {}
        if previous_import_id:
            for previous_row in self.db.list_mapfile_rows(previous_import_id):
                if previous_row["is_done"]:
                    done_by_path[previous_row["expected_relative_path"]] = (
                        True, previous_row["done_at"], previous_row["done_by"],
                    )

        import_id = self.db.create_mapfile_import(project_id, profile.id or 0, str(file_path))
        rows: list[tuple[int, dict[str, Any], str]] = []
        for row_number, values in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
            raw = {header: normalize_cell(values[index]) for header, index in headers.items() if header}
            if not any(raw.values()):
                continue
            expected = normalize_expected_path(
                raw.get(profile.project_column, ""),
                raw.get(profile.year_column, ""),
                raw.get(profile.case_type_column, ""),
                raw.get(profile.case_number_column, ""),
                raw.get(profile.file_name_column, ""),
            )
            rows.append((row_number, raw, expected))
        self.db.add_mapfile_rows(import_id, rows)

        if done_by_path:
            for new_row in self.db.list_mapfile_rows(import_id):
                carried = done_by_path.get(new_row["expected_relative_path"])
                if carried:
                    _, done_at, done_by = carried
                    self.db.mark_mapfile_row_done(new_row["id"], done_by, done_at=done_at)

        self.reconcile(project_id, import_id)
        self.db.record_audit(
            "MAPFILE_IMPORTED", f"Imported {len(rows)} rows from {file_path}", project_id=project_id
        )
        return import_id

    def reconcile(self, project_id: int, import_id: int | None = None) -> dict[str, int]:
        import_id = import_id or self.db.latest_mapfile_import_id(project_id)
        if import_id is None:
            return {"matched": 0, "missing": 0, "extra": 0}

        backup_rows = self.db.list_backup_files(project_id, limit=None)
        backed_up = {
            str(Path(row["project_code"]) / row["relative_project_path"]): row
            for row in backup_rows
            if row["status"] in {"HASH_PENDING", "VERIFIED_HASH", "LOCKED", "ALREADY_EXISTS"}
        }

        matched = 0
        missing = 0
        for row in self.db.list_mapfile_rows(import_id):
            expected = row["expected_relative_path"]
            if expected in backed_up:
                self.db.update_mapfile_row_status(row["id"], "MATCHED", "Found in backup log")
                matched += 1
            else:
                self.db.update_mapfile_row_status(row["id"], "MISSING", "Not found in backup log")
                missing += 1

        expected_paths = {row["expected_relative_path"] for row in self.db.list_mapfile_rows(import_id)}
        extra = sum(1 for path in backed_up if path not in expected_paths)
        return {"matched": matched, "missing": missing, "extra": extra}

    def reconcile_row(self, project_id: int, row_id: int) -> str:
        """Re-check a single mapfile row against backup_files, without re-running
        reconcile() for the whole import (which can be thousands of rows)."""
        row = self.db.get_mapfile_row(row_id)
        if not row:
            raise ValueError(f"Mapfile row not found: {row_id}")
        matched = self.db.find_backup_file_by_relative_path(project_id, row["expected_relative_path"])
        if matched:
            self.db.update_mapfile_row_status(row_id, "MATCHED", "Found in backup log")
            return "MATCHED"
        self.db.update_mapfile_row_status(row_id, "MISSING", "Not found in backup log")
        return "MISSING"
