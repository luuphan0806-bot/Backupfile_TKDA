from __future__ import annotations

import flet as ft

from ....models import DirectoryLevel
from ...theme import LEVEL_LABELS


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

    if not levels:
        return ft.Column(
            expand=True,
            spacing=12,
            controls=[
                ft.Text(
                    "Chưa có cây thư mục cho dự án. Vào Cấu hình > Dự án & cây thư mục để tạo các cấp trước.",
                    color=ft.Colors.ON_SURFACE_VARIANT,
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

    def add_value(_event) -> None:
        try:
            clean = _validate_value(selected_level, value_field.value or "")
        except ValueError as exc:
            error_text.value = str(exc)
            ctx.page.update()
            return
        if clean in selected_level.allowed_values:
            error_text.value = "Giá trị này đã tồn tại."
            ctx.page.update()
            return
        next_levels = list(levels)
        values = [*selected_level.allowed_values, clean]
        next_levels[selected_index] = DirectoryLevel(
            selected_level.id,
            selected_level.project_id,
            selected_level.position,
            selected_level.display_name,
            selected_level.validation_type,
            values,
        )
        save_levels(next_levels)

    def delete_value(value: str) -> None:
        next_levels = list(levels)
        values = [item for item in selected_level.allowed_values if item != value]
        next_levels[selected_index] = DirectoryLevel(
            selected_level.id,
            selected_level.project_id,
            selected_level.position,
            selected_level.display_name,
            selected_level.validation_type,
            values,
        )
        save_levels(next_levels)

    value_field = ft.TextField(
        label=f"Thêm giá trị cho {selected_level.display_name}",
        width=300,
        dense=True,
        on_submit=add_value,
    )

    level_buttons: list[ft.Control] = []
    for index, level in enumerate(levels):
        label = f"{index + 1}. {level.display_name}"
        button_type = ft.FilledButton if index == selected_index else ft.OutlinedButton
        level_buttons.append(
            button_type(
                label,
                icon=ft.Icons.VIEW_COLUMN_OUTLINED,
                on_click=lambda _event, selected=index: select_level(selected),
            )
        )

    summary_columns = [
        ft.DataColumn(ft.Text("#")),
        ft.DataColumn(ft.Text("Cấp thư mục")),
        ft.DataColumn(ft.Text("Kiểu")),
        ft.DataColumn(ft.Text("Số danh mục")),
    ]
    summary_rows = [
        ft.DataRow(
            selected=index == selected_index,
            on_select_changed=lambda _selected, selected=index: select_level(selected),
            cells=[
                ft.DataCell(ft.Text(str(index + 1))),
                ft.DataCell(ft.Text(level.display_name, weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(LEVEL_LABELS.get(level.validation_type, level.validation_type))),
                ft.DataCell(ft.Text(str(len(level.allowed_values)))),
            ],
        )
        for index, level in enumerate(levels)
    ]

    value_rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(index + 1))),
                ft.DataCell(ft.Text(value)),
                ft.DataCell(
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        tooltip="Xóa giá trị",
                        on_click=lambda _event, current=value: delete_value(current),
                    )
                ),
            ],
        )
        for index, value in enumerate(selected_level.allowed_values)
    ]

    values_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("#")),
            ft.DataColumn(ft.Text(selected_level.display_name)),
            ft.DataColumn(ft.Text("")),
        ],
        rows=value_rows,
    )

    selected_panel = ft.Container(
        padding=16,
        border_radius=8,
        bgcolor=ft.Colors.SURFACE,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        content=ft.Column(
            spacing=12,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Column(
                            spacing=2,
                            controls=[
                                ft.Text(selected_level.display_name, size=16, weight=ft.FontWeight.BOLD),
                                ft.Text(
                                    LEVEL_LABELS.get(selected_level.validation_type, selected_level.validation_type),
                                    size=12,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                ),
                            ],
                        ),
                    ],
                ),
                ft.Row(
                    wrap=True,
                    controls=[
                        value_field,
                        ft.FilledButton("Thêm danh mục", icon=ft.Icons.ADD, on_click=add_value),
                    ],
                ),
                error_text,
                values_table if value_rows else ft.Text(
                    "Chưa có giá trị danh mục cho cấp này.",
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ],
        ),
    )

    return ft.Column(
        expand=True,
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text(
                "Quản lý danh mục hiển thị theo từng cấp trong cây thư mục của dự án. "
                "Mỗi cấp tương ứng một cột hồ sơ; bấm vào cấp để tạo hoặc xóa giá trị danh mục.",
                size=13,
                color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            ft.Row(spacing=8, wrap=True, controls=level_buttons),
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Container(
                        expand=1,
                        content=ft.DataTable(columns=summary_columns, rows=summary_rows),
                    ),
                    ft.Container(width=24),
                    ft.Container(expand=2, content=selected_panel),
                ],
            ),
        ],
    )
