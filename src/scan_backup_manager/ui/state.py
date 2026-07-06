from __future__ import annotations

from dataclasses import dataclass

from ..backup import BackupManager
from ..db import Database
from ..i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, translate
from ..mapfile import MapfileService
from ..reports import ReportService
from ..statistics import StatisticsService


@dataclass
class AppState:
    """Holds everything a Flet view needs besides the ft.Page itself.

    Created once per app process and passed down to every view -- there is no
    per-request session, this is a single-operator desktop console.
    """

    db: Database
    backup: BackupManager
    mapfiles: MapfileService
    reports: ReportService
    stats: StatisticsService
    language: str
    theme_mode: str
    authenticated: bool = False
    admin_must_change_password: bool = False
    personnel_id: int | None = None
    personnel_project_id: int | None = None

    @classmethod
    def create(cls, db: Database) -> "AppState":
        language = db.get_setting("language", DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE
        if language not in SUPPORTED_LANGUAGES:
            language = DEFAULT_LANGUAGE
        theme_mode = db.get_setting("theme_mode", "dark") or "dark"
        return cls(
            db=db,
            backup=BackupManager(db),
            mapfiles=MapfileService(db),
            reports=ReportService(db),
            stats=StatisticsService(db),
            language=language,
            theme_mode=theme_mode,
        )

    def t(self, key: str, **kwargs: object) -> str:
        return translate(self.language, key, **kwargs)
