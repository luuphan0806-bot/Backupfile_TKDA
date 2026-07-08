from __future__ import annotations

from datetime import date, datetime


DISPLAY_DATE_FORMAT = "%d/%m/%Y"
STORAGE_DATE_FORMAT = "%Y-%m-%d"
DISPLAY_DATE_HINT = "dd/mm/yyyy"


def today_display() -> str:
    return date.today().strftime(DISPLAY_DATE_FORMAT)


def iso_to_display(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        return datetime.strptime(text[:10], STORAGE_DATE_FORMAT).strftime(DISPLAY_DATE_FORMAT)
    except ValueError:
        return text


def iso_datetime_to_display(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return iso_to_display(text)
    return parsed.strftime("%d/%m/%Y %H:%M:%S")


def display_to_iso(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    for fmt in (DISPLAY_DATE_FORMAT, STORAGE_DATE_FORMAT):
        try:
            return datetime.strptime(text[:10], fmt).strftime(STORAGE_DATE_FORMAT)
        except ValueError:
            continue
    raise ValueError(f"Ngày phải có định dạng {DISPLAY_DATE_HINT}.")
