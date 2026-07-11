from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


LevelType = Literal["YEAR4", "ENUM", "INTEGER", "TEXT"]


@dataclass(slots=True)
class Project:
    id: int | None
    project_code: str
    display_name: str
    backup_root: str
    staging_dir: str
    conflict_archive_dir: str
    reports_dir: str
    enabled: bool = True


@dataclass(slots=True)
class DirectoryLevel:
    id: int | None
    project_id: int
    position: int
    display_name: str
    validation_type: LevelType
    allowed_values: list[str]
    show_in_mapfile: bool = True
    mapfile_position: int = 0
    require_catalog_selection: bool = False


@dataclass(slots=True)
class Client:
    id: int | None
    project_id: int
    client_code: str
    staff_name: str
    share_path: str
    enabled: bool = True
    notes: str = ""


@dataclass(slots=True)
class ProjectSettings:
    project_id: int
    poll_interval_seconds: int
    stability_wait_seconds: int
    numeric_sequence_check: bool


@dataclass(slots=True)
class Personnel:
    id: int | None
    project_id: int
    personnel_code: str
    full_name: str
    role_name: str
    enabled: bool = True


@dataclass(slots=True)
class PaperFormat:
    id: int | None
    project_id: int
    code: str
    display_name: str
    requires_separate_scan: bool = True
    requires_check: bool = True
    enabled: bool = True
    sort_order: int = 0


@dataclass(slots=True)
class JobType:
    id: int | None
    project_id: int
    job_code: str
    display_name: str
    enabled: bool = True
    sort_order: int = 0
    job_kind: str = "SCAN"


@dataclass(slots=True)
class ProjectTask:
    id: int | None
    project_id: int
    task_code: str
    title: str
    description: str
    assignee_id: int
    due_date: str
    priority: str = "NORMAL"
    status: str = "NEW"
    record_key: str = ""
    task_kind: str = ""
    work_date: str = ""
    started_at: str = ""
    finished_at: str = ""
    attendance_status: str = "PENDING"


@dataclass(slots=True)
class AttendanceEntry:
    id: int | None
    project_id: int
    task_id: int | None
    record_key: str
    personnel_id: int
    work_date: str
    task_kind: str
    job_title: str
    quantity: int = 1
    completed_count: int = 0
    status: str = "PENDING"
    approved_by: str = ""
    approved_at: str = ""
    override_reason: str = ""
    notes: str = ""


@dataclass(slots=True)
class DiscoveredFile:
    project_id: int
    client_code: str
    source_path: Path
    project_code: str
    relative_project_path: Path
    file_size: int
    source_mtime: float


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    message: str = ""
    project_code: str = ""
    relative_project_path: Path | None = None


@dataclass(slots=True)
class BackupOutcome:
    status: str
    message: str = ""
    dest_path: Path | None = None
    backup_file_id: int | None = None


@dataclass(slots=True)
class MapfileProfile:
    id: int | None
    project_id: int
    name: str
    sheet_name: str
    project_column: str
    year_column: str
    case_type_column: str
    case_number_column: str
    file_name_column: str
