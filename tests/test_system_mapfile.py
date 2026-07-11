from datetime import datetime
from pathlib import Path

from pypdf import PdfWriter

from scan_backup_manager.backup import BackupManager
from scan_backup_manager.db import Database
import pytest

from scan_backup_manager.mapfile import MapfileService
from scan_backup_manager.models import (
    Client,
    DirectoryLevel,
    JobType,
    PaperFormat,
    Personnel,
    Project,
    ProjectSettings,
    ProjectTask,
)


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
    dest_path: Path | None = None,
    create_dest: bool = False,
) -> None:
    record_code = name.rsplit(".", 1)[0]
    target = dest_path or Path(rf"D:\backup\PROJECT_ALPHA\2026\HS\{record_code}\{name}")
    if create_dest:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.4\n")
    db.upsert_backup_file(
        project_id=project_id,
        client_code=client,
        source_path=rf"\\{client}\share\PROJECT_ALPHA\2026\HS\{record_code}\{name}",
        project_code="PROJECT_ALPHA",
        relative_project_path=f"2026/HS/{record_code}/{name}",
        dest_path=str(target),
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


def test_system_mapfile_requires_catalog_value_when_configured(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    db.save_directory_levels(
        project_id,
        [
            DirectoryLevel(None, project_id, 1, "Năm", "YEAR4", ["2026"]),
            DirectoryLevel(None, project_id, 2, "Loại hồ sơ", "ENUM", ["HD"], True, 2, True),
            DirectoryLevel(None, project_id, 3, "Mã hồ sơ", "TEXT", []),
        ],
    )
    service = MapfileService(db)

    service.add_manual_record(project_id, ["2026", "HD", "001"])
    with pytest.raises(ValueError, match="phải chọn từ danh mục"):
        service.add_manual_record(project_id, ["2026", "DOC", "002"])


def test_system_mapfile_can_edit_manual_record_key(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    service = MapfileService(db)
    service.add_manual_record(project_id, ["2026", "HS", "002"])
    db.save_record_workflow(
        project_id=project_id,
        record_key="2026/HS/002",
        scanner_id=None,
        scan_date="",
        checker_id=None,
        check_date="",
        check_pages=0,
        check_files=0,
        record_status="SCANNING",
        notes="",
        paper_statuses=[],
    )
    db.upsert_backup_file(
        project_id=project_id,
        client_code="SCAN01",
        source_path=r"\\SCAN01\share\PROJECT_ALPHA\2026\HS\002\1.pdf",
        project_code="PROJECT_ALPHA",
        relative_project_path="2026/HS/002/1.pdf",
        dest_path=str(tmp_path / "backup" / "PROJECT_ALPHA" / "2026" / "HS" / "002" / "1.pdf"),
        file_size=1,
        source_mtime="2026-07-10T00:00:00",
        status="HASH_PENDING",
    )

    new_key = service.update_manual_record(project_id, "2026/HS/002", ["2026", "HS", "003"])

    assert new_key == "2026/HS/003"
    records, total = db.list_system_records_page(project_id)
    assert total == 1
    assert records[0]["record_key"] == "2026/HS/003"
    assert records[0]["record_status"] == "SCANNING"
    assert db.list_backup_files_for_record(project_id, "2026/HS/002") == []
    assert len(db.list_backup_files_for_record(project_id, "2026/HS/003")) == 1


def test_renaming_record_keeps_attendance_entry_in_sync(tmp_path: Path) -> None:
    """Renaming a record must carry its attendance entries along, so the read
    path's lightweight backfill (which no longer re-syncs every task) never
    leaves a stale record_key behind."""
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    service = MapfileService(db)
    service.add_manual_record(project_id, ["2026", "HS", "002"])
    person_id = db.save_personnel(
        Personnel(None, project_id, "NV01", "Nguyen Van A", "Scanner")
    )
    db.save_task(
        ProjectTask(
            None, project_id, "SCAN_S", "Scan A4", "Record", person_id, "",
            status="COMPLETED", record_key="2026/HS/002", task_kind="SCAN",
        )
    )
    before = db.list_attendance_entries(project_id, "2000-01-01", "2999-12-31")
    assert [row["record_key"] for row in before] == ["2026/HS/002"]

    service.update_manual_record(project_id, "2026/HS/002", ["2026", "HS", "003"])

    after = db.list_attendance_entries(project_id, "2000-01-01", "2999-12-31")
    assert [row["record_key"] for row in after] == ["2026/HS/003"]
    # No orphaned entry left under the old key.
    assert all(row["record_key"] != "2026/HS/002" for row in after)


def test_system_mapfile_can_delete_record_and_related_system_data(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    service = MapfileService(db)
    service.add_manual_record(project_id, ["2026", "HS", "002"])
    db.save_record_workflow(
        project_id=project_id,
        record_key="2026/HS/002",
        scanner_id=None,
        scan_date="",
        checker_id=None,
        check_date="",
        check_pages=0,
        check_files=0,
        record_status="SCANNING",
        notes="",
        paper_statuses=[],
    )
    db.upsert_backup_file(
        project_id=project_id,
        client_code="SCAN01",
        source_path=r"\\SCAN01\share\PROJECT_ALPHA\2026\HS\002\1.pdf",
        project_code="PROJECT_ALPHA",
        relative_project_path="2026/HS/002/1.pdf",
        dest_path=str(tmp_path / "backup" / "PROJECT_ALPHA" / "2026" / "HS" / "002" / "1.pdf"),
        file_size=1,
        source_mtime="2026-07-10T00:00:00",
        status="HASH_PENDING",
    )

    deleted = db.delete_system_record(project_id, "2026/HS/002")

    records, total = db.list_system_records_page(project_id)
    assert deleted >= 3
    assert total == 0
    assert records == []
    assert db.list_backup_files_for_record(project_id, "2026/HS/002") == []
    assert db.get_record_workflow(project_id, "2026/HS/002")["id"] is None


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
    assert workflow["record_status"] == "SCANNING"
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


def test_system_mapfile_keeps_new_manual_rows_at_bottom(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    service = MapfileService(db)

    service.add_manual_record(project_id, ["2026", "HS", "999"])
    service.add_manual_record(project_id, ["2026", "HS", "001"])
    records, total = db.list_system_records_page(project_id)

    assert total == 2
    assert [record["record_key"] for record in records] == [
        "2026/HS/999",
        "2026/HS/001",
    ]


def test_check_assignment_lists_pending_check_records(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    service = MapfileService(db)
    scanner_id = db.save_personnel(
        Personnel(None, project_id, "NV01", "Người Scan", "Scanner")
    )
    checker_id = db.save_personnel(
        Personnel(None, project_id, "NV02", "Người Check", "Checker")
    )
    formats = {item.code: item for item in db.list_paper_formats(project_id)}

    service.add_manual_record(project_id, ["2026", "HS", "READY"])
    db.save_record_workflow(
        project_id=project_id,
        record_key="2026/HS/READY",
        scanner_id=scanner_id,
        scan_date="10/07/2026",
        checker_id=None,
        check_date="",
        check_pages=0,
        check_files=0,
        record_status="PENDING_CHECK",
        notes="",
        paper_statuses=[
            {
                "paper_format_id": formats["A4"].id,
                "scanner_id": scanner_id,
                "scan_date": "10/07/2026",
                "scan_status": "SCANNED",
                "scan_pages": 12,
                "scan_files": 1,
                "check_pages": 0,
                "notes": "",
            }
        ],
    )
    _add_file(
        db,
        project_id,
        client="SCAN01",
        name="READY.pdf",
        status="HASH_PENDING",
        hash_sha256="c" * 64,
        dest_path=tmp_path / "backup" / "PROJECT_ALPHA" / "2026" / "HS" / "READY" / "READY.pdf",
        create_dest=True,
    )

    service.add_manual_record(project_id, ["2026", "HS", "MANUAL_DONE"])
    db.save_record_workflow(
        project_id=project_id,
        record_key="2026/HS/MANUAL_DONE",
        scanner_id=scanner_id,
        scan_date="10/07/2026",
        checker_id=None,
        check_date="",
        check_pages=0,
        check_files=0,
        record_status="COMPLETED",
        notes="",
        paper_statuses=[
            {
                "paper_format_id": formats["A4"].id,
                "scanner_id": scanner_id,
                "scan_date": "10/07/2026",
                "scan_status": "SCANNED",
                "scan_pages": 8,
                "scan_files": 1,
                "check_pages": 0,
                "notes": "",
            }
        ],
    )
    _add_file(
        db,
        project_id,
        client="SCAN01",
        name="MANUAL_DONE.pdf",
        status="HASH_PENDING",
        hash_sha256="a" * 64,
        dest_path=tmp_path / "backup" / "PROJECT_ALPHA" / "2026" / "HS" / "MANUAL_DONE" / "MANUAL_DONE.pdf",
        create_dest=True,
    )

    service.add_manual_record(project_id, ["2026", "HS", "CHECKED"])
    db.save_record_workflow(
        project_id=project_id,
        record_key="2026/HS/CHECKED",
        scanner_id=scanner_id,
        scan_date="10/07/2026",
        checker_id=checker_id,
        check_date="10/07/2026",
        check_pages=5,
        check_files=1,
        record_status="COMPLETED",
        notes="",
        paper_statuses=[
            {
                "paper_format_id": formats["A4"].id,
                "scanner_id": scanner_id,
                "scan_date": "10/07/2026",
                "scan_status": "SCANNED",
                "scan_pages": 5,
                "scan_files": 1,
                "check_pages": 0,
                "notes": "",
            }
        ],
    )
    _add_file(
        db,
        project_id,
        client="SCAN01",
        name="CHECKED.pdf",
        status="HASH_PENDING",
        hash_sha256="d" * 64,
    )
    # Still waiting on another paper format — not check-ready yet.
    service.add_manual_record(project_id, ["2026", "HS", "WAITING"])
    db.save_record_workflow(
        project_id=project_id,
        record_key="2026/HS/WAITING",
        scanner_id=scanner_id,
        scan_date="10/07/2026",
        checker_id=None,
        check_date="",
        check_pages=0,
        check_files=0,
        record_status="PENDING_PAPER",
        notes="",
        paper_statuses=[
            {
                "paper_format_id": formats["A4"].id,
                "scanner_id": scanner_id,
                "scan_date": "10/07/2026",
                "scan_status": "SCANNED",
                "scan_pages": 7,
                "scan_files": 1,
                "check_pages": 0,
                "notes": "",
            }
        ],
    )
    _add_file(
        db,
        project_id,
        client="SCAN01",
        name="WAITING.pdf",
        status="HASH_PENDING",
        hash_sha256="e" * 64,
        dest_path=tmp_path / "backup" / "PROJECT_ALPHA" / "2026" / "HS" / "WAITING" / "WAITING.pdf",
        create_dest=True,
    )
    # Pending check but the physical backup file no longer exists on disk.
    service.add_manual_record(project_id, ["2026", "HS", "MISSING"])
    db.save_record_workflow(
        project_id=project_id,
        record_key="2026/HS/MISSING",
        scanner_id=scanner_id,
        scan_date="10/07/2026",
        checker_id=None,
        check_date="",
        check_pages=0,
        check_files=0,
        record_status="PENDING_CHECK",
        notes="",
        paper_statuses=[
            {
                "paper_format_id": formats["A4"].id,
                "scanner_id": scanner_id,
                "scan_date": "10/07/2026",
                "scan_status": "SCANNED",
                "scan_pages": 9,
                "scan_files": 1,
                "check_pages": 0,
                "notes": "",
            }
        ],
    )
    _add_file(
        db,
        project_id,
        client="SCAN01",
        name="MISSING.pdf",
        status="HASH_PENDING",
        hash_sha256="f" * 64,
        dest_path=tmp_path / "backup" / "PROJECT_ALPHA" / "2026" / "HS" / "MISSING" / "MISSING.pdf",
        create_dest=False,
    )
    _add_file(
        db,
        project_id,
        client="SCAN01",
        name="LEGACY.pdf",
        status="HASH_PENDING",
        hash_sha256="b" * 64,
        dest_path=tmp_path / "backup" / "PROJECT_ALPHA" / "2026" / "HS" / "LEGACY" / "LEGACY.pdf",
        create_dest=True,
    )

    ready_records = db.list_check_ready_system_records(project_id)

    assert [record["record_key"] for record in ready_records] == [
        "2026/HS/READY",
        "2026/HS/MANUAL_DONE",
        "2026/HS/LEGACY",
    ]


def test_demo_scan_complete_then_create_check_assignment_for_same_folder(tmp_path: Path) -> None:
    from scan_backup_manager.ui.views.project_console.system_mapfile_tab import (
        check_job_selected,
        check_record_is_selected,
        copy_record_backup_files_for_check,
    )

    db = Database(tmp_path / "app.sqlite3")
    project_id = db.create_project(
        Project(
            None,
            "DEMO",
            "Dự án mẫu Demo",
            str(tmp_path / "backup"),
            str(tmp_path / "staging"),
            str(tmp_path / "conflicts"),
            str(tmp_path / "reports"),
        )
    )
    settings = db.get_project_settings(project_id)
    db.save_project_settings(
        ProjectSettings(project_id, settings.poll_interval_seconds, 0, False)
    )
    db.save_directory_levels(
        project_id,
        [
            DirectoryLevel(None, project_id, 1, "Năm", "YEAR4", ["2025"], True, 1),
            DirectoryLevel(
                None,
                project_id,
                2,
                "Loại hồ sơ",
                "ENUM",
                ["BAN_VE"],
                True,
                2,
                True,
            ),
            DirectoryLevel(None, project_id, 3, "Mã hồ sơ", "TEXT", ["001"], True, 3),
        ],
    )
    scanner_id = db.save_personnel(
        Personnel(None, project_id, "NV001", "Nguyễn Văn A", "Scanner")
    )
    checker_id = db.save_personnel(
        Personnel(None, project_id, "NV002", "Người Check", "Checker")
    )
    db.save_client(
        Client(None, project_id, "1", "", str(tmp_path / "share"), True)
    )
    check_job = JobType(None, project_id, "CHECK", "Check Scan", True, 50, "CHECK")
    db.save_job_type(check_job)

    record_parts = ["2025", "Ban_ve", "001"]
    record_key = "/".join(record_parts)
    source_pdf = (
        tmp_path
        / "share"
        / "DEMO"
        / "2025"
        / "Ban_ve"
        / "001"
        / "H01.01.03.AG.207.01.13.0000006.pdf"
    )
    source_pdf.parent.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source_pdf.open("wb") as handle:
        writer.write(handle)

    MapfileService(db).add_manual_record(project_id, record_parts)
    db.save_record_assignment(
        project_id=project_id,
        record_key=record_key,
        personnel_id=scanner_id,
        work_date="10/07/2026",
        assignment_kind="scan",
        paper_presence={"A3": False},
    )

    BackupManager(db).run_all_enabled(project_id)

    ready_records = db.list_check_ready_system_records(project_id)
    assert [record["record_key"] for record in ready_records] == [record_key]
    assert check_job_selected(check_job, "CHECK")
    assert check_job_selected(check_job, "Check Scan")
    assert check_record_is_selected(record_key, {record_key})

    check_target = MapfileService(db).create_client_record_folder(
        project_id,
        "1",
        record_parts,
        owner_name="Người Check",
        work_date="10-07-2026",
        task_name="Check Scan",
    )
    copied = copy_record_backup_files_for_check(db, project_id, record_key, check_target)
    assignment_id = db.save_check_assignment(
        project_id=project_id,
        record_key=record_key,
        checker_id=checker_id,
        client_code="1",
        folder_path=str(check_target),
    )

    assert copied == 1
    assert (check_target / source_pdf.name).is_file()
    assignments = db.list_check_assignments(project_id, record_key=record_key)
    assert [row["id"] for row in assignments] == [assignment_id]
    assert assignments[0]["folder_path"] == str(check_target)


def test_task_code_long_keys_do_not_collide() -> None:
    from scan_backup_manager.ui.views.project_console.system_mapfile_tab import task_code_for

    shared_prefix = ["2026", "HS", "X" * 90]
    code_a = task_code_for([*shared_prefix, "001"], "SCAN_A4")
    code_b = task_code_for([*shared_prefix, "002"], "SCAN_A4")

    assert code_a != code_b
    assert len(code_a) <= 80 and len(code_b) <= 80
    # Deterministic: the same inputs always upsert the same task row.
    assert code_a == task_code_for([*shared_prefix, "001"], "SCAN_A4")
    assert task_code_for(["2026", "HS", "001"], "SCAN_A4") == "SCAN_A4_2026_HS_001"


def test_complete_open_tasks_returns_kinds_and_leaves_status_alone(tmp_path: Path) -> None:
    from scan_backup_manager.models import ProjectTask

    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    personnel_id = db.save_personnel(
        Personnel(None, project_id, "NV01", "Người Scan", "Scanner")
    )
    db.save_record_assignment(
        project_id=project_id,
        record_key="2026/HS/010",
        personnel_id=personnel_id,
        work_date="10/07/2026",
        assignment_kind="scan",
    )
    db.save_task(
        ProjectTask(
            None, project_id, "SCAN_A4_2026_HS_010", "Scan A4",
            "Thư mục hồ sơ: 2026/HS/010", personnel_id, "",
            record_key="2026/HS/010", task_kind="SCAN",
        )
    )
    # Legacy row: no record_key column value, key only in the description.
    db.save_task(
        ProjectTask(
            None, project_id, "CHECK_2026_HS_011", "Check Scan",
            "Thư mục hồ sơ: 2026/HS/011", personnel_id, "",
        )
    )

    completed = db.complete_open_tasks_for_assignee(project_id, personnel_id)

    by_key = {item["record_key"]: item["kind"] for item in completed}
    assert by_key == {"2026/HS/010": "SCAN", "2026/HS/011": "CHECK"}
    assert all(task["status"] == "COMPLETED" for task in db.list_tasks(project_id))
    # Closing a task must not force the workflow status anymore.
    workflow = db.get_record_workflow(project_id, "2026/HS/010")
    assert workflow["record_status"] == "SCANNING"


def test_scan_assignment_reopens_rescan_required(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    personnel_id = db.save_personnel(
        Personnel(None, project_id, "NV01", "Người Scan", "Scanner")
    )
    db.save_record_workflow(
        project_id=project_id,
        record_key="2026/HS/020",
        scanner_id=None,
        scan_date="",
        checker_id=None,
        check_date="",
        check_pages=0,
        check_files=0,
        record_status="RESCAN_REQUIRED",
        notes="",
        paper_statuses=[],
    )

    db.save_record_assignment(
        project_id=project_id,
        record_key="2026/HS/020",
        personnel_id=personnel_id,
        work_date="10/07/2026",
        assignment_kind="scan",
    )

    workflow = db.get_record_workflow(project_id, "2026/HS/020")
    assert workflow["record_status"] == "SCANNING"


def test_check_assignment_registry_roundtrip(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    checker_id = db.save_personnel(
        Personnel(None, project_id, "NV02", "Người Check", "Checker")
    )
    folder = tmp_path / "share" / "CSDL_SOHOA_PROJECT_ALPHA" / "Người Check" / "10-07-2026" / "Check Scan" / "2026" / "HS" / "030"

    assignment_id = db.save_check_assignment(
        project_id=project_id,
        record_key="2026/HS/030",
        checker_id=checker_id,
        client_code="SCAN01",
        folder_path=str(folder),
    )
    rows = db.list_check_assignments(project_id, record_key="2026/HS/030")
    assert len(rows) == 1
    assert rows[0]["status"] == "ASSIGNED"

    db.mark_check_assignment_recorded(assignment_id)
    rows = db.list_check_assignments(project_id, record_key="2026/HS/030")
    assert rows[0]["status"] == "RECORDED"

    # Re-assigning the same folder resets it to ASSIGNED for a fresh round.
    db.save_check_assignment(
        project_id=project_id,
        record_key="2026/HS/030",
        checker_id=checker_id,
        client_code="SCAN01",
        folder_path=str(folder),
    )
    rows = db.list_check_assignments(project_id, record_key="2026/HS/030")
    assert len(rows) == 1
    assert rows[0]["status"] == "ASSIGNED"


def test_verified_size_counts_as_backed_up_everywhere(tmp_path: Path) -> None:
    from scan_backup_manager.constants import COUNTABLE_BACKUP_STATUSES

    assert "VERIFIED_SIZE" in COUNTABLE_BACKUP_STATUSES

    db = Database(tmp_path / "app.sqlite3")
    project_id = _create_project(db, tmp_path)
    profile = db.get_mapfile_profile(project_id)
    import_id = db.create_mapfile_import(project_id, profile.id or 0, "mapfile.xlsx")
    db.add_mapfile_rows(
        import_id,
        [(2, {"file_name": "1.pdf"}, str(Path("PROJECT_ALPHA") / "2026" / "HS" / "040" / "1.pdf"))],
    )
    db.upsert_backup_file(
        project_id=project_id,
        client_code="SCAN01",
        source_path=r"\\SCAN01\share\PROJECT_ALPHA\2026\HS\040\1.pdf",
        project_code="PROJECT_ALPHA",
        relative_project_path="2026/HS/040/1.pdf",
        dest_path=str(tmp_path / "backup" / "PROJECT_ALPHA" / "2026" / "HS" / "040" / "1.pdf"),
        file_size=1,
        source_mtime="2026-07-10T00:00:00",
        status="VERIFIED_SIZE",
    )

    # The record-level summary and the mapfile reconcile must agree.
    records, _total = db.list_system_records_page(project_id)
    assert records[0]["backup_status"] == "BACKED_UP"
    MapfileService(db).reconcile(project_id, import_id)
    row = db.list_mapfile_rows(import_id)[0]
    assert row["status"] == "MATCHED"
