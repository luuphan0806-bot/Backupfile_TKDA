from __future__ import annotations

import sys
import threading

from .constants import runtime_db_path
from .db import Database
from .logging_config import setup_logging
from .service_core import BackupJobService

try:  # pragma: no cover - imports are Windows/service-host specific
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil
except ImportError:  # pragma: no cover
    servicemanager = win32event = win32service = win32serviceutil = None


if win32serviceutil is not None:
    class ScanBackupWindowsService(win32serviceutil.ServiceFramework):
        _svc_name_ = "ScanBackupService"
        _svc_display_name_ = "Scan Backup Manager - Dịch vụ sao lưu"
        _svc_description_ = "Tự động quét máy trạm và sao lưu hồ sơ dự án."

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = threading.Event()
            self.wait_handle = win32event.CreateEvent(None, 0, 0, None)

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self.stop_event.set()
            win32event.SetEvent(self.wait_handle)

        def SvcDoRun(self):
            setup_logging()
            servicemanager.LogInfoMsg("ScanBackupService started")
            BackupJobService(Database(runtime_db_path())).run(self.stop_event)
else:
    ScanBackupWindowsService = None


def run_console() -> None:
    """Run the service loop in a console for development and diagnostics."""
    setup_logging()
    stop = threading.Event()
    try:
        BackupJobService(Database(runtime_db_path())).run(stop)
    except KeyboardInterrupt:
        stop.set()


def run_service_command_line() -> None:
    if win32serviceutil is None or ScanBackupWindowsService is None:
        raise SystemExit("Install pywin32 to manage Windows Service")
    if len(sys.argv) == 1:
        # When Windows Service Control Manager starts a frozen EXE there are no
        # command-line args. pywin32's HandleCommandLine is only for install,
        # remove, debug, etc.; the service host must attach to SCM explicitly.
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ScanBackupWindowsService)
        servicemanager.StartServiceCtrlDispatcher()
        return
    win32serviceutil.HandleCommandLine(ScanBackupWindowsService)


if __name__ == "__main__":
    run_service_command_line()
