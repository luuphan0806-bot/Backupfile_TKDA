from datetime import datetime
from pathlib import Path

from scan_backup_manager.db import Database
import pytest

from scan_backup_manager.mapfile import MapfileService
from scan_backup_manager.models import Client, PaperFormat, Personnel, Project


def _create_project(db: Database, tmp_path: Path) -> int:
    return db.create_project(
        Project(
            None,
            "PROJECT_ALPHA",
            "Project Alpha",
            str(tmp_path / "backup"),
            str(tmp_path / "staging"),
            str(tmp_path / "conflicts"),
            str(tmp_path / "reports"),
        )
    )


def _add_file(
    db: Database,
    project_id: int,
    *,
    client: str,
    name: str,
    status: str,
    hash_sha256: str,
) -> None:
    record_code = name.rsplit(".", 1)[0]
    db.upsert_backup_file(
        project_id=project_id,
        client_code=client,
        source_path=rf"\\{client}\share\PROJECT_ALPHA\2026\HS\{record_code}\{name}",
        project_code="PROJECT_ALPHA",
        relative_project_path=f"2026/HS/{record_code}/{name}",
        dest_path=rf"D:\backup\PROJECT_ALPHA\2026\HS\{record_code}\{name}",
        file_size=1024,
        source_mtime="2026-07-06T08:00:00+00:00",
        status=status,
        hash_sha256=hash_sha256,
    )


