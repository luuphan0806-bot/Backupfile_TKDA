from __future__ import annotations

import flet as ft

# ---------------------------------------------------------------------------
# Cyan cyberpunk design system -- dark only.
#
# The whole app renders on one deep-space plane with electric-cyan accents.
# Every hue below was picked for an "hologram on deep space" mood and the four
# status hues were verified (not eyeballed) with the dataviz palette validator:
# dark-mode lightness band (OKLCH L 0.48-0.67), chroma floor (>= 0.10), CVD
# separation (all-pairs Machado-2009 ΔE >= 12), and >= 3:1 contrast on the dark
# (#05070D) surface.
# ---------------------------------------------------------------------------

PRIMARY = "#3D5AFE"          # legacy light seed (kept for reference)
PRIMARY_DARK = "#22E1FF"     # THE cyan glow accent -- primary throughout
ACCENT = "#8B6CFF"           # neon violet, for gradients/hero accents
ACCENT_2 = "#FF4D9D"         # neon magenta, sparing secondary accent

# Deep-space surface stack
BG_BASE = "#05070D"          # near-black cool -- the base plane
BG_GRADIENT_TOP = "#0B1226"  # top-left glow of the background gradient
SURFACE = "#0C0F1A"          # cards / panels
SURFACE_HIGH = "#141A2B"     # elevated cards / dialogs / hover
SURFACE_INPUT = "#0A0E19"    # text field / dropdown fill

# Text
TEXT_PRIMARY = "#E7EEFB"     # near-white, cool
TEXT_MUTED = "#8B94A7"       # secondary / captions

# Status (validated)
SUCCESS = "#0C9663"
WARNING = "#C08313"
DANGER = "#FF3B5C"
INFO = "#4C8DFF"
NEUTRAL = "#8B94A7"

# Hairlines / glows built from the cyan accent
LINE = ft.Colors.with_opacity(0.20, PRIMARY_DARK)
LINE_STRONG = ft.Colors.with_opacity(0.55, PRIMARY_DARK)
GLOW_CYAN = ft.Colors.with_opacity(0.35, PRIMARY_DARK)


def background_gradient() -> ft.LinearGradient:
    """The deep-space plane every full-screen surface sits on."""
    return ft.LinearGradient(
        begin=ft.Alignment.TOP_LEFT,
        end=ft.Alignment.BOTTOM_RIGHT,
        colors=[BG_GRADIENT_TOP, BG_BASE, BG_BASE],
        stops=[0.0, 0.55, 1.0],
    )


def content_switcher(initial: ft.Control | None = None) -> ft.Container:
    """Plain content host used for screen swaps without transition animation."""
    return ft.Container(
        content=initial or ft.Container(),
        expand=True,
    )


def scrollable_table(table: ft.Control) -> ft.Control:
    """Wrap a wide DataTable so it scrolls horizontally instead of
    overflowing (and visually overlapping) neighbouring content on narrow
    windows. `kit.table_frame` is the styled superset used for primary tables;
    this stays as the minimal wrapper for tables already inside a card."""
    return ft.Row(
        controls=[table],
        scroll=ft.ScrollMode.AUTO,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


def build_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme_seed=PRIMARY_DARK,
        font_family="Segoe UI",
        visual_density=ft.VisualDensity.COMPACT,
    )


def apply_theme(page: ft.Page) -> None:
    """Dark-only cyberpunk theme. No light variant."""
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = build_theme()
    page.dark_theme = build_theme()
    page.padding = 0
    page.bgcolor = BG_BASE


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
