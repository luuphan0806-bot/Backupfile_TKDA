from __future__ import annotations

from scan_backup_manager.i18n import SUPPORTED_LANGUAGES, translate


def test_vietnamese_translation_is_available() -> None:
    assert "vi" in SUPPORTED_LANGUAGES
    assert translate("vi", "action.backup_now") == "Chạy backup"


def test_missing_language_falls_back_to_vietnamese_catalog() -> None:
    assert translate("unknown", "status.ready") == "Sẵn sàng"
