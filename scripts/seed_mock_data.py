from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scan_backup_manager.backup import BackupManager
from scan_backup_manager.constants import DEFAULT_DB_PATH
from scan_backup_manager.db import Database
from scan_backup_manager.filesystem import make_writable
from scan_backup_manager.mapfile import MapfileService
from scan_backup_manager.models import (
    Client,
    DirectoryLevel,
    Personnel,
    Project,
    ProjectTask,
)
from scan_backup_manager.reports import ReportService


MOCK_ROOT = ROOT / "data" / "mock_env"
DB_PATH = ROOT / DEFAULT_DB_PATH


def reset_dir(path: Path) -> None:
    if path.exists():
        for current, _dirs, files in os.walk(path):
            for file_name in files:
                make_writable(Path(current) / file_name)
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def backup_existing_db() -> None:
    if not DB_PATH.exists():
        return
    backup_path = DB_PATH.with_suffix(f".sqlite3.bak-{datetime.now():%Y%m%d-%H%M%S}")
    DB_PATH.rename(backup_path)
    print(f"Backed up existing DB: {backup_path}")


def write_pdf(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (
            "%PDF-1.4\n"
            f"% Mock file: {title}\n"
            "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >> endobj\n"
            f"% {body}\n"
            "%%EOF\n"
        ).encode("utf-8")
    )


def create_mock_files() -> dict[str, Path]:
    reset_dir(MOCK_ROOT)
    shares = MOCK_ROOT / "shares"
    backup_root = MOCK_ROOT / "backup"
    conflict_dest = backup_root / "PROJECT_ALPHA" / "2024" / "DOC" / "A-003" / "scan-03.pdf"

    write_pdf(
        shares / "SCAN01_SHARE" / "PROJECT_ALPHA" / "2024" / "DOC" / "A-001" / "scan-01.pdf",
        "PROJECT_ALPHA A-001",
        "Valid file that will be copied and later hash-verified.",
    )
    write_pdf(
        shares / "SCAN01_SHARE" / "PROJECT_ALPHA" / "2024" / "DOC" / "A-002" / "scan-02.pdf",
        "PROJECT_ALPHA A-002",
        "Valid file that remains in HASH_PENDING for dashboard preview.",
    )
    write_pdf(
        shares / "SCAN01_SHARE" / "PROJECT_ALPHA" / "2024" / "DOC" / "A-003" / "scan-03.pdf",
        "PROJECT_ALPHA A-003",
        "Source side for conflict scenario.",
    )
    write_pdf(
        shares / "SCAN01_SHARE" / "PROJECT_ALPHA" / "bad-year" / "DOC" / "A-004" / "scan-04.pdf",
        "Invalid year",
        "This file intentionally breaks the YYYY level validation.",
    )
    write_pdf(
        shares / "SCAN02_SHARE" / "PROJECT_ALPHA" / "2024" / "INVOICE" / "INV-1001" / "invoice-1001.pdf",
        "PROJECT_ALPHA INV-1001",
        "Valid invoice sample.",
    )
    write_pdf(
        shares / "SCAN02_SHARE" / "PROJECT_ALPHA" / "2024" / "UNKNOWN" / "INV-1002" / "invoice-1002.pdf",
        "Invalid category",
        "This file intentionally uses a category code not configured in the app.",
    )
    write_pdf(
        conflict_dest,
        "Existing destination",
        "This existing backup file has different content, so backup must create a conflict.",
    )

    mapfile_path = MOCK_ROOT / "mapfiles" / "mock_mapfile.xlsx"
    mapfile_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Mapfile"
    sheet.append(["project", "year", "case_type", "case_number", "file_name", "owner", "note"])
    sheet.append(["PROJECT_ALPHA", "2024", "DOC", "A-001", "scan-01.pdf", "Team A", "Expected and copied"])
    sheet.append(["PROJECT_ALPHA", "2024", "DOC", "A-002", "scan-02.pdf", "Team A", "Expected and pending hash"])
    sheet.append(["PROJECT_ALPHA", "2024", "DOC", "A-003", "scan-03.pdf", "Team A", "Conflict, not accepted yet"])
    sheet.append(["PROJECT_ALPHA", "2024", "INVOICE", "INV-1001", "invoice-1001.pdf", "Team B", "Expected and copied"])
    sheet.append(["PROJECT_GAMMA", "2024", "CONTRACT", "C-404", "missing-contract.pdf", "Team C", "Expected but missing"])
    workbook.save(mapfile_path)

    write_pdf(
        shares / "SCAN04_SHARE" / "PROJECT_BETA" / "2025" / "HD" / "B-001" / "hop-dong-01.pdf",
        "PROJECT_BETA B-001",
        "Second demo project, used to show the multi-project list.",
    )

    return {
        "scan01": shares / "SCAN01_SHARE",
        "scan02": shares / "SCAN02_SHARE",
        "scan04": shares / "SCAN04_SHARE",
        "backup_root": backup_root,
        "backup_root_beta": MOCK_ROOT / "backup_beta",
        "staging": MOCK_ROOT / "staging",
        "staging_beta": MOCK_ROOT / "staging_beta",
        "conflict_archive": MOCK_ROOT / "conflict_archive",
        "conflict_archive_beta": MOCK_ROOT / "conflict_archive_beta",
        "reports": MOCK_ROOT / "reports",
        "reports_beta": MOCK_ROOT / "reports_beta",
        "mapfile": mapfile_path,
    }


