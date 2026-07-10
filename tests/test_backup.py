from __future__ import annotations

import stat
from datetime import datetime
from pathlib import Path

import pytest
from pypdf import PdfWriter

from scan_backup_manager.backup import BackupManager
from scan_backup_manager.constants import STATUS_CONFLICT, STATUS_HASH_PENDING
from scan_backup_manager.db import Database
from scan_backup_manager.models import Client, DirectoryLevel, Project, ProjectSettings
from scan_backup_manager.pdf_analysis import classify_pdf_page, display_bucket_for_iso_code


POINTS_PER_MM = 72 / 25.4


def make_db(tmp_path: Path) -> tuple[Database, int]:
    db = Database(tmp_path / "app.sqlite3")
    project_id = db.create_project(
        Project(
            None,
            "CSDL_SOHOA_A",
            "Demo",
            str(tmp_path / "backup"),
            str(tmp_path / "staging"),
            str(tmp_path / "conflict_archive"),
            str(tmp_path / "reports"),
        )
    )
    settings = db.get_project_settings(project_id)
    db.save_project_settings(
        ProjectSettings(project_id, settings.poll_interval_seconds, 0, settings.numeric_sequence_check)
    )
    db.save_directory_levels(
        project_id,
        [
            DirectoryLevel(None, project_id, 1, "Year", "YEAR4", []),
            DirectoryLevel(None, project_id, 2, "Category", "ENUM", ["HS"]),
            DirectoryLevel(None, project_id, 3, "Record ID", "TEXT", []),
        ],
    )
    return db, project_id


def make_source_file(tmp_path: Path, content: bytes = b"one") -> Path:
    source = tmp_path / "share" / "CSDL_SOHOA_A" / "2023" / "HS" / "123" / "1.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(content)
    return source


def make_source_pdf(tmp_path: Path, name: str, pages_mm: list[tuple[int, int]]) -> Path:
    source = tmp_path / "share" / "CSDL_SOHOA_A" / "2023" / "HS" / "123" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for width_mm, height_mm in pages_mm:
        writer.add_blank_page(
            width=width_mm * POINTS_PER_MM,
            height=height_mm * POINTS_PER_MM,
        )
    with source.open("wb") as handle:
        writer.write(handle)
    return source


def make_workstation_pdf(
    tmp_path: Path,
    name: str,
    page_points: list[tuple[float, float]],
    task: str = "Scan A4",
    project_root: str = "CSDL_SOHOA_A",
) -> Path:
    source = (
        tmp_path
        / "share"
        / project_root
        / "Nguyen Van A"
        / "09-07-2026"
        / task
        / "2023"
        / "HS"
        / "123"
        / name
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for width, height in page_points:
        writer.add_blank_page(width=width, height=height)
    with source.open("wb") as handle:
        writer.write(handle)
    return source


def test_copy_new_pdf_to_backup_tree(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    source = make_source_file(tmp_path)
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))

    result = BackupManager(db).run_all_enabled(project_id)

    dest = tmp_path / "backup" / "CSDL_SOHOA_A" / "2023" / "HS" / "123" / "1.pdf"
    assert result["processed"] == 1
    assert dest.read_bytes() == source.read_bytes()
    assert db.list_backup_files(project_id)[0]["status"] == STATUS_HASH_PENDING


def test_backup_counts_pdf_pages_by_paper_size(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    make_source_pdf(tmp_path, "1.pdf", [(210, 297), (210, 297), (297, 420), (841, 1189)])
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))

    BackupManager(db).run_all_enabled(project_id)

    records, total = db.list_system_records_page(project_id)
    assert total == 1
    assert records[0]["record_status"] == "PENDING_CHECK"
    statuses = records[0]["paper_statuses"]
    assert statuses["A4"]["scan_pages"] == 2
    assert statuses["A4"]["scan_files"] == 1
    assert statuses["A4"]["scan_date"] == datetime.now().strftime("%Y-%m-%d")
    assert statuses["A3"]["scan_pages"] == 1
    assert statuses["A3"]["scan_files"] == 1
    assert statuses["A3"]["scan_date"] == datetime.now().strftime("%Y-%m-%d")
    assert statuses["A0"]["scan_pages"] == 1
    assert statuses["A0"]["scan_files"] == 1
    assert statuses["A0"]["scan_date"] == datetime.now().strftime("%Y-%m-%d")


def test_backup_recomputes_pdf_counts_without_double_counting(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    make_source_pdf(tmp_path, "1.pdf", [(210, 297)])
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))
    manager = BackupManager(db)

    manager.run_all_enabled(project_id)
    manager.run_all_enabled(project_id)

    records, _total = db.list_system_records_page(project_id)
    assert records[0]["record_status"] == "PENDING_PAPER"
    assert records[0]["paper_statuses"]["A4"]["scan_pages"] == 1
    assert records[0]["paper_statuses"]["A4"]["scan_files"] == 1
    assert records[0]["paper_statuses"]["A3"]["scan_date"] == ""


