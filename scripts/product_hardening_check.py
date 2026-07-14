from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _set_data_dir(path: str | None) -> None:
    if path:
        os.environ["SCAN_BACKUP_DATA_DIR"] = str(Path(path).resolve())


def _health(args: argparse.Namespace) -> int:
    _set_data_dir(args.data_dir)
    from scan_backup_manager.constants import runtime_data_dir, runtime_db_path
    from scan_backup_manager.db import DEFAULT_ADMIN_PASSWORD, Database
    from scan_backup_manager.logging_config import setup_logging
    from scan_backup_manager.service_core import BackupJobService

    logger = setup_logging()
    db_path = runtime_db_path()
    db = Database(db_path)
    service = BackupJobService(db, instance_id="product-health-check")
    service.schedule_due_projects()
    db.update_heartbeat(service.instance_id, "health-check")

    checks = {
        "data_dir": str(runtime_data_dir()),
        "db_path": str(db.db_path),
        "db_exists": db.db_path.is_file(),
        "admin_default_password_valid": db.verify_admin_password(DEFAULT_ADMIN_PASSWORD),
        "admin_must_change_password": db.admin_must_change_password(),
        "project_count": len(db.list_projects()),
        "log_file": str(next(iter(logger.handlers)).baseFilename) if logger.handlers else "",
    }
    failed = [key for key, value in checks.items() if key.endswith("_exists") and not value]
    print(json.dumps({"ok": not failed, "checks": checks, "failed": failed}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


def _snapshot(args: argparse.Namespace) -> int:
    _set_data_dir(args.data_dir)
    from scan_backup_manager.maintenance import create_database_snapshot

    snapshot = create_database_snapshot(
        args.db_path,
        backup_dir=args.backup_dir,
        label=args.label,
    )
    print(snapshot)
    return 0


def _restore(args: argparse.Namespace) -> int:
    _set_data_dir(args.data_dir)
    from scan_backup_manager.maintenance import restore_database_snapshot

    pre_restore = restore_database_snapshot(
        args.snapshot_path,
        args.db_path,
        backup_dir=args.backup_dir,
    )
    print(json.dumps({"restored": str(args.snapshot_path), "pre_restore": str(pre_restore) if pre_restore else ""}, ensure_ascii=False))
    return 0


def _pipeline(args: argparse.Namespace) -> int:
    _set_data_dir(args.data_dir)
    from pypdf import PdfWriter

    from scan_backup_manager.backup import BackupManager
    from scan_backup_manager.constants import runtime_data_dir, runtime_db_path
    from scan_backup_manager.db import Database
    from scan_backup_manager.mapfile import MapfileService
    from scan_backup_manager.models import Client, DirectoryLevel, Personnel, Project, ProjectSettings

    data_dir = runtime_data_dir()
    share_dir = data_dir / "pipeline_share"
    backup_dir = data_dir / "pipeline_backup"
    staging_dir = data_dir / "pipeline_staging"
    conflicts_dir = data_dir / "pipeline_conflicts"
    reports_dir = data_dir / "pipeline_reports"
    db = Database(runtime_db_path())
    project_id = db.create_project(
        Project(
            None,
            "PIPE",
            "Pipeline Smoke",
            str(backup_dir),
            str(staging_dir),
            str(conflicts_dir),
            str(reports_dir),
        )
    )
    settings = db.get_project_settings(project_id)
    db.save_project_settings(
        ProjectSettings(project_id, settings.poll_interval_seconds, 0, False)
    )
    db.save_directory_levels(
        project_id,
        [
            DirectoryLevel(None, project_id, 1, "Year", "YEAR4", ["2026"], True, 1),
            DirectoryLevel(None, project_id, 2, "Type", "ENUM", ["HS"], True, 2, True),
            DirectoryLevel(None, project_id, 3, "Code", "TEXT", [], True, 3),
        ],
    )
    scanner_id = db.save_personnel(Personnel(None, project_id, "NV001", "Smoke Scanner", "Scanner"))
    db.save_client(Client(None, project_id, "LOCAL", "Local Smoke", str(share_dir), True))
    record_parts = ["2026", "HS", "001"]
    record_key = "/".join(record_parts)
    MapfileService(db).add_manual_record(project_id, record_parts)
    db.save_record_assignment(
        project_id=project_id,
        record_key=record_key,
        personnel_id=scanner_id,
        work_date="12/07/2026",
        assignment_kind="scan",
        paper_presence={"A3": False},
    )

    source_pdf = share_dir / "PIPE" / "2026" / "HS" / "001" / "001.pdf"
    source_pdf.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source_pdf.open("wb") as handle:
        writer.write(handle)

    counters = BackupManager(db).run_all_enabled(project_id)
    backup_pdf = backup_dir / "PIPE" / "2026" / "HS" / "001" / "001.pdf"
    ready = db.list_check_ready_system_records(project_id)
    ok = (
        counters.get("processed") == 1
        and counters.get("errors") == 0
        and counters.get("conflicts") == 0
        and backup_pdf.is_file()
        and [record["record_key"] for record in ready] == [record_key]
    )
    print(
        json.dumps(
            {
                "ok": ok,
                "data_dir": str(data_dir),
                "project_id": project_id,
                "record_key": record_key,
                "source_pdf": str(source_pdf),
                "backup_pdf": str(backup_pdf),
                "counters": counters,
                "check_ready": [record["record_key"] for record in ready],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


def _ui_compose(args: argparse.Namespace) -> int:
    _set_data_dir(args.data_dir)
    from scan_backup_manager.constants import runtime_db_path
    from scan_backup_manager.db import DEFAULT_ADMIN_PASSWORD
    from scan_backup_manager.models import Project
    from scan_backup_manager.ui.app import (
        NAV_AUDIT,
        NAV_PROJECTS,
        NAV_SETTINGS,
        ScanBackupFletApp,
    )
    from scan_backup_manager.ui.views.project_console import (
        TAB_CATALOG,
        TAB_DASHBOARD,
        TAB_LEADER_WORKBENCH,
        TAB_SETTINGS as TAB_PROJECT_SETTINGS,
        TAB_STATISTICS,
        TAB_SYSTEM_MAPFILE,
        ConsoleContext,
    )

    class FakePage:
        def __init__(self) -> None:
            self.window = SimpleNamespace(
                width=None,
                height=None,
                min_width=None,
                min_height=None,
            )
            self.controls = []
            self.services = []
            self.overlay = []
            self.title = ""
            self.on_resize = None
            self.update_count = 0

        def update(self) -> None:
            self.update_count += 1

    page = FakePage()
    app = ScanBackupFletApp(page, runtime_db_path())
    screens: list[dict[str, object]] = []

    def walk_controls(control, seen: set[int] | None = None):
        if seen is None:
            seen = set()
        if id(control) in seen:
            return
        seen.add(id(control))
        yield control
        for attr in ("content", "leading", "trailing"):
            child = getattr(control, attr, None)
            if child is not None:
                yield from walk_controls(child, seen)
        for attr in ("controls", "actions", "tabs", "rows", "cells"):
            children = getattr(control, attr, None)
            if children:
                for child in children:
                    yield from walk_controls(child, seen)

    def control_value(control, key: str):
        values = getattr(control, "_values", {})
        if isinstance(values, dict) and key in values:
            return values[key]
        return getattr(control, key, None)

    def find_button(label: str):
        for root in page.controls:
            for control in walk_controls(root):
                if control_value(control, "content") == label:
                    return control
        return None

    def record(name: str) -> None:
        screens.append(
            {
                "name": name,
                "root_controls": len(page.controls),
                "services": len(page.services),
                "updates": page.update_count,
            }
        )

    first_run_requires_password_change = app.db.admin_must_change_password()
    snapshot_created = False
    record("role-selection")
    app.show_admin_login()
    record("admin-login")
    app.show_change_password(force=True, current_password=DEFAULT_ADMIN_PASSWORD)
    record("first-run-change-password")
    app.db.change_admin_password(DEFAULT_ADMIN_PASSWORD, "ChangeMe123!")
    app.show_main_shell()
    record("main-shell-overview")

    data_dir = runtime_db_path().parent
    project_id = app.db.create_project(
        Project(
            None,
            "UI-SMOKE",
            "UI Composition Smoke",
            str(data_dir / "ui_backup"),
            str(data_dir / "ui_staging"),
            str(data_dir / "ui_conflicts"),
            str(data_dir / "ui_reports"),
        )
    )
    app.current_project_id = project_id
    console = ConsoleContext(app, project_id)
    for tab_name, tab_index in (
        ("project-dashboard", TAB_DASHBOARD),
        ("project-catalog", TAB_CATALOG),
        ("project-system-mapfile", TAB_SYSTEM_MAPFILE),
        ("project-leader-workbench", TAB_LEADER_WORKBENCH),
        ("project-statistics", TAB_STATISTICS),
        ("project-settings", TAB_PROJECT_SETTINGS),
    ):
        console.tab_index = tab_index
        console.render()
        app.content_switcher.content = console.root
        page.update()
        record(tab_name)

    for nav_name, nav_index in (
        ("projects", NAV_PROJECTS),
        ("settings-recovery", NAV_SETTINGS),
        ("audit", NAV_AUDIT),
    ):
        app.nav_index = nav_index
        app.current_project_id = None
        app.refresh_content()
        record(nav_name)
        if nav_name == "settings-recovery":
            snapshot_button = find_button("Sao lưu ngay")
            if snapshot_button is None:
                failed_snapshot = "settings-recovery-snapshot-button"
            else:
                failed_snapshot = ""
                handler = control_value(snapshot_button, "on_click")
                if handler is None:
                    failed_snapshot = "settings-recovery-snapshot-handler"
                else:
                    before_snapshots = set((app.db.db_path.parent / "db_backups").glob("*.sqlite3"))
                    handler(None)
                    after_snapshots = set((app.db.db_path.parent / "db_backups").glob("*.sqlite3"))
                    snapshot_created = bool(after_snapshots - before_snapshots)
                    if not snapshot_created:
                        failed_snapshot = "settings-recovery-snapshot-created"
                    if bool(getattr(snapshot_button, "disabled", False)):
                        failed_snapshot = "settings-recovery-snapshot-button-stuck-disabled"

    app.show_personnel_login()
    record("personnel-login")

    failed = [screen["name"] for screen in screens if int(screen["root_controls"]) < 1]
    settings_screen = next(screen for screen in screens if screen["name"] == "settings-recovery")
    if int(settings_screen["services"]) < 1:
        failed.append("settings-recovery-file-picker")
    if "failed_snapshot" in locals() and failed_snapshot:
        failed.append(failed_snapshot)

    payload = {
        "ok": not failed,
        "db_path": str(runtime_db_path()),
        "first_run_requires_password_change": first_run_requires_password_change,
        "settings_snapshot_created": snapshot_created,
        "screens": screens,
        "failed": failed,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Product hardening checks and DB recovery helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("health", help="first-run/runtime health check")
    health.add_argument("--data-dir", help="override SCAN_BACKUP_DATA_DIR")
    health.set_defaults(func=_health)

    snapshot = subparsers.add_parser("snapshot", help="create a consistent DB snapshot")
    snapshot.add_argument("--data-dir", help="override SCAN_BACKUP_DATA_DIR")
    snapshot.add_argument("--db-path", help="explicit SQLite DB path")
    snapshot.add_argument("--backup-dir", help="directory for snapshots")
    snapshot.add_argument("--label", default="manual", help="snapshot filename label")
    snapshot.set_defaults(func=_snapshot)

    restore = subparsers.add_parser("restore", help="restore a DB snapshot")
    restore.add_argument("snapshot_path", help="snapshot SQLite file to restore")
    restore.add_argument("--data-dir", help="override SCAN_BACKUP_DATA_DIR")
    restore.add_argument("--db-path", help="explicit SQLite DB path")
    restore.add_argument("--backup-dir", help="directory for pre-restore snapshot")
    restore.set_defaults(func=_restore)

    pipeline = subparsers.add_parser("pipeline", help="local end-to-end scan backup/check-readiness smoke")
    pipeline.add_argument("--data-dir", help="override SCAN_BACKUP_DATA_DIR")
    pipeline.set_defaults(func=_pipeline)

    ui_compose = subparsers.add_parser("ui-compose", help="compose first-run auth and main Flet views without a real display")
    ui_compose.add_argument("--data-dir", help="override SCAN_BACKUP_DATA_DIR")
    ui_compose.set_defaults(func=_ui_compose)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
