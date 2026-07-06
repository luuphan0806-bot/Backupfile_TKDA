from __future__ import annotations

import stat
from pathlib import Path

import pytest

from scan_backup_manager.backup import BackupManager
from scan_backup_manager.constants import STATUS_CONFLICT, STATUS_HASH_PENDING
from scan_backup_manager.db import Database
from scan_backup_manager.models import Client, DirectoryLevel, Project, ProjectSettings


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


def test_copy_new_pdf_to_backup_tree(tmp_path: Path) -> None:
    db, project_id = make_db(tmp_path)
    source = make_source_file(tmp_path)
    db.save_client(Client(None, project_id, "SCAN01", "Staff", str(tmp_path / "share"), True))

    result = BackupManager(db).run_all_enabled(project_id)

    dest = tmp_path / "backup" / "CSDL_SOHOA_A" / "2023" / "HS" / "123" / "1.pdf"
    assert result["processed"] == 1
    assert dest.read_bytes() == source.read_bytes()
    assert db.list_backup_files(project_id)[0]["status"] == STATUS_HASH_PENDING


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