def test_backup_does_not_overwrite_admin_completed_status(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    make_source_pdf(tmp_path, "1.pdf", [(210, 297)])
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))
    db.save_record_workflow(
        project_id=project_id,
        record_key="2023/HS/123",
        scanner_id=None,
        scan_date="",
        checker_id=None,
        check_date="",
        check_pages=0,
        check_files=0,
        record_status="COMPLETED",
        notes="",
        paper_statuses=[],
    )

    BackupManager(db).run_all_enabled(project_id)

    records, _total = db.list_system_records_page(project_id)
    assert records[0]["record_status"] == "COMPLETED"
    assert records[0]["paper_statuses"]["A4"]["scan_pages"] == 1


def test_backup_record_only_processes_matching_record(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    make_source_pdf(tmp_path, "1.pdf", [(210, 297)])
    other = tmp_path / "share" / "CSDL_SOHOA_A" / "2023" / "HS" / "999" / "1.pdf"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"other")
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))

    result = BackupManager(db).backup_record(project_id, "2023/HS/123")

    assert result["processed"] == 1
    backed_up = db.list_backup_files(project_id, limit=None)
    assert len(backed_up) == 1
    assert backed_up[0]["record_key"] == "2023/HS/123"


def test_practical_iso_216_measurement_counts_cropped_a4_pages(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    project = db.get_project(project_id)
    assert project is not None
    project.project_code = "PROJECT_ALPHA"
    db.save_project(project)
    make_workstation_pdf(
        tmp_path,
        "custom.pdf",
        [(545.76, 906.72), (501.6, 746.88)],
        project_root="CSDL_SOHOA_PROJECT_ALPHA",
    )
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))

    BackupManager(db).backup_record(project_id, "2023/HS/123")

    records, _total = db.list_system_records_page(project_id)
    statuses = records[0]["paper_statuses"]
    assert statuses["A4"]["scan_pages"] == 2
    assert statuses["A4"]["scan_files"] == 1
    assert statuses["A3"]["scan_pages"] == 0


def test_iso_216_smaller_than_a4_counts_as_a4_on_mapfile(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    make_source_pdf(tmp_path, "small.pdf", [(105, 148)])
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))

    BackupManager(db).run_all_enabled(project_id)

    records, _total = db.list_system_records_page(project_id)
    statuses = records[0]["paper_statuses"]
    assert statuses["A4"]["scan_pages"] == 1
    assert statuses["A4"]["scan_files"] == 1
    assert statuses["A3"]["scan_pages"] == 0

    backup_file = db.list_backup_files(project_id, limit=None)[0]
    with db.connect() as conn:
        exact = conn.execute(
            """
            SELECT paper_code, page_count FROM backup_file_paper_sizes
            WHERE backup_file_id=?
            """,
            (backup_file["id"],),
        ).fetchall()
    assert {row["paper_code"]: row["page_count"] for row in exact} == {"A6": 1}


def test_iso_216_page_classifier() -> None:
    assert classify_pdf_page(210 * POINTS_PER_MM, 297 * POINTS_PER_MM) == "A4"
    assert classify_pdf_page(297 * POINTS_PER_MM, 420 * POINTS_PER_MM) == "A3"
    assert classify_pdf_page(841 * POINTS_PER_MM, 1189 * POINTS_PER_MM) == "A0"
    assert classify_pdf_page(545.76, 906.72) == "A4"
    assert classify_pdf_page(105 * POINTS_PER_MM, 148 * POINTS_PER_MM) == "A6"
    assert display_bucket_for_iso_code("A6") == "A4"
    assert display_bucket_for_iso_code("A4") == "A4"
    assert display_bucket_for_iso_code("A3") == "A3"
    assert display_bucket_for_iso_code("A2") == "A0"


def test_existing_different_file_becomes_conflict_without_overwrite(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    source = make_source_file(tmp_path, b"new")
    dest = tmp_path / "backup" / "CSDL_SOHOA_A" / "2023" / "HS" / "123" / "1.pdf"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"old")
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))

    BackupManager(db).run_all_enabled(project_id)

    assert dest.read_bytes() == b"old"
    assert db.list_backup_files(project_id)[0]["status"] == STATUS_CONFLICT
    assert len(db.list_conflicts(project_id)) == 1


def test_replace_conflict_archives_old_file_and_copies_new(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    source = make_source_file(tmp_path, b"new")
    dest = tmp_path / "backup" / "CSDL_SOHOA_A" / "2023" / "HS" / "123" / "1.pdf"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"old")
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))
    manager = BackupManager(db)
    manager.run_all_enabled(project_id)
    conflict_id = db.list_conflicts(project_id)[0]["id"]

    manager.replace_conflict(project_id, conflict_id)

    assert dest.read_bytes() == source.read_bytes()
    assert len(list((tmp_path / "conflict_archive" / "SCAN01").glob("*.pdf"))) == 1
    assert db.list_conflicts(project_id, "RESOLVED")[0]["resolution"] == "REPLACED"