def test_system_mapfile_page_supports_pagination_and_search(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    _add_file(
        db,
        project_id,
        client="SCAN01",
        name="alpha.pdf",
        status="LOCKED",
        hash_sha256="a" * 64,
    )
    _add_file(
        db,
        project_id,
        client="SCAN02",
        name="beta.pdf",
        status="ERROR",
        hash_sha256="b" * 64,
    )

    first_page, total = db.list_backup_files_page(project_id, limit=1)
    assert total == 2
    assert len(first_page) == 1

    rows, total = db.list_backup_files_page(project_id, search="alpha.pdf")
    assert total == 1
    assert rows[0]["client_code"] == "SCAN01"

    rows, total = db.list_backup_files_page(project_id, search="b" * 16)
    assert total == 1
    assert rows[0]["status"] == "ERROR"

    rows, total = db.list_backup_files_page(project_id, status="LOCKED")
    assert total == 1
    assert rows[0]["relative_project_path"].endswith("alpha.pdf")


def test_record_workflow_tracks_paper_sizes_and_requires_a3_confirmation(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    _add_file(
        db,
        project_id,
        client="SCAN01",
        name="alpha.pdf",
        status="LOCKED",
        hash_sha256="a" * 64,
    )
    scanner_id = db.save_personnel(
        Personnel(None, project_id, "NV01", "Người Scan", "Scanner")
    )
    checker_id = db.save_personnel(
        Personnel(None, project_id, "NV02", "Người Check", "Checker")
    )
    formats = {item.code: item for item in db.list_paper_formats(project_id)}
    assert set(formats) == {"A4", "A3", "A0"}

    paper_statuses = [
        {
            "paper_format_id": formats["A4"].id,
            "scanner_id": scanner_id,
            "scan_date": "2026-07-06",
            "scan_status": "SCANNED",
            "scan_pages": 12,
            "scan_files": 3,
            "check_pages": 0,
            "notes": "",
        },
        {
            "paper_format_id": formats["A3"].id,
            "scanner_id": None,
            "scan_date": "",
            "scan_status": "UNKNOWN",
            "scan_pages": 0,
            "check_pages": 0,
            "notes": "",
        },
        {
            "paper_format_id": formats["A0"].id,
            "scanner_id": None,
            "scan_date": "",
            "scan_status": "UNKNOWN",
            "scan_pages": 0,
            "check_pages": 0,
            "notes": "",
        },
    ]
    db.save_record_workflow(
        project_id=project_id,
        record_key="2026/HS/alpha",
        scanner_id=scanner_id,
        scan_date="2026-07-06",
        checker_id=checker_id,
        check_date="2026-07-07",
        check_pages=12,
        record_status="COMPLETED",
        notes="Đã đối chiếu",
        paper_statuses=paper_statuses,
    )

    records, total = db.list_system_records_page(project_id)
    assert total == 1
    assert records[0]["scanner_name"] == "Người Scan"
    assert records[0]["checker_name"] == "Người Check"
    assert records[0]["check_pages"] == 12
    assert records[0]["backup_status"] == "BACKED_UP"
    assert records[0]["paper_statuses"]["A4"]["scan_pages"] == 12
    assert records[0]["paper_statuses"]["A4"]["scan_files"] == 3
    assert records[0]["paper_statuses"]["A4"]["scanner_id"] == scanner_id
    assert records[0]["paper_statuses"]["A3"]["scan_status"] == "UNKNOWN"
    assert records[0]["paper_statuses"]["A0"]["scan_status"] == "UNKNOWN"


def test_system_mapfile_includes_imported_record_before_backup(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    profile = db.get_mapfile_profile(project_id)
    import_id = db.create_mapfile_import(
        project_id, profile.id or 0, str(tmp_path / "mapfile.xlsx")
    )
    db.add_mapfile_rows(
        import_id,
        [
            (
                2,
                {"project": "PROJECT_ALPHA", "case_number": "001"},
                "PROJECT_ALPHA/2026/HS/001/1.pdf",
            )
        ],
    )

    records, total = db.list_system_records_page(project_id)

    assert total == 1
    assert records[0]["record_key"] == "2026/HS/001"
    assert records[0]["backup_status"] == "NOT_BACKED_UP"
    assert records[0]["sample_dest_path"] is None


def test_system_mapfile_can_add_manual_record(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)

    row_id = MapfileService(db).add_manual_record(
        project_id,
        ["2026", "HS", "002"],
    )
    row = db.get_mapfile_row(row_id)
    records, total = db.list_system_records_page(project_id)

    assert row["expected_relative_path"] == str(
        Path("PROJECT_ALPHA") / "2026" / "HS" / "002"
    )
    assert row["record_key"] == "2026/HS/002"
    assert total == 1
    assert records[0]["record_key"] == "2026/HS/002"
    assert records[0]["backup_status"] == "NOT_BACKED_UP"


def test_manual_record_can_create_client_folder(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    share = tmp_path / "share"
    db.save_client(
        Client(None, project_id, "SCAN01", "", str(share), True)
    )

    MapfileService(db).add_manual_record(
        project_id,
        ["2026", "HS", "010"],
        client_code="SCAN01",
    )

    assert (
        share
        / "CSDL_SOHOA_PROJECT_ALPHA"
        / "Họ tên"
        / datetime.now().strftime("%d-%m-%Y")
        / "Nội dung công việc"
        / "2026"
        / "HS"
        / "010"
    ).is_dir()


def test_assignment_keeps_completion_dates_empty_until_work_finishes(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    personnel_id = db.save_personnel(
        Personnel(None, project_id, "NV01", "Người Scan", "Scanner")
    )

    db.save_record_assignment(
        project_id=project_id,
        record_key="2026/HS/010",
        personnel_id=personnel_id,
        work_date="09/07/2026",
        assignment_kind="scan",
    )

    workflow = db.get_record_workflow(project_id, "2026/HS/010")
    assert workflow["scanner_id"] == personnel_id
    assert workflow["scan_date"] == ""
    assert all(paper["scan_date"] == "" for paper in workflow["paper_statuses"])


def test_project_can_enable_subset_of_paper_formats(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    formats = {item.code: item for item in db.list_paper_formats(project_id)}

    db.save_paper_format(
        PaperFormat(
            formats["A0"].id,
            project_id,
            "A0",
            formats["A0"].display_name,
            formats["A0"].requires_separate_scan,
            formats["A0"].requires_check,
            False,
            formats["A0"].sort_order,
        )
    )

    enabled_codes = [item.code for item in db.list_paper_formats(project_id, enabled_only=True)]
    assert enabled_codes == ["A4", "A3"]


def test_system_mapfile_can_duplicate_manual_record_with_next_number(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    service = MapfileService(db)
    service.add_manual_record(project_id, ["2026", "HS", "002"])

    new_key = service.duplicate_manual_record(project_id, "2026/HS/002")
    records, total = db.list_system_records_page(project_id)

    assert new_key == "2026/HS/003"
    assert total == 2
    assert [record["record_key"] for record in records] == [
        "2026/HS/002",
        "2026/HS/003",
    ]
