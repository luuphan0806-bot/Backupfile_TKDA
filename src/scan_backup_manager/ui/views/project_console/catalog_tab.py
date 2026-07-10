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

    def clone_level(
        level: DirectoryLevel,
        *,
        allowed_values: list[str] | None = None,
        show_in_mapfile: bool | None = None,
        mapfile_position: int | None = None,
        require_catalog_selection: bool | None = None,
    ) -> DirectoryLevel:
        return DirectoryLevel(
            level.id,
            level.project_id,
            level.position,
            level.display_name,
            level.validation_type,
            list(level.allowed_values if allowed_values is None else allowed_values),
            level.show_in_mapfile if show_in_mapfile is None else show_in_mapfile,
            level.mapfile_position if mapfile_position is None else mapfile_position,
            (
                level.require_catalog_selection
                if require_catalog_selection is None
                else require_catalog_selection
            ),
        )

    def normalize_mapfile_positions(next_levels: list[DirectoryLevel]) -> list[DirectoryLevel]:
        ordered = sorted(
            next_levels,
            key=lambda item: (int(item.mapfile_position or item.position), item.position),
        )
        positions = {id(level): index for index, level in enumerate(ordered, start=1)}
        return [
            clone_level(level, mapfile_position=positions[id(level)])
            for level in next_levels
        ]

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
        next_levels[selected_index] = clone_level(selected_level, allowed_values=values)
        error_text.value = ""
        status_text.value = f"Đã lưu {len(values)} giá trị cho {selected_level.display_name}."
        save_levels(next_levels)

    def update_mapfile_visibility(level_index: int, value: bool) -> None:
        next_levels = list(levels)
        next_levels[level_index] = clone_level(next_levels[level_index], show_in_mapfile=value)
        save_levels(normalize_mapfile_positions(next_levels))

    def update_catalog_requirement(level_index: int, value: bool) -> None:
        next_levels = list(levels)
        next_levels[level_index] = clone_level(
            next_levels[level_index],
            require_catalog_selection=value,
        )
        save_levels(next_levels)

    def move_mapfile_level(level_index: int, delta: int) -> None:
        ordered_indices = sorted(
            range(len(levels)),
            key=lambda index: (
                int(levels[index].mapfile_position or levels[index].position),
                levels[index].position,
            ),
        )
        current_order_index = ordered_indices.index(level_index)
        target_order_index = current_order_index + delta
        if target_order_index < 0 or target_order_index >= len(ordered_indices):
            return
        ordered_indices[current_order_index], ordered_indices[target_order_index] = (
            ordered_indices[target_order_index],
            ordered_indices[current_order_index],
        )
        position_by_index = {
            index: order
            for order, index in enumerate(ordered_indices, start=1)
        }
        next_levels = [
            clone_level(level, mapfile_position=position_by_index[index])
            for index, level in enumerate(levels)
        ]
        state["selected_index"] = level_index
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

    sorted_level_indices = sorted(
        range(len(levels)),
        key=lambda index: (
            int(levels[index].mapfile_position or levels[index].position),
            levels[index].position,
        ),
    )
    order_by_index = {index: order for order, index in enumerate(sorted_level_indices, start=1)}
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
                            ft.Text(
                                f"Mapfile: thứ tự {order_by_index[index]}",
                                size=11,
                                color=TEXT_MUTED,
                            ),
                            ft.Text(
                                "Bắt buộc chọn danh mục"
                                if level.require_catalog_selection
                                else "Cho phép nhập tự do",
                                size=11,
                                color=TEXT_MUTED,
                            ),
                        ],
                    ),
                    ft.Row(
                        spacing=2,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Checkbox(
                                value=level.show_in_mapfile,
                                tooltip="Hiển thị cấp này trong Mapfile hệ thống",
                                on_change=lambda event, i=index: update_mapfile_visibility(
                                    i,
                                    bool(event.control.value),
                                ),
                            ),
                            ft.Checkbox(
                                value=level.require_catalog_selection,
                                tooltip="Bắt buộc tạo hồ sơ từ danh sách danh mục",
                                on_change=lambda event, i=index: update_catalog_requirement(
                                    i,
                                    bool(event.control.value),
                                ),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.ARROW_UPWARD,
                                icon_size=16,
                                tooltip="Đưa lên trong Mapfile",
                                disabled=order_by_index[index] <= 1,
                                on_click=lambda _event, i=index: move_mapfile_level(i, -1),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.ARROW_DOWNWARD,
                                icon_size=16,
                                tooltip="Đưa xuống trong Mapfile",
                                disabled=order_by_index[index] >= len(levels),
                                on_click=lambda _event, i=index: move_mapfile_level(i, 1),
                            ),
                            kit.badge(str(len(level.allowed_values)), ft.Colors.PRIMARY),
                        ],
                    ),
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
                        ft.Row(
                            spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Text(f"{len(selected_level.allowed_values)} giá trị", color=TEXT_MUTED),
                                ft.Checkbox(
                                    label="Hiển thị trong Mapfile hệ thống",
                                    value=selected_level.show_in_mapfile,
                                    on_change=lambda event: update_mapfile_visibility(
                                        selected_index,
                                        bool(event.control.value),
                                    ),
                                ),
                                ft.Checkbox(
                                    label="Bắt buộc chọn từ danh mục khi tạo việc",
                                    value=selected_level.require_catalog_selection,
                                    on_change=lambda event: update_catalog_requirement(
                                        selected_index,
                                        bool(event.control.value),
                                    ),
                                ),
                            ],
                        ),
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
                "Mỗi cấp tương ứng một cột hồ sơ; tích chọn để đưa cấp đó vào phần cột động của Mapfile hệ thống.",
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
