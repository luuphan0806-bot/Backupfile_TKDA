from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .models import DirectoryLevel, DiscoveredFile, ValidationResult


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iso_from_mtime(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=timezone.utc).replace(microsecond=0).isoformat()


def is_same_file(source: Path, dest: Path) -> bool:
    if not source.exists() or not dest.exists():
        return False
    if source.stat().st_size != dest.stat().st_size:
        return False
    return sha256_file(source) == sha256_file(dest)


def make_readonly(path: Path) -> None:
    if path.exists():
        os.chmod(path, stat.S_IREAD)


def make_writable(path: Path) -> None:
    if path.exists():
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def find_project_roots(root: Path, project_code: str) -> list[Path]:
    roots: list[Path] = []
    if not root.exists():
        return roots
    normalized_code = project_code.strip().upper()
    if not normalized_code:
        return roots
    for current, dirnames, _filenames in os.walk(root):
        current_path = Path(current)
        matching = [name for name in dirnames if name.upper() == normalized_code]
        for name in matching:
            roots.append(current_path / name)
        dirnames[:] = [name for name in dirnames if name.upper() != normalized_code]
    return sorted(roots)


def validate_project_file(
    project_root: Path,
    file_path: Path,
    levels: list[DirectoryLevel],
    *,
    numeric_sequence_check: bool = False,
) -> ValidationResult:
    try:
        relative = file_path.relative_to(project_root)
    except ValueError:
        return ValidationResult(False, "File is not inside project root")

    parts = relative.parts
    if len(parts) != len(levels) + 1:
        expected = "/".join(level.display_name for level in levels)
        return ValidationResult(False, f"Expected {expected}/file.pdf")

    directory_values = parts[:-1]
    filename = parts[-1]
    for level, value in zip(levels, directory_values):
        clean_value = value.strip()
        if not clean_value:
            return ValidationResult(False, f"Missing {level.display_name}")
        if level.validation_type == "YEAR4" and not (
            clean_value.isdigit() and len(clean_value) == 4
        ):
            return ValidationResult(False, f"Invalid {level.display_name}: {value}")
        if level.validation_type == "INTEGER" and not clean_value.isdigit():
            return ValidationResult(False, f"Invalid {level.display_name}: {value}")
        if level.validation_type == "ENUM":
            allowed = {item.upper() for item in level.allowed_values}
            if clean_value.upper() not in allowed:
                return ValidationResult(False, f"Invalid {level.display_name}: {value}")
    if not filename.lower().endswith(".pdf"):
        return ValidationResult(False, f"Not a PDF file: {filename}")
    if numeric_sequence_check and not Path(filename).stem.isdigit():
        return ValidationResult(False, f"PDF file name is not numeric: {filename}")

    return ValidationResult(
        True,
        project_code=project_root.name,
        relative_project_path=relative,
    )


def discover_files(
    client_code: str,
    share_path: Path,
    project_id: int,
    project_code: str,
    levels: list[DirectoryLevel],
    *,
    numeric_sequence_check: bool = False,
) -> tuple[list[DiscoveredFile], list[tuple[Path, str, str, Path | None]]]:
    discovered: list[DiscoveredFile] = []
    invalid: list[tuple[Path, str, str, Path | None]] = []
    for project_root in find_project_roots(share_path, project_code):
        for file_path in project_root.rglob("*"):
            if not file_path.is_file():
                continue
            result = validate_project_file(
                project_root,
                file_path,
                levels,
                numeric_sequence_check=numeric_sequence_check,
            )
            if not result.valid:
                relative = None
                try:
                    relative = file_path.relative_to(project_root)
                except ValueError:
                    pass
                invalid.append((file_path, result.message, project_root.name, relative))
                continue
            stat_result = file_path.stat()
            discovered.append(
                DiscoveredFile(
                    project_id=project_id,
                    client_code=client_code,
                    source_path=file_path,
                    project_code=result.project_code,
                    relative_project_path=result.relative_project_path or Path(),
                    file_size=stat_result.st_size,
                    source_mtime=stat_result.st_mtime,
                )
            )
    return discovered, invalid


def is_file_stable(path: Path, wait_seconds: int) -> bool:
    first = path.stat()
    time.sleep(max(wait_seconds, 0))
    second = path.stat()
    return first.st_size == second.st_size and int(first.st_mtime) == int(second.st_mtime)


def copy_with_robocopy_or_shutil(source: Path, dest: Path, staging_dir: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged = staging_dir / f"{dest.name}.tmp"
    if staged.exists():
        make_writable(staged)
        staged.unlink()

    robocopy = shutil.which("robocopy")
    if robocopy:
        staged_parent = staged.parent
        staged_name = staged.name
        temp_source = staged_parent / staged_name
        shutil.copy2(source, temp_source)
        result = subprocess.run(
            [
                robocopy,
                str(staged_parent),
                str(dest.parent),
                staged_name,
                "/COPY:DAT",
                "/R:2",
                "/W:1",
                "/NFL",
                "/NDL",
                "/NJH",
                "/NJS",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode >= 8:
            raise RuntimeError(f"robocopy failed ({result.returncode}): {result.stderr or result.stdout}")
        copied_temp = dest.parent / staged_name
        if copied_temp.exists():
            if dest.exists():
                make_writable(copied_temp)
                copied_temp.unlink()
                raise FileExistsError(dest)
            copied_temp.replace(dest)
        if temp_source.exists():
            make_writable(temp_source)
            temp_source.unlink()
        return

    shutil.copy2(source, staged)
    if dest.exists():
        make_writable(staged)
        staged.unlink()
        raise FileExistsError(dest)
    staged.replace(dest)
