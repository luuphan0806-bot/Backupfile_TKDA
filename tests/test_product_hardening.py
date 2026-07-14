from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import scan_backup_manager
from scan_backup_manager.db import Database
from scan_backup_manager.maintenance import (
    create_database_snapshot,
    restore_database_snapshot,
)
from scan_backup_manager.models import Project


def test_release_version_has_one_canonical_source() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == scan_backup_manager.__version__
    installer = (repo_root / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert '#define AppVersion GetVersionNumbersString("..\\dist\\ScanBackupManager.exe")' in installer


def test_service_exe_without_args_attaches_to_scm(monkeypatch) -> None:
    from scan_backup_manager import windows_service

    calls: list[object] = []

    class FakeServiceManager:
        @staticmethod
        def Initialize() -> None:
            calls.append("initialize")

        @staticmethod
        def PrepareToHostSingle(service_class) -> None:
            calls.append(("prepare", service_class))

        @staticmethod
        def StartServiceCtrlDispatcher() -> None:
            calls.append("dispatch")

    service_class = object()
    monkeypatch.setattr(windows_service, "servicemanager", FakeServiceManager)
    monkeypatch.setattr(windows_service, "win32serviceutil", object())
    monkeypatch.setattr(windows_service, "ScanBackupWindowsService", service_class)
    monkeypatch.setattr(sys, "argv", ["ScanBackupService.exe"])

    windows_service.run_service_command_line()

    assert calls == ["initialize", ("prepare", service_class), "dispatch"]


def test_database_snapshot_and_restore_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime" / "app.sqlite3"
    db = Database(db_path)
    db.create_project(
        Project(
            None,
            "ALPHA",
            "Alpha",
            str(tmp_path / "backup"),
            str(tmp_path / "staging"),
            str(tmp_path / "conflicts"),
            str(tmp_path / "reports"),
        )
    )
    snapshot = create_database_snapshot(db_path, backup_dir=tmp_path / "snapshots")

    db.create_project(
        Project(
            None,
            "BETA",
            "Beta",
            str(tmp_path / "backup_b"),
            str(tmp_path / "staging_b"),
            str(tmp_path / "conflicts_b"),
            str(tmp_path / "reports_b"),
        )
    )
    assert [project.project_code for project in db.list_projects()] == ["ALPHA", "BETA"]

    pre_restore = restore_database_snapshot(
        snapshot,
        db_path,
        backup_dir=tmp_path / "snapshots",
    )

    assert pre_restore is not None
    restored = Database(db_path)
    assert [project.project_code for project in restored.list_projects()] == ["ALPHA"]


def test_product_health_check_bootstraps_clean_data_dir(tmp_path: Path) -> None:
    env = {**os.environ, "SCAN_BACKUP_DATA_DIR": str(tmp_path / "data")}
    result = subprocess.run(
        [
            sys.executable,
            "scripts/product_hardening_check.py",
            "health",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["checks"]["db_exists"] is True
    assert payload["checks"]["admin_default_password_valid"] is True
    assert payload["checks"]["admin_must_change_password"] is True
    assert Path(payload["checks"]["log_file"]).is_file()


def test_product_pipeline_smoke_creates_real_backup_and_check_ready_record(tmp_path: Path) -> None:
    env = {**os.environ, "SCAN_BACKUP_DATA_DIR": str(tmp_path / "data")}
    result = subprocess.run(
        [
            sys.executable,
            "scripts/product_hardening_check.py",
            "pipeline",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["counters"] == {"clients": 1, "processed": 1, "errors": 0, "conflicts": 0}
    assert Path(payload["backup_pdf"]).is_file()
    assert payload["check_ready"] == [payload["record_key"]]


def test_ui_composition_smoke_covers_first_run_and_recovery_screen(tmp_path: Path) -> None:
    env = {**os.environ, "SCAN_BACKUP_DATA_DIR": str(tmp_path / "data")}
    result = subprocess.run(
        [
            sys.executable,
            "scripts/product_hardening_check.py",
            "ui-compose",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["first_run_requires_password_change"] is True
    assert payload["settings_snapshot_created"] is True
    names = {screen["name"]: screen for screen in payload["screens"]}
    assert {
        "role-selection",
        "admin-login",
        "first-run-change-password",
        "main-shell-overview",
        "project-dashboard",
        "project-catalog",
        "project-system-mapfile",
        "project-leader-workbench",
        "project-statistics",
        "project-settings",
        "projects",
        "settings-recovery",
        "audit",
        "personnel-login",
    } <= set(names)
    assert len(payload["screens"]) >= 14
    assert names["settings-recovery"]["services"] >= 1