def test_readonly_attribute_is_applied(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    make_source_file(tmp_path)
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))

    BackupManager(db).run_all_enabled(project_id)

    dest = tmp_path / "backup" / "CSDL_SOHOA_A" / "2023" / "HS" / "123" / "1.pdf"
    assert not (dest.stat().st_mode & stat.S_IWRITE)


def test_backup_uses_exact_configured_project_code(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    project = db.get_project(project_id)
    assert project is not None
    project.project_code = "PROJECT_ALPHA"
    db.save_project(project)
    db.save_directory_levels(
        project_id,
        [
            DirectoryLevel(None, project_id, 1, "Year", "YEAR4", []),
            DirectoryLevel(None, project_id, 2, "Category", "ENUM", ["DOC"]),
            DirectoryLevel(None, project_id, 3, "Record ID", "TEXT", []),
        ],
    )
    source = tmp_path / "share" / "PROJECT_ALPHA" / "2024" / "DOC" / "A-001" / "scan.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"generic")
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))

    BackupManager(db).run_all_enabled(project_id)

    dest = tmp_path / "backup" / "PROJECT_ALPHA" / "2024" / "DOC" / "A-001" / "scan.pdf"
    assert dest.read_bytes() == b"generic"


def test_backup_single_mapfile_row_requires_done_flag(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    profile = db.get_mapfile_profile(project_id)
    import_id = db.create_mapfile_import(project_id, profile.id or 0, "mapfile.xlsx")
    expected = str(Path("CSDL_SOHOA_A") / "2023" / "HS" / "123" / "1.pdf")
    db.add_mapfile_rows(import_id, [(2, {"file_name": "1.pdf"}, expected)])
    row = db.list_mapfile_rows(import_id)[0]

    with pytest.raises(ValueError, match="Done"):
        BackupManager(db).backup_single_mapfile_row(project_id, row["id"])


def test_backup_single_mapfile_row_happy_path(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    source = make_source_file(tmp_path)
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))
    profile = db.get_mapfile_profile(project_id)
    import_id = db.create_mapfile_import(project_id, profile.id or 0, "mapfile.xlsx")
    expected = str(Path("CSDL_SOHOA_A") / "2023" / "HS" / "123" / "1.pdf")
    db.add_mapfile_rows(import_id, [(2, {"file_name": "1.pdf"}, expected)])
    row = db.list_mapfile_rows(import_id)[0]
    db.mark_mapfile_row_done(row["id"], None)

    outcome = BackupManager(db).backup_single_mapfile_row(project_id, row["id"])

    dest = tmp_path / "backup" / "CSDL_SOHOA_A" / "2023" / "HS" / "123" / "1.pdf"
    assert outcome.status == STATUS_HASH_PENDING
    assert dest.read_bytes() == source.read_bytes()


def test_backup_single_mapfile_row_missing_file_raises(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))
    profile = db.get_mapfile_profile(project_id)
    import_id = db.create_mapfile_import(project_id, profile.id or 0, "mapfile.xlsx")
    expected = str(Path("CSDL_SOHOA_A") / "2023" / "HS" / "999" / "missing.pdf")
    db.add_mapfile_rows(import_id, [(2, {"file_name": "missing.pdf"}, expected)])
    row = db.list_mapfile_rows(import_id)[0]
    db.mark_mapfile_row_done(row["id"], None)

    with pytest.raises(FileNotFoundError):
        BackupManager(db).backup_single_mapfile_row(project_id, row["id"])


def test_backup_single_mapfile_row_skips_invalid_candidate(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    settings = db.get_project_settings(project_id)
    db.save_project_settings(
        ProjectSettings(
            project_id, settings.poll_interval_seconds, settings.stability_wait_seconds, True
        )
    )
    invalid = tmp_path / "share" / "CSDL_SOHOA_A" / "2023" / "HS" / "123" / "abc.pdf"
    invalid.parent.mkdir(parents=True)
    invalid.write_bytes(b"invalid-name")
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))

    profile = db.get_mapfile_profile(project_id)
    import_id = db.create_mapfile_import(project_id, profile.id or 0, "mapfile.xlsx")
    expected = str(Path("CSDL_SOHOA_A") / "2023" / "HS" / "123" / "abc.pdf")
    db.add_mapfile_rows(import_id, [(2, {"file_name": "abc.pdf"}, expected)])
    row = db.list_mapfile_rows(import_id)[0]
    db.mark_mapfile_row_done(row["id"], None)

    with pytest.raises(FileNotFoundError):
        BackupManager(db).backup_single_mapfile_row(project_id, row["id"])
