import sys

from scan_backup_manager.windows_service import run_console, run_service_command_line


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() == "console":
        run_console()
    else:
        run_service_command_line()
