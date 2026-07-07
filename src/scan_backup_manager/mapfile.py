from __future__ import annotations

import json
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

    def update_row_cell(
        self,
        project_id: int,
        row_id: int,
        column_name: str,
        value: Any,
    ) -> str:
        row = self.db.get_mapfile_row(row_id)
        if not row:
            raise ValueError(f"Mapfile row not found: {row_id}")
        raw = dict(json.loads(row["raw_json"]))
        raw[column_name] = normalize_cell(value)

        profile = self.db.get_mapfile_profile(project_id)
        expected = normalize_expected_path(
            raw.get(profile.project_column, ""),
            raw.get(profile.year_column, ""),
            raw.get(profile.case_type_column, ""),
            raw.get(profile.case_number_column, ""),
            raw.get(profile.file_name_column, ""),
        )
        self.db.update_mapfile_row_source(row_id, raw, expected)
        status = self.reconcile_row(project_id, row_id)
        self.db.record_audit(
            "MAPFILE_ROW_UPDATED",
            f"Updated mapfile row {row_id} column {column_name}",
            project_id=project_id,
        )
        return status

    def add_manual_record(
        self,
        project_id: int,
        record_parts: list[str],
        *,
        file_name: str = "1.pdf",
    ) -> int:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        clean_parts = [str(part).strip() for part in record_parts]
        if not clean_parts or any(not part for part in clean_parts):
            raise ValueError("Cần nhập đầy đủ thông tin hồ sơ.")

        profile = self.db.get_mapfile_profile(project_id)
        directory_levels = self.db.list_directory_levels(project_id)
        raw: dict[str, Any] = {
            profile.project_column: project.project_code,
            profile.file_name_column: normalize_cell(file_name or "1.pdf"),
        }
        if clean_parts:
            raw[profile.year_column] = clean_parts[0]
        if len(clean_parts) > 1:
            raw[profile.case_type_column] = clean_parts[1]
        if len(clean_parts) > 2:
            raw[profile.case_number_column] = "/".join(clean_parts[2:])
        for index, value in enumerate(clean_parts):
            if index < len(directory_levels):
                raw[directory_levels[index].display_name] = value

        expected = str(
            Path(project.project_code.strip()) / Path(*clean_parts) / raw[profile.file_name_column]
        )
        import_id = self.db.latest_mapfile_import_id(project_id)
        if import_id is None:
            import_id = self.db.create_mapfile_import(
                project_id,
                profile.id or 0,
                "manual://system-mapfile",
            )
        row_id = self.db.append_mapfile_row(import_id, raw, expected)
        self.reconcile_row(project_id, row_id)
        self.db.record_audit(
            "MAPFILE_ROW_ADDED",
            f"Added manual mapfile row {row_id}",
            project_id=project_id,
        )
        return row_id

    def duplicate_manual_record(self, project_id: int, source_record_key: str) -> str:
        source_parts = [
            part for part in source_record_key.replace("\\", "/").strip("/").split("/") if part
        ]
        if not source_parts:
            raise ValueError("Không xác định được hồ sơ cần sao chép.")
        existing_keys = {
            record["record_key"]
            for record, _index in self._iter_system_records(project_id)
        }
        new_parts = self._next_record_parts(source_parts, existing_keys)
        self.add_manual_record(project_id, new_parts)
        new_record_key = "/".join(new_parts)

        workflow = self.db.get_record_workflow(project_id, source_record_key)
        if workflow.get("id") is not None:
            self.db.save_record_workflow(
                project_id=project_id,
                record_key=new_record_key,
                scanner_id=workflow.get("scanner_id"),
                scan_date=workflow.get("scan_date", ""),
                checker_id=workflow.get("checker_id"),
                check_date=workflow.get("check_date", ""),
                record_status=workflow.get("record_status", "NOT_STARTED"),
                notes=workflow.get("notes", ""),
                paper_statuses=[
                    {
                        "paper_format_id": paper["paper_format_id"],
                        "scan_status": paper["scan_status"],
                        "scan_pages": str(paper["scan_pages"]),
                        "check_pages": str(paper["check_pages"]),
                        "notes": paper["notes"],
                    }
                    for paper in workflow["paper_statuses"]
                ],
            )
        return new_record_key

    def _iter_system_records(self, project_id: int):
        offset = 0
        limit = 500
        while True:
            records, total = self.db.list_system_records_page(
                project_id, limit=limit, offset=offset
            )
            for index, record in enumerate(records, start=offset):
                yield record, index
            offset += len(records)
            if offset >= total or not records:
                break

    @staticmethod
    def _next_record_parts(source_parts: list[str], existing_keys: set[str]) -> list[str]:
        prefix = source_parts[:-1]
        last = source_parts[-1]
        if last.isdigit():
            width = len(last)
            number = int(last)
            while True:
                number += 1
                candidate = [*prefix, str(number).zfill(width)]
                if "/".join(candidate) not in existing_keys:
                    return candidate
        suffix = 1
        while True:
            candidate_last = f"{last}-copy" if suffix == 1 else f"{last}-copy-{suffix}"
            candidate = [*prefix, candidate_last]
            if "/".join(candidate) not in existing_keys:
                return candidate
            suffix += 1