def seed_database(paths: dict[str, Path]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = Database(DB_PATH)
    db.set_setting("language", "vi")
    db.set_setting("default_stability_wait_seconds", "0")

    project_id = db.create_project(
        Project(
            None,
            "PROJECT_ALPHA",
            "Dự án mẫu Alpha",
            str(paths["backup_root"]),
            str(paths["staging"]),
            str(paths["conflict_archive"]),
            str(paths["reports"]),
        )
    )
    db.save_directory_levels(
        project_id,
        [
            DirectoryLevel(None, project_id, 1, "Năm", "YEAR4", []),
            DirectoryLevel(None, project_id, 2, "Loại hồ sơ", "ENUM", ["DOC", "INVOICE", "CONTRACT"]),
            DirectoryLevel(None, project_id, 3, "Mã hồ sơ", "TEXT", []),
        ],
    )

    db.save_client(Client(None, project_id, "SCAN01", "", str(paths["scan01"]), True, "Demo workstation with valid files, conflict, and invalid year"))
    db.save_client(Client(None, project_id, "SCAN02", "", str(paths["scan02"]), True, "Demo workstation with invoice data and invalid category"))
    db.save_client(Client(None, project_id, "SCAN03", "", str(MOCK_ROOT / "shares" / "SCAN03_OFFLINE"), False, "Disabled demo workstation"))
    person_id = db.save_personnel(
        Personnel(None, project_id, "NV001", "Nguyễn Văn A", "Nhân sự scan", True)
    )
    db.save_task(
        ProjectTask(
            None, project_id, "CV001", "Scan hồ sơ đợt 1",
            "Xử lý dữ liệu mẫu", person_id, "2026-12-31", "NORMAL", "NEW",
        )
    )

    manager = BackupManager(db)
    backup_result = manager.run_all_enabled(project_id)
    verified = manager.verify_hash_pending(project_id, limit=1)
    import_id = MapfileService(db).import_excel(project_id, paths["mapfile"])
    # Mark one row as "Done" (scanned, ready for on-demand backup) to have a
    # non-empty starting point for the Mapfile Done -> Backup demo.
    done_row = next(
        row for row in db.list_mapfile_rows(import_id)
        if row["expected_relative_path"] == str(Path("PROJECT_GAMMA") / "2024" / "CONTRACT" / "C-404" / "missing-contract.pdf")
    )
    db.mark_mapfile_row_done(done_row["id"], person_id)
    report_path = ReportService(db).export_daily_report(project_id, paths["reports"])

    # Second, lighter-weight project so "Danh sách dự án" has more than one entry.
    beta_id = db.create_project(
        Project(
            None,
            "PROJECT_BETA",
            "Dự án mẫu Beta",
            str(paths["backup_root_beta"]),
            str(paths["staging_beta"]),
            str(paths["conflict_archive_beta"]),
            str(paths["reports_beta"]),
        )
    )
    db.save_directory_levels(
        beta_id,
        [
            DirectoryLevel(None, beta_id, 1, "Năm", "YEAR4", []),
            DirectoryLevel(None, beta_id, 2, "Loại hồ sơ", "ENUM", ["HD"]),
            DirectoryLevel(None, beta_id, 3, "Mã hồ sơ", "TEXT", []),
        ],
    )
    db.save_client(Client(None, beta_id, "SCAN04", "", str(paths["scan04"]), True, "Demo workstation for Project Beta"))
    beta_result = BackupManager(db).run_all_enabled(beta_id)

    print("Mock data is ready.")
    print(f"Database: {DB_PATH}")
    print(f"Mock root: {MOCK_ROOT}")
    print(f"Mapfile import ID: {import_id}")
    print(f"Backup result (Alpha): {backup_result}")
    print(f"Backup result (Beta): {beta_result}")
    print(f"Hash verified count: {verified}")
    print(f"Report: {report_path}")


def main() -> None:
    backup_existing_db()
    paths = create_mock_files()
    seed_database(paths)
    print("\nOpen the app with:")
    print("python -m scan_backup_manager")


if __name__ == "__main__":
    main()
