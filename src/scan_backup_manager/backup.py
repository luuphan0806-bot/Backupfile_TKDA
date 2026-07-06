from __future__ import annotations

import shutil
import time
from pathlib import Path

from .constants import (
    STATUS_ALREADY_EXISTS,
    STATUS_CONFLICT,
    STATUS_COPYING,
    STATUS_ERROR,
    STATUS_HASH_PENDING,
    STATUS_INVALID_STRUCTURE,
    STATUS_LOCKED,
    STATUS_WAITING_STABLE,
)
from .db import Database
from .filesystem import (
    copy_with_robocopy_or_shutil,
    discover_files,
    find_project_roots,
    is_file_stable,
    iso_from_mtime,
    make_readonly,
    make_writable,
    sha256_file,
    validate_project_file,
)
from .models import BackupOutcome, Client, DiscoveredFile, Project


class BackupManager:
    def __init__(self, db: Database):
        self.db = db

    def run_all_enabled(self, project_id: int, *, job_id: int | None = None) -> dict[str, int]:
        totals = {"clients": 0, "processed": 0, "errors": 0, "conflicts": 0}
        project = self.db.get_project(project_id)
        if not project or not project.enabled:
            raise ValueError("Configure and enable the project before running backup")
        if not self.db.list_directory_levels(project_id):
            raise ValueError("Configure at least one project directory level")
        for client in self.db.list_clients(project_id):
            if not client.enabled:
                continue
            totals["clients"] += 1
            result = self.run_client(project, client, job_id=job_id)
            totals["processed"] += result["processed"]
            totals["errors"] += result["errors"]
            totals["conflicts"] += result["conflicts"]
        return totals

    def run_client(
        self, project: Project, client: Client, *, job_id: int | None = None
    ) -> dict[str, int]:
        share = Path(client.share_path)
        counts = {"processed": 0, "errors": 0, "conflicts": 0}
        available = False
        for attempt in range(3):
            if share.exists():
                available = True
                break
            if attempt < 2:
                time.sleep(0.2 * (2 ** attempt))
        if not available:
            self.db.record_audit(
                "CLIENT_OFFLINE",
                "Share path is not accessible",
                client.client_code,
                client.share_path,
                None,
                project_id=project.id,
            )
            return {**counts, "errors": 1}

        levels = self.db.list_directory_levels(project.id or 0)
        numeric_sequence_check = self.db.get_project_settings(project.id or 0).numeric_sequence_check
        discovered, invalid = discover_files(
            client.client_code,
            share,
            project.id or 0,
            project.project_code,
            levels,
            numeric_sequence_check=numeric_sequence_check,
        )

        for source_path, message, project_code, relative in invalid:
            dest = Path(project.backup_root) / project_code / (relative or Path(source_path.name))
            self.db.upsert_backup_file(
                project_id=project.id or 0,
                client_code=client.client_code,
                source_path=str(source_path),
                project_code=project_code,
                relative_project_path=str(relative or ""),
                dest_path=str(dest),
                file_size=source_path.stat().st_size if source_path.exists() else None,
                source_mtime=iso_from_mtime(source_path.stat().st_mtime) if source_path.exists() else None,
                status=STATUS_INVALID_STRUCTURE,
                error_message=message,
            )
            self.db.record_audit(
                "INVALID_STRUCTURE",
                message,
                client.client_code,
                str(source_path),
                str(dest),
                project_id=project.id,
            )
            counts["errors"] += 1

        for item in discovered:
            outcome = self.process_file(project, item, job_id=job_id)
            counts["processed"] += 1
            if outcome.status == STATUS_ERROR:
                counts["errors"] += 1
            elif outcome.status == STATUS_CONFLICT:
                counts["conflicts"] += 1
        return counts

    def process_file(
        self, project: Project, item: DiscoveredFile, *, job_id: int | None = None
    ) -> BackupOutcome:
        dest = Path(project.backup_root) / item.project_code / item.relative_project_path
        staging_dir = Path(project.staging_dir) / str(project.id or 0) / str(job_id or "manual")
        stability_wait_seconds = self.db.get_project_settings(project.id or 0).stability_wait_seconds
        backup_file_id = self.db.upsert_backup_file(
            project_id=project.id or 0,
            client_code=item.client_code,
            source_path=str(item.source_path),
            project_code=item.project_code,
            relative_project_path=str(item.relative_project_path),
            dest_path=str(dest),
            file_size=item.file_size,
            source_mtime=iso_from_mtime(item.source_mtime),
            status="DISCOVERED",
        )
        lock_key = f"dest:{dest.resolve()}"
        lock_owner = f"job:{job_id or 'manual'}:{backup_file_id}"
        if not self.db.acquire_lock(lock_key, lock_owner):
            self.db.update_backup_status(
                backup_file_id, STATUS_WAITING_STABLE, "Another operation is processing this file"
            )
            return BackupOutcome(
                STATUS_WAITING_STABLE, "Another operation is processing this file",
                dest, backup_file_id,
            )

        try:
            if not is_file_stable(item.source_path, stability_wait_seconds):
                self.db.update_backup_status(
                    backup_file_id,
                    STATUS_WAITING_STABLE,
                    "File is still changing",
                )
                return BackupOutcome(STATUS_WAITING_STABLE, "File is still changing", dest, backup_file_id)

            if dest.exists():
                source_hash = sha256_file(item.source_path)
                dest_hash = sha256_file(dest)
                if item.source_path.stat().st_size == dest.stat().st_size and source_hash == dest_hash:
                    make_readonly(dest)
                    self.db.update_backup_status(
                        backup_file_id,
                        STATUS_ALREADY_EXISTS,
                        "Destination already has same content",
                        hash_sha256=source_hash,
                        verified=True,
                        locked=True,
                    )
                    return BackupOutcome(STATUS_ALREADY_EXISTS, "Same content exists", dest, backup_file_id)
                self.db.update_backup_status(
                    backup_file_id,
                    STATUS_CONFLICT,
                    "Destination exists with different content",
                    hash_sha256=source_hash,
                )
                self.db.record_conflict(
                    backup_file_id=backup_file_id,
                    client_code=item.client_code,
                    source_path=str(item.source_path),
                    dest_path=str(dest),
                    source_hash=source_hash,
                    dest_hash=dest_hash,
                )
                self.db.record_audit(
                    "CONFLICT",
                    "Destination exists with different content",
                    item.client_code,
                    str(item.source_path),
                    str(dest),
                    project_id=project.id,
                )
                return BackupOutcome(STATUS_CONFLICT, "Different content exists", dest, backup_file_id)

            self.db.update_backup_status(backup_file_id, STATUS_COPYING)
            copy_with_robocopy_or_shutil(item.source_path, dest, staging_dir)
            if not dest.exists() or dest.stat().st_size != item.source_path.stat().st_size:
                raise RuntimeError("Copied file failed size verification")
            make_readonly(dest)
            source_hash = sha256_file(item.source_path)
            self.db.update_backup_status(
                backup_file_id,
                STATUS_HASH_PENDING,
                "Size verified; hash verification pending",
                hash_sha256=source_hash,
                copied=True,
                verified=True,
                locked=True,
            )
            self.db.record_audit(
                "COPIED",
                "Copied and size verified",
                item.client_code,
                str(item.source_path),
                str(dest),
                project_id=project.id,
            )
            return BackupOutcome(STATUS_HASH_PENDING, "Copied", dest, backup_file_id)
        except Exception as exc:
            self.db.update_backup_status(backup_file_id, STATUS_ERROR, str(exc))
            self.db.record_audit(
                "ERROR", str(exc), item.client_code, str(item.source_path), str(dest),
                project_id=project.id,
            )
            return BackupOutcome(STATUS_ERROR, str(exc), dest, backup_file_id)
        finally:
            self.db.release_lock(lock_key, lock_owner)

    def backup_single_mapfile_row(self, project_id: int, row_id: int) -> BackupOutcome:
        """Backup exactly the 1 file referenced by a mapfile row, on demand.

        Unlike run_all_enabled/run_client, this does not crawl an entire share —
        it targets the exact expected_relative_path and only checks whether it
        exists on one of the project's enabled workstation shares.
        """
        project = self.db.get_project(project_id)
        if not project or not project.enabled:
            raise ValueError("Project is not configured or is disabled")
        row = self.db.get_mapfile_row(row_id)
        if not row:
            raise ValueError(f"Mapfile row not found: {row_id}")
        imported = self.db.get_mapfile_import(row["import_id"])
        if not imported or int(imported["project_id"]) != project_id:
            raise ValueError("Mapfile row does not belong to this project")
        if not row["is_done"]:
            raise ValueError("Row must be marked Done before triggering backup")
        if row["status"] == "MATCHED":
            raise ValueError("Row is already backed up")

        expected = Path(row["expected_relative_path"])
        if expected.is_absolute() or ".." in expected.parts or len(expected.parts) < 2:
            raise ValueError(f"Malformed expected path for row {row_id}: {expected}")
        relative_within_root = Path(*expected.parts[1:])
        levels = self.db.list_directory_levels(project_id)
        numeric_sequence_check = self.db.get_project_settings(project_id).numeric_sequence_check

        for client in self.db.list_clients(project_id):
            if not client.enabled:
                continue
            share = Path(client.share_path)
            if not share.exists():
                continue
            for project_root in find_project_roots(share, project.project_code):
                candidate = project_root / relative_within_root
                try:
                    candidate.resolve().relative_to(project_root.resolve())
                except ValueError:
                    continue
                if not candidate.is_file():
                    continue
                validation = validate_project_file(
                    project_root, candidate, levels,
                    numeric_sequence_check=numeric_sequence_check,
                )
                if not validation.valid:
                    continue
                stat_result = candidate.stat()
                item = DiscoveredFile(
                    project_id=project_id,
                    client_code=client.client_code,
                    source_path=candidate,
                    project_code=validation.project_code,
                    relative_project_path=validation.relative_project_path or Path(),
                    file_size=stat_result.st_size,
                    source_mtime=stat_result.st_mtime,
                )
                return self.process_file(project, item)

        raise FileNotFoundError(
            f"Could not find the physical file for mapfile row #{row_id} on any workstation"
        )

    def verify_hash_pending(self, project_id: int, limit: int = 100) -> int:
        rows = self.db.list_backup_files(project_id, statuses=[STATUS_HASH_PENDING], limit=limit)
        verified = 0
        for row in rows:
            dest = Path(row["dest_path"])
            try:
                if not dest.exists():
                    self.db.update_backup_status(row["id"], STATUS_ERROR, "Destination missing")
                    continue
                if not row["hash_sha256"] or row["hash_sha256"] != sha256_file(dest):
                    self.db.update_backup_status(row["id"], STATUS_ERROR, "SHA256 mismatch")
                    continue
                make_readonly(dest)
                self.db.update_backup_status(
                    row["id"],
                    STATUS_LOCKED,
                    "SHA256 verified and locked",
                    verified=True,
                    locked=True,
                )
                verified += 1
            except Exception as exc:
                self.db.update_backup_status(row["id"], STATUS_ERROR, str(exc))
        return verified

    def replace_conflict(
        self, project_id: int, conflict_id: int, *, job_id: int | None = None
    ) -> None:
        conflicts = [row for row in self.db.list_conflicts(project_id) if row["id"] == conflict_id]
        if not conflicts:
            raise ValueError(f"Open conflict not found: {conflict_id}")
        conflict = conflicts[0]
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError("Project is not configured")
        source = Path(conflict["source_path"])
        dest = Path(conflict["dest_path"])
        if not source.exists():
            raise FileNotFoundError(source)
        if not dest.exists():
            raise FileNotFoundError(dest)

        source_hash = sha256_file(source)
        archive_root = Path(project.conflict_archive_dir) / conflict["client_code"]
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_name = f"{dest.stem}.conflict-{conflict_id}{dest.suffix}"
        archive_path = archive_root / archive_name
        counter = 1
        while archive_path.exists():
            archive_path = archive_root / f"{dest.stem}.conflict-{conflict_id}-{counter}{dest.suffix}"
            counter += 1

        make_writable(dest)
        shutil.move(str(dest), str(archive_path))
        try:
            staging = Path(project.staging_dir) / str(project_id) / str(job_id or "manual")
            copy_with_robocopy_or_shutil(source, dest, staging)
            if dest.stat().st_size != source.stat().st_size:
                raise RuntimeError("Replacement failed size verification")
        except Exception:
            if dest.exists():
                make_writable(dest)
                dest.unlink()
            shutil.move(str(archive_path), str(dest))
            make_readonly(dest)
            raise
        make_readonly(dest)
        self.db.update_backup_status(
            conflict["backup_file_id"],
            STATUS_HASH_PENDING,
            "Leader replaced conflict; size verified",
            hash_sha256=source_hash,
            copied=True,
            verified=True,
            locked=True,
        )
        self.db.resolve_conflict(conflict_id, "REPLACED", str(archive_path))
        self.db.record_audit(
            "CONFLICT_REPLACED",
            f"Archived previous destination to {archive_path}",
            conflict["client_code"],
            str(source),
            str(dest),
            project_id=project_id,
        )
