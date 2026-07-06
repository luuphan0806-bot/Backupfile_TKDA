"""Convenience launcher: `python main.py`, equivalent to
`python -m scan_backup_manager` (see src/scan_backup_manager/__main__.py) or
the `scan-backup-manager` console script installed by `pip install -e .`.
"""
from scan_backup_manager.ui.app import run

if __name__ == "__main__":
    run()
