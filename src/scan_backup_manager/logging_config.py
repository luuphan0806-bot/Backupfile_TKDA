from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .constants import runtime_data_dir

DEFAULT_LOG_DIR = runtime_data_dir() / "logs"
LOGGER_NAME = "scan_backup_manager"


def setup_logging(log_dir: Path = DEFAULT_LOG_DIR) -> logging.Logger:
    """Configure the app-wide logger with a rotating file handler under
    `logs/`. Called once at startup; background worker failures (see
    ui/workers.py) are logged here even after the on-screen snackbar/status
    text is dismissed."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger  # already configured (e.g. re-entrant call in tests)

    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
