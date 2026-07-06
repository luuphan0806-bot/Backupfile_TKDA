from __future__ import annotations

from pathlib import Path

from scan_backup_manager.filesystem import discover_files, find_project_roots, validate_project_file
from scan_backup_manager.models import DirectoryLevel


def levels(project_id: int = 1, category: str = "HS") -> list[DirectoryLevel]:
    return [
        DirectoryLevel(None, project_id, 1, "Year", "YEAR4", []),
        DirectoryLevel(None, project_id, 2, "Category", "ENUM", [category]),
        DirectoryLevel(None, project_id, 3, "Record ID", "TEXT", []),
    ]


def test_find_project_roots_nested(tmp_path: Path) -> None:
    project = tmp_path / "NGUYENVANA" / "24052026" / "SCAN" / "CSDL_SOHOA_LONGDIEN"
    project.mkdir(parents=True)

    assert find_project_roots(tmp_path, "CSDL_SOHOA_LONGDIEN") == [project]


def test_validate_project_file_accepts_expected_structure(tmp_path: Path) -> None:
    file_path = tmp_path / "CSDL_SOHOA_A" / "2023" / "HS" / "123" / "1.pdf"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"pdf")

    result = validate_project_file(tmp_path / "CSDL_SOHOA_A", file_path, levels())

    assert result.valid
    assert result.project_code == "CSDL_SOHOA_A"
    assert result.relative_project_path == Path("2023") / "HS" / "123" / "1.pdf"


def test_validate_project_file_rejects_bad_case_type(tmp_path: Path) -> None:
    file_path = tmp_path / "CSDL_SOHOA_A" / "2023" / "HoSo" / "123" / "1.pdf"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"pdf")

    result = validate_project_file(tmp_path / "CSDL_SOHOA_A", file_path, levels())

    assert not result.valid
    assert "Invalid Category" in result.message


def test_discover_files_splits_valid_and_invalid(tmp_path: Path) -> None:
    valid = tmp_path / "staff" / "date" / "SCAN" / "CSDL_SOHOA_A" / "2023" / "HS" / "123" / "1.pdf"
    invalid = tmp_path / "staff" / "date" / "SCAN" / "CSDL_SOHOA_A" / "abc" / "HS" / "123" / "2.pdf"
    valid.parent.mkdir(parents=True)
    invalid.parent.mkdir(parents=True)
    valid.write_bytes(b"ok")
    invalid.write_bytes(b"bad")

    discovered, invalid_rows = discover_files(
        "SCAN01", tmp_path, 1, "CSDL_SOHOA_A", levels()
    )

    assert [item.source_path for item in discovered] == [valid]
    assert invalid_rows[0][0] == invalid


def test_discover_files_supports_exact_project_code(tmp_path: Path) -> None:
    file_path = tmp_path / "operator" / "PROJECT_ALPHA" / "2024" / "DOC" / "A-001" / "scan.pdf"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"ok")

    discovered, invalid_rows = discover_files(
        "SCAN01",
        tmp_path,
        1,
        "PROJECT_ALPHA",
        levels(category="DOC"),
    )

    assert invalid_rows == []
    assert len(discovered) == 1
    assert discovered[0].project_code == "PROJECT_ALPHA"


def test_similar_project_prefix_is_not_discovered(tmp_path: Path) -> None:
    file_path = tmp_path / "PROJECT_ALPHA_OLD" / "2024" / "DOC" / "A-001" / "scan.pdf"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"old")

    discovered, invalid_rows = discover_files(
        "SCAN01", tmp_path, 1, "PROJECT_ALPHA", levels(category="DOC")
    )

    assert discovered == []
    assert invalid_rows == []


def test_integer_directory_level_rejects_non_digits(tmp_path: Path) -> None:
    file_path = tmp_path / "PROJECT_ALPHA" / "batch-one" / "scan.pdf"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"bad")
    dynamic_levels = [
        DirectoryLevel(None, 1, 1, "Batch", "INTEGER", []),
    ]

    result = validate_project_file(
        tmp_path / "PROJECT_ALPHA", file_path, dynamic_levels
    )

    assert not result.valid
    assert "Invalid Batch" in result.message
