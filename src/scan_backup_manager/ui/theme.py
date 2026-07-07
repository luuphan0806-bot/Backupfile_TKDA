from __future__ import annotations

import flet as ft

# Hitech / futuristic system palette. Every hue below was picked with an
# electric, "hologram on deep space" mood, then verified (not eyeballed) with
# the dataviz skill's palette validator: dark-mode lightness band (OKLCH L
# 0.48-0.67), chroma floor (>= 0.10), CVD separation (all-pairs Machado-2009
# ΔE >= 12), and >= 3:1 contrast on both the dark (#05070D) and light
# (#F6F8FC) surfaces -- see the four status hues below, which all pass clean
# in both modes.
PRIMARY = "#3D5AFE"          # light-mode seed: electric indigo-blue
PRIMARY_DARK = "#22E1FF"     # dark-mode seed: electric cyan (the "glow" accent)
ACCENT = "#8B6CFF"           # secondary neon violet, for gradients/hero accents

BACKGROUND_DARK = "#05070D"      # near-black, cool -- the "deep space" plane
SURFACE_DARK = "#0C0F1A"
SURFACE_HIGH_DARK = "#141A2B"    # elevated cards/dialogs
BACKGROUND_LIGHT = "#F6F8FC"

SUCCESS = "#0C9663"
WARNING = "#C08313"
DANGER = "#FF3B5C"
INFO = "#4C8DFF"
NEUTRAL = "#8B94A7"

def content_switcher(initial: ft.Control | None = None) -> ft.Container:
    """Plain content host used for screen swaps without transition animation."""
    return ft.Container(
        content=initial or ft.Container(),
        expand=True,
    )


def build_theme(mode: str) -> ft.Theme:
    seed = PRIMARY if mode == "light" else PRIMARY_DARK
    return ft.Theme(
        color_scheme_seed=seed,
        font_family="Segoe UI",
        visual_density=ft.VisualDensity.COMPACT,
    )


def apply_theme(page: ft.Page, mode: str) -> None:
    page.theme_mode = ft.ThemeMode.DARK if mode == "dark" else ft.ThemeMode.LIGHT
    page.theme = build_theme("light")
    page.dark_theme = build_theme("dark")
    page.padding = 0
    page.bgcolor = BACKGROUND_DARK if mode == "dark" else BACKGROUND_LIGHT


def status_color(status: str) -> str:
    ok = {"LOCKED", "HASH_PENDING", "VERIFIED_HASH", "ALREADY_EXISTS", "MATCHED", "COMPLETED"}
    pending = {"WAITING_STABLE", "DISCOVERED", "COPYING", "EXPECTED", "NEW", "IN_PROGRESS"}
    error = {"ERROR", "INVALID_STRUCTURE", "MISSING", "CANCELLED"}
    conflict = {"CONFLICT", "OPEN"}
    if status in ok:
        return SUCCESS
    if status in error:
        return DANGER
    if status in conflict:
        return WARNING
    if status in pending:
        return INFO
    return NEUTRAL


STATUS_LABELS = {
    "DISCOVERED": "Đã phát hiện",
    "INVALID_STRUCTURE": "Sai cấu trúc",
    "WAITING_STABLE": "Chờ tệp ổn định",
    "COPYING": "Đang sao lưu",
    "HASH_PENDING": "Chờ kiểm tra toàn vẹn",
    "LOCKED": "Đã sao lưu an toàn",
    "ALREADY_EXISTS": "Đã tồn tại an toàn",
    "CONFLICT": "Tệp khác nội dung",
    "ERROR": "Có lỗi",
    "EXPECTED": "Đang chờ",
    "MATCHED": "Đã tìm thấy bản sao lưu",
    "MISSING": "Chưa tìm thấy bản sao lưu",
    "NEW": "Mới",
    "IN_PROGRESS": "Đang thực hiện",
    "COMPLETED": "Đã hoàn thành",
    "CANCELLED": "Đã hủy",
    "PENDING": "Đang chờ xử lý",
    "RUNNING": "Đang xử lý",
    "SUCCEEDED": "Hoàn tất",
    "PARTIAL": "Hoàn tất một phần",
    "FAILED": "Thất bại",
}

LEVEL_LABELS = {
    "YEAR4": "Năm 4 số",
    "ENUM": "Danh sách lựa chọn",
    "INTEGER": "Số nguyên",
    "TEXT": "Văn bản",
}

PRIORITY_LABELS = {
    "LOW": "Thấp", "NORMAL": "Bình thường", "HIGH": "Cao", "URGENT": "Khẩn",
}


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)
