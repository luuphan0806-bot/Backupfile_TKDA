from __future__ import annotations

import json
import socket
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone

from .backup import BackupManager
from .db import Database
from .logging_config import get_logger


SERVICE_VERSION = "1.0"
JOB_SCAN = "SCAN_PROJECT"
JOB_VERIFY = "VERIFY_INTEGRITY"
JOB_REPLACE_CONFLICT = "REPLACE_CONFLICT"


class BackupJobService:
    """Durable queue processor shared by the Windows service and tests."""

    def __init__(self, db: Database, *, instance_id: str | None = None):
        self.db = db
        self.backup = BackupManager(db)
        self.instance_id = instance_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._next_scan: dict[int, datetime] = {}
        self._last_verify_day: dict[int, str] = {}

    def schedule_due_projects(self) -> None:
        now = datetime.now(timezone.utc)
        verify_day = datetime.now().date().isoformat()
        for project in self.db.list_projects():
            if not project.enabled or project.id is None:
                continue
            due = self._next_scan.get(project.id)
            if due is None or due <= now:
                self.db.enqueue_job(project.id, JOB_SCAN, deduplicate=True)
                seconds = max(self.db.get_project_settings(project.id).poll_interval_seconds, 30)
                self._next_scan[project.id] = now + timedelta(seconds=seconds)
            if self._last_verify_day.get(project.id) != verify_day:
                self.db.enqueue_job(project.id, JOB_VERIFY, deduplicate=True)
                self._last_verify_day[project.id] = verify_day

    def process_one(self) -> bool:
        job = self.db.claim_next_job(self.instance_id)
        if not job:
            return False
        job_id = int(job["id"])
        project_id = int(job["project_id"])
        renew_stop = threading.Event()

        def renew_lease() -> None:
            while not renew_stop.wait(60):
                self.db.renew_job_lease(job_id, self.instance_id)

        renewer = threading.Thread(target=renew_lease, daemon=True)
        renewer.start()
        try:
            payload = json.loads(job["payload_json"] or "{}")
            if job["job_type"] == JOB_SCAN:
                counters = self.backup.run_all_enabled(project_id, job_id=job_id)
                status = "PARTIAL" if counters.get("errors") or counters.get("conflicts") else "SUCCEEDED"
            elif job["job_type"] == JOB_VERIFY:
                counters = {"verified": self.backup.verify_hash_pending(project_id)}
                status = "SUCCEEDED"
            elif job["job_type"] == JOB_REPLACE_CONFLICT:
                self.backup.replace_conflict(project_id, int(payload["conflict_id"]), job_id=job_id)
                counters = {"replaced": 1}
                status = "SUCCEEDED"
            else:
                raise ValueError(f"Unsupported job type: {job['job_type']}")
            self.db.finish_job(job_id, status, counters=counters)
        except Exception as exc:
            get_logger().exception("Job %s failed", job_id)
            self.db.finish_job(
                job_id, "FAILED", error_code=type(exc).__name__,
                error_detail=traceback.format_exc(),
            )
        finally:
            renew_stop.set()
            renewer.join(timeout=1)
        return True

    def run(self, stop_event: threading.Event, *, idle_seconds: float = 1.0) -> None:
        get_logger().info("Backup service started: %s", self.instance_id)
        while not stop_event.is_set():
            self.db.update_heartbeat(self.instance_id, SERVICE_VERSION)
            self.schedule_due_projects()
            if not self.process_one():
                stop_event.wait(idle_seconds)
        get_logger().info("Backup service stopped: %s", self.instance_id)
