from __future__ import annotations

import flet as ft

from ....models import DirectoryLevel
from ... import kit
from ...theme import LEVEL_LABELS, TEXT_MUTED


def _normalize_value(level: DirectoryLevel, value: str) -> str:
    clean = value.strip()
    if level.validation_type in {"ENUM", "YEAR4", "INTEGER"}:
        clean = clean.upper()
    return clean


def _validate_value(level: DirectoryLevel, value: str) -> str:
    clean = _normalize_value(level, value)
    if not clean:
        raise ValueError("Cần nhập giá trị danh mục.")
    if level.validation_type == "YEAR4" and not (clean.isdigit() and len(clean) == 4):
        raise ValueError("Cấp năm cần nhập đúng 4 chữ số.")
    if level.validation_type == "INTEGER" and not clean.isdigit():
        raise ValueError("Cấp số chỉ nhận chữ số.")
    return clean


def build(ctx) -> ft.Control:
    db = ctx.db
    state = ctx.view_state.setdefault("catalog", {"selected_index": 0})
    levels = db.list_directory_levels(ctx.project_id)
    error_text = ft.Text("", color=ft.Colors.ERROR)
    status_text = ft.Text("", color=ft.Colors.PRIMARY)

    if not levels:
        return ft.Column(
            expand=True,
            spacing=12,
            controls=[
                ft.Text(
                    "Chưa có cây thư mục cho dự án. Vào Cấu hình > Dự án & cây thư mục để tạo các cấp trước.",
                    color=TEXT_MUTED,
                )
            ],
        )

    selected_index = min(int(state.get("selected_index", 0)), len(levels) - 1)
    state["selected_index"] = selected_index
    selected_level = levels[selected_index]

    def save_levels(next_levels: list[DirectoryLevel]) -> None:
        db.save_directory_levels(ctx.project_id, next_levels)
        ctx.refresh()

    def select_level(index: int) -> None:
        state["selected_index"] = index
        ctx.refresh()

    def parse_values(raw: str) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if not line.strip():
                continue
            clean = _validate_value(selected_level, line)
            if clean in seen:
                continue
            seen.add(clean)
            values.append(clean)
        return values

    def save_values(_event=None) -> None:
        try:
            values = parse_values(values_field.value or "")
        except ValueError as exc:
            error_text.value = str(exc)
            status_text.value = ""
            ctx.page.update()
            return
        if not values:
            error_text.value = "Cần nhập ít nhất một giá trị danh mục."
            status_text.value = ""
            ctx.page.update()
            return
        next_levels = list(levels)
        next_levels[selected_index] = DirectoryLevel(
            selected_level.id,
            selected_level.project_id,
            selected_level.position,
            selected_level.display_name,
            selected_level.validation_type,
            values,
        )
        error_text.value = ""
        status_text.value = f"Đã lưu {len(values)} giá trị cho {selected_level.display_name}."
        save_levels(next_levels)

    values_field = ft.TextField(
        label=f"Giá trị của {selected_level.display_name}",
        value="\n".join(selected_level.allowed_values),
        multiline=True,
        min_lines=14,
        max_lines=24,
        expand=True,
        hint_text="Dán từ Excel: mỗi giá trị một dòng",
    )

    level_cards = [
        ft.Container(
            padding=12,
            border_radius=8,
            bgcolor=ft.Colors.with_opacity(
                0.14 if index == selected_index else 0.04, ft.Colors.PRIMARY
            ),
            border=ft.Border.all(
                1,
                ft.Colors.with_opacity(
                    0.55 if index == selected_index else 0.18, ft.Colors.PRIMARY
                ),
            ),
            on_click=lambda _event, selected=index: select_level(selected),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Column(
                        spacing=2,
                        controls=[
                            ft.Text(level.display_name, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                LEVEL_LABELS.get(level.validation_type, level.validation_type),
                                size=12,
                                color=TEXT_MUTED,
                            ),
                        ],
                    ),
                    kit.badge(str(len(level.allowed_values)), ft.Colors.PRIMARY),
                ],
            ),
        )
        for index, level in enumerate(levels)
    ]

    level_list = kit.section(
        "Danh sách các loại danh mục",
        "Chọn một loại để sửa danh sách giá trị",
        ft.Column(spacing=8, controls=level_cards),
        icon=ft.Icons.VIEW_LIST_OUTLINED,
    )

    selected_panel = kit.section(
        selected_level.display_name,
        LEVEL_LABELS.get(selected_level.validation_type, selected_level.validation_type),
        ft.Column(
            spacing=12,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(f"{len(selected_level.allowed_values)} giá trị", color=TEXT_MUTED),
                        kit.primary_button("Lưu danh mục", icon=ft.Icons.SAVE, on_click=save_values),
                    ],
                ),
                values_field,
                error_text,
                status_text,
            ],
        ),
        icon=ft.Icons.LABEL_OUTLINE,
    )

    return ft.Column(
        expand=True,
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text(
                "Quản lý danh mục hiển thị theo từng cấp trong cây thư mục của dự án. "
                "Mỗi cấp tương ứng một cột hồ sơ; bấm vào cấp để sửa nhanh danh sách giá trị.",
                size=13,
                color=TEXT_MUTED,
            ),
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Container(expand=1, content=level_list),
                    ft.Container(expand=2, content=selected_panel),
                ],
            ),
        ],
    )
