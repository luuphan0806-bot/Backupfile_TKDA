from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import flet as ft

from ....models import ProjectTask
from ... import kit
from ...date_format import DISPLAY_DATE_HINT, display_to_iso, iso_to_display
from ...theme import DANGER, INFO, LINE, SUCCESS, WARNING, TEXT_MUTED


DEFAULT_PAGE_SIZE = 50
PAGE_SIZE_OPTIONS = [25, 50, 100]
PAPER_CELL_WIDTH = 320
# Scan cells use borderless inline fields: name+date share one line, page/file metrics the next.
# Keep the row compact, but tall enough for both editable lines plus save icon.
PAPER_FIELD_HEIGHT = 32
PAPER_TABLE_ROW_HEIGHT = 116
PAPER_SAVE_BUTTON_SIZE = PAPER_FIELD_HEIGHT
SYSTEM_TABLE_MIN_WIDTH = 1560
# One accent color per data column, so a column can be told apart from its
# neighbors at a glance (header tint, cell background, metric chips).
COLUMN_ACCENT_COLORS = {
    "A4": "#2563EB",
    "A3": "#B45309",
    "A0": "#059669",
    "check": "#7C3AED",
}
# Kept as an alias: still referenced where the accent is specifically about
# the paper-format scan cells rather than a column in general.
SCAN_FILE_COLORS = COLUMN_ACCENT_COLORS
SCAN_PAGE_COLOR = "#0891B2"
DEFAULT_COLUMN_ACCENT = "#64748B"

RECORD_STATUS_LABELS = {
    "NOT_STARTED": "Chưa thực hiện",
    "SCANNING": "Đang scan",
    "PENDING_PAPER": "Chờ scan khổ khác",
    "PENDING_CHECK": "Chờ check",
    "COMPLETED": "Hoàn thành",
    "RESCAN_REQUIRED": "Cần scan lại",
}
BACKUP_STATUS_LABELS = {
    "NOT_BACKED_UP": "Chưa backup",
    "BACKED_UP": "Đã backup",
    "IN_PROGRESS": "Đang xử lý",
    "CONFLICT": "Xung đột",
    "ERROR": "Lỗi",
}
BACKUP_STATUS_COLORS = {
    "NOT_BACKED_UP": "#9CA3AF",
    "BACKED_UP": SUCCESS,
    "IN_PROGRESS": INFO,
    "CONFLICT": WARNING,
    "ERROR": DANGER,
}


def build(ctx) -> ft.Control:
    state = ctx.view_state.setdefault(
        "system_mapfile",
        {"search": "", "page": 0},
    )
    state.setdefault("flash", "")
    state.setdefault("selected_records", set())
    state.setdefault("clipboard_records", [])
    state.setdefault("filters", {})
    state.setdefault("page_size", DEFAULT_PAGE_SIZE)
    state.setdefault("column_weights", {})
    state.setdefault("column_widths", {})
    if not isinstance(state["selected_records"], set):
        state["selected_records"] = set(state["selected_records"])
    if int(state.get("page_size", DEFAULT_PAGE_SIZE)) not in PAGE_SIZE_OPTIONS:
        state["page_size"] = DEFAULT_PAGE_SIZE
    if not isinstance(state.get("column_weights"), dict):
        state["column_weights"] = {}
    if not isinstance(state.get("column_widths"), dict):
        state["column_widths"] = {}
    page_size = int(state["page_size"])
    status_banner = ft.Text(state.get("flash", ""), color=ft.Colors.PRIMARY)
    search_field = ft.TextField(
        label="Tìm theo hồ sơ, máy trạm hoặc đường dẫn",
        value=state["search"],
        width=360,
        dense=True,
    )
    filters = state["filters"]

    def apply_search(_event=None) -> None:
        state["search"] = (search_field.value or "").strip()
        state["page"] = 0
        ctx.refresh()

    def clear_search(_event) -> None:
        state["search"] = ""
        state["page"] = 0
        ctx.refresh()

    def apply_filters(_event=None) -> None:
        state["filters"] = {
            "record_key": (record_key_filter.value or "").strip(),
            "client_code": (client_filter.value or "").strip(),
            "record_status": record_status_filter.value or "",
            "backup_status": backup_status_filter.value or "",
            **{
                key: (field.value or "").strip()
                for key, field in level_filter_fields
            },
        }
        state["page"] = 0
        ctx.refresh()

    def clear_filters(_event=None) -> None:
        state["filters"] = {}
        state["page"] = 0
        ctx.refresh()

    def change_page(delta: int) -> None:
        state["page"] = max(0, int(state["page"]) + delta)
        ctx.refresh()

    def change_page_size(event) -> None:
        state["page_size"] = int(event.control.value or DEFAULT_PAGE_SIZE)
        state["page"] = 0
        ctx.refresh()

    def optional_personnel_id(value: str | None) -> int | None:
        return int(value) if value else None

    def save_inline(record: dict, mutator, *, message: str) -> bool:
        workflow = ctx.db.get_record_workflow(ctx.project_id, record["record_key"])
        values = {
            "scanner_id": workflow.get("scanner_id"),
            "scan_date": workflow.get("scan_date", ""),
            "checker_id": workflow.get("checker_id"),
            "check_date": workflow.get("check_date", ""),
            "check_pages": workflow.get("check_pages", 0),
            "check_files": workflow.get("check_files", 0),
            "record_status": workflow.get("record_status", "NOT_STARTED"),
            "notes": workflow.get("notes", ""),
            "paper_statuses": [
                {
                    "paper_format_id": paper["paper_format_id"],
                    "scanner_id": paper.get("scanner_id"),
                    "scan_date": paper.get("scan_date", ""),
                    "scan_status": paper["scan_status"],
                    "scan_pages": str(paper["scan_pages"]),
                    "scan_files": str(paper.get("scan_files", 0)),
                    "check_pages": str(paper["check_pages"]),
                    "notes": paper["notes"],
                }
                for paper in workflow["paper_statuses"]
            ],
        }
        mutator(values)
        try:
            ctx.db.save_record_workflow(
                project_id=ctx.project_id,
                record_key=record["record_key"],
                scanner_id=values["scanner_id"],
                scan_date=values["scan_date"],
                checker_id=values["checker_id"],
                check_date=values["check_date"],
                check_pages=values["check_pages"],
                check_files=values["check_files"],
                record_status=values["record_status"],
                notes=values["notes"],
                paper_statuses=values["paper_statuses"],
            )
        except ValueError as exc:
            status_banner.value = str(exc)
            status_banner.color = ft.Colors.ERROR
            ctx.page.update()
            return False
        # Update the flash message in place instead of ctx.refresh(): a full
        # refresh re-queries the page of records and rebuilds every row's
        # dropdowns from scratch, which made every single-cell save feel like
        # it was reloading the whole table. The edited control already shows
        # its new value (the user just set it), so only the status banner
        # needs to change.
        state["flash"] = message
        status_banner.value = message
        status_banner.color = ft.Colors.PRIMARY
        ctx.page.update()
        return True

    def record_status_cell(record: dict) -> ft.DataCell:
        control = ft.Dropdown(
            dense=True,
            width=170,
            value=record["record_status"],
            options=[
                ft.dropdown.Option(key=key, text=label)
                for key, label in RECORD_STATUS_LABELS.items()
            ],
        )
        control.on_change = lambda event: save_inline(
            record,
            lambda values: values.__setitem__(
                "record_status", event.control.value or "NOT_STARTED"
            ),
            message=f"Đã lưu trạng thái {record['record_key']}.",
        )
        return ft.DataCell(
            ft.Container(expand=True, alignment=ft.Alignment.CENTER, content=control),
            expand=column_weight("record_status"),
        )

    def open_folder(record: dict) -> None:
        try:
            destination = Path(record["sample_dest_path"])
            folder = destination.parent
            if not folder.exists():
                raise FileNotFoundError(f"Thư mục không tồn tại: {folder}")
            os.startfile(str(folder))
        except (OSError, TypeError) as exc:
            status_banner.value = f"Không thể mở thư mục: {exc}"
            status_banner.color = ft.Colors.ERROR
            ctx.page.update()

    search_field.on_submit = apply_search
    page_index = int(state["page"])
    directory_levels = ctx.db.list_directory_levels(ctx.project_id)
    mapfile_levels = sorted(
        [level for level in directory_levels if level.show_in_mapfile],
        key=lambda level: (int(level.mapfile_position or level.position), level.position),
    )
    record_key_filter = ft.TextField(
        label="Lọc mã hồ sơ",
        value=filters.get("record_key", ""),
        width=170,
        dense=True,
    )
    client_filter = ft.TextField(
        label="Lọc máy lưu",
        value=filters.get("client_code", ""),
        width=150,
        dense=True,
    )
    record_status_filter = ft.Dropdown(
        label="Trạng thái hồ sơ",
        dense=True,
        width=180,
        value=filters.get("record_status", ""),
        options=[
            ft.dropdown.Option(key="", text="Tất cả"),
            *[
                ft.dropdown.Option(key=key, text=label)
                for key, label in RECORD_STATUS_LABELS.items()
            ],
        ],
    )
    backup_status_filter = ft.Dropdown(
        label="Backup",
        dense=True,
        width=160,
        value=filters.get("backup_status", ""),
        options=[
            ft.dropdown.Option(key="", text="Tất cả"),
            *[
                ft.dropdown.Option(key=key, text=label)
                for key, label in BACKUP_STATUS_LABELS.items()
            ],
        ],
    )
    level_filter_fields = [
        (
            f"level_{level.position}",
            ft.TextField(
                label=f"Lọc {level.display_name}",
                value=filters.get(f"level_{level.position}", ""),
                width=150,
                dense=True,
            ),
        )
        for level in mapfile_levels
    ]
    for field in [record_key_filter, client_filter, *[field for _key, field in level_filter_fields]]:
        field.on_submit = apply_filters
    records, total_rows = ctx.db.list_system_records_page(
        ctx.project_id,
        limit=page_size,
        offset=page_index * page_size,
        search=state["search"],
        filters=filters,
    )
    paper_formats = ctx.db.list_paper_formats(ctx.project_id, enabled_only=True)
    records_summary = ctx.db.get_system_records_summary(
        ctx.project_id, search=state["search"], filters=filters
    )

    def level_part_value(record_key: str, level) -> str:
        record_parts = record_key.replace("\\", "/").split("/")
        part_index = max(0, int(level.position) - 1)
        value = record_parts[part_index] if part_index < len(record_parts) else "—"
        if part_index == len(directory_levels) - 1 and len(record_parts) > len(directory_levels):
            value = "/".join(record_parts[part_index:])
        return value

    personnel = ctx.db.list_personnel(ctx.project_id, enabled_only=True)
    clients = ctx.db.list_clients(ctx.project_id)
    job_types = ctx.db.list_job_types(ctx.project_id, enabled_only=True)
    personnel_names = {
        str(person.id): person.full_name
        for person in personnel
        if person.id is not None
    }

    def personnel_name(person_id: str) -> str:
        return personnel_names.get(person_id, "")

    def visible_table_width() -> float:
        page_width = float(getattr(ctx.page, "width", 0) or 0)
        window_width = float(getattr(ctx.page.window, "width", 1360) or 1360)
        available_width = max(page_width, window_width)
        sidebar_width = 72
        content_padding = 48
        table_frame_padding = 16
        return max(
            SYSTEM_TABLE_MIN_WIDTH,
            available_width - sidebar_width - content_padding - table_frame_padding,
        )

    default_column_weights: dict[str, int] = {
        "stt": 1,
        "check": 6,
        "record_status": 4,
        "backup_status": 3,
        "client_codes": 3,
        "actions": 2,
    }
    for level in mapfile_levels:
        default_column_weights[f"level_{level.position}"] = 2
    if not directory_levels:
        default_column_weights["record_key"] = 4
    for paper_format in paper_formats:
        default_column_weights[f"scan_{paper_format.code}"] = 6
    column_weights = state["column_weights"]
    for key, value in default_column_weights.items():
        column_weights.setdefault(key, value)

    def column_weight(key: str) -> int:
        return max(1, int(column_weights.get(key, default_column_weights.get(key, 1))))

    column_widths = state["column_widths"]
    min_column_widths = {
        "stt": 64,
        "record_status": 170,
        "backup_status": 150,
        "client_codes": 150,
        "actions": 92,
        "check": 250,
    }
    for level in mapfile_levels:
        min_column_widths[f"level_{level.position}"] = 120
    if not directory_levels:
        min_column_widths["record_key"] = 220
    for paper_format in paper_formats:
        min_column_widths[f"scan_{paper_format.code}"] = 280

    def reset_column_widths() -> None:
        table_width = visible_table_width()
        spacing = 12 * max(0, len(default_column_weights) - 1) + 16
        usable_width = max(600, table_width - spacing)
        total_weight = sum(column_weight(key) for key in default_column_weights)
        column_widths.clear()
        for key in default_column_weights:
            weighted_width = usable_width * column_weight(key) / total_weight
            column_widths[key] = max(
                min_column_widths.get(key, 100),
                int(weighted_width),
            )

    expected_width_keys = set(default_column_weights)
    if set(column_widths) != expected_width_keys:
        reset_column_widths()

    def column_width(key: str) -> int:
        return max(
            min_column_widths.get(key, 100),
            int(column_widths.get(key, min_column_widths.get(key, 100))),
        )

    def actual_table_width() -> int:
        content_width = sum(column_width(key) for key in default_column_weights)
        spacing = 12 * max(0, len(default_column_weights) - 1) + 16
        return max(int(visible_table_width()), content_width + spacing)

    def resize_columns(left_key: str, right_key: str | None, delta: float) -> None:
        if not right_key or abs(delta) < 1:
            return
        left = column_width(left_key)
        right = column_width(right_key)
        left_min = min_column_widths.get(left_key, 100)
        right_min = min_column_widths.get(right_key, 100)
        movement = int(delta)
        if movement > 0:
            movement = min(movement, right - right_min)
        else:
            movement = -min(abs(movement), left - left_min)
        if movement == 0:
            return
        column_widths[left_key] = left + movement
        column_widths[right_key] = right - movement
        ctx.refresh()

    def drag_delta(event) -> float:
        for attr in ("primary_delta", "delta_x"):
            value = getattr(event, attr, None)
            if value is not None:
                return float(value or 0)
        for attr in ("local_delta", "global_delta"):
            value = getattr(event, attr, None)
            if value is not None and hasattr(value, "x"):
                return float(value.x or 0)
        return 0.0

    def header(
        label: str,
        key: str,
        next_key: str | None = None,
        *,
        subtitle: str | None = None,
        accent: str | None = None,
    ) -> ft.Control:
        title_column: list[ft.Control] = [
            ft.Text(
                label,
                text_align=ft.TextAlign.CENTER,
                size=12,
                weight=ft.FontWeight.W_600,
                tooltip=label,
            )
        ]
        if subtitle:
            title_column.append(
                ft.Text(
                    subtitle,
                    text_align=ft.TextAlign.CENTER,
                    size=10,
                    weight=ft.FontWeight.W_500,
                    color=accent or TEXT_MUTED,
                )
            )
        controls: list[ft.Control] = [
            ft.Container(
                expand=True,
                alignment=ft.Alignment.CENTER,
                padding=ft.Padding.symmetric(horizontal=4, vertical=0),
                content=ft.Column(
                    spacing=1,
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=title_column,
                ),
            )
        ]
        if next_key:
            controls.append(
                ft.GestureDetector(
                    width=18,
                    height=38,
                    mouse_cursor=ft.MouseCursor.RESIZE_COLUMN,
                    drag_interval=24,
                    on_horizontal_drag_update=lambda event, left=key, right=next_key: resize_columns(
                        left,
                        right,
                        drag_delta(event),
                    ),
                    content=ft.Container(
                        alignment=ft.Alignment.CENTER,
                        content=ft.Container(
                            width=2,
                            height=24,
                            border_radius=1,
                            bgcolor=ft.Colors.with_opacity(0.22, ft.Colors.PRIMARY),
                        ),
                    ),
                    tooltip="Kéo để đổi độ rộng cột",
                )
            )
        return ft.Row(
            spacing=0,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=controls,
        )

    def col(
        label: str,
        key: str,
        *,
        next_key: str | None = None,
        numeric: bool = False,
        subtitle: str | None = None,
        accent: str | None = None,
    ) -> ft.DataColumn:
        return ft.DataColumn(
            ft.Container(
                width=column_width(key),
                height=44,
                border_radius=6,
                bgcolor=ft.Colors.with_opacity(0.12, accent) if accent else None,
                content=header(label, key, next_key, subtitle=subtitle, accent=accent),
            ),
            numeric=numeric,
            heading_row_alignment=ft.MainAxisAlignment.CENTER,
        )

    def cell(content: ft.Control | str, *, key: str) -> ft.DataCell:
        if isinstance(content, str):
            content = ft.Text(content, text_align=ft.TextAlign.CENTER)
        return ft.DataCell(
            ft.Container(
                width=column_width(key),
                alignment=ft.Alignment.CENTER,
                content=content,
            ),
        )

    def selected_record_keys() -> list[str]:
        selected = state["selected_records"]
        return [record["record_key"] for record in records if record["record_key"] in selected]

    def workflow_payload(record_key: str) -> dict:
        workflow = ctx.db.get_record_workflow(ctx.project_id, record_key)
        return {
            "scanner_id": workflow.get("scanner_id"),
            "scan_date": workflow.get("scan_date", ""),
            "checker_id": workflow.get("checker_id"),
            "check_date": workflow.get("check_date", ""),
            "check_pages": workflow.get("check_pages", 0),
            "check_files": workflow.get("check_files", 0),
            "record_status": workflow.get("record_status", "NOT_STARTED"),
            "notes": workflow.get("notes", ""),
            "paper_statuses": [
                {
                    "paper_format_id": paper["paper_format_id"],
                    "scanner_id": paper.get("scanner_id"),
                    "scan_date": paper.get("scan_date", ""),
                    "scan_status": paper["scan_status"],
                    "scan_pages": str(paper["scan_pages"]),
                    "scan_files": str(paper.get("scan_files", 0)),
                    "check_pages": str(paper["check_pages"]),
                    "notes": paper["notes"],
                }
                for paper in workflow["paper_statuses"]
            ],
        }

    def apply_workflow(record_key: str, payload: dict) -> None:
        ctx.db.save_record_workflow(
            project_id=ctx.project_id,
            record_key=record_key,
            scanner_id=payload["scanner_id"],
            scan_date=payload["scan_date"],
            checker_id=payload["checker_id"],
            check_date=payload["check_date"],
            check_pages=payload["check_pages"],
            check_files=payload["check_files"],
            record_status=payload["record_status"],
            notes=payload["notes"],
            paper_statuses=payload["paper_statuses"],
        )

    def copy_selected_rows() -> None:
        keys = selected_record_keys()
        if not keys:
            state["flash"] = "Chưa chọn dòng để sao chép."
            ctx.refresh()
            return
        state["clipboard_records"] = [
            {"record_key": key, "workflow": workflow_payload(key)} for key in keys
        ]
        state["flash"] = f"Đã sao chép {len(keys)} dòng."
        ctx.refresh()

    def paste_copied_rows() -> None:
        copied = state.get("clipboard_records") or []
        if not copied:
            state["flash"] = "Clipboard chưa có dòng để dán."
            ctx.refresh()
            return
        new_keys = []
        try:
            for item in copied:
                new_key = ctx.mapfiles.duplicate_manual_record(
                    ctx.project_id, item["record_key"]
                )
                apply_workflow(new_key, item["workflow"])
                new_keys.append(new_key)
        except ValueError as exc:
            status_banner.value = str(exc)
            status_banner.color = ft.Colors.ERROR
            ctx.page.update()
            return
        state["selected_records"] = set(new_keys)
        state["flash"] = f"Đã dán {len(new_keys)} dòng mới."
        ctx.refresh()

    def fill_down_selected_rows() -> None:
        keys = selected_record_keys()
        if len(keys) < 2:
            state["flash"] = "Chọn ít nhất 2 dòng để dùng Ctrl+D."
            ctx.refresh()
            return
        payload = workflow_payload(keys[0])
        try:
            for key in keys[1:]:
                apply_workflow(key, payload)
        except ValueError as exc:
            status_banner.value = str(exc)
            status_banner.color = ft.Colors.ERROR
            ctx.page.update()
            return
        state["flash"] = f"Đã điền dữ liệu xuống {len(keys) - 1} dòng."
        ctx.refresh()

    def on_keyboard(event: ft.KeyboardEvent) -> None:
        if (
            getattr(ctx.shell, "current_project_id", None) != ctx.project_id
            or getattr(ctx, "tab_index", None) != 2
            or not event.ctrl
        ):
            return
        key = event.key.upper()
        if key == "C":
            copy_selected_rows()
        elif key == "V":
            paste_copied_rows()
        elif key == "D":
            fill_down_selected_rows()

    ctx.page.on_keyboard_event = on_keyboard

    def new_record_keys() -> list[tuple[str, str]]:
        if directory_levels:
            return [
                (f"level_{index}", level.display_name)
                for index, level in enumerate(directory_levels)
            ]
        return [("record_key", "Mã hồ sơ")]

    def task_code_for(record_parts: list[str], job_code: str) -> str:
        raw = "_".join([job_code, *record_parts]).upper()
        clean = "".join(char if char.isalnum() else "_" for char in raw)
        return clean[:80].strip("_") or job_code

    def open_create_job_dialog(_event=None) -> None:
        record_fields = [
            ft.TextField(label=label, dense=True, width=180)
            for _key, label in new_record_keys()
        ]
        job_dropdown = ft.Dropdown(
            label="Tên công việc",
            dense=True,
            width=240,
            value=job_types[0].job_code if job_types else "",
            options=[
                ft.dropdown.Option(key=item.job_code, text=item.display_name)
                for item in job_types
            ],
        )
        personnel_dropdown = ft.Dropdown(
            label="Nhân sự đảm nhiệm",
            dense=True,
            width=260,
            options=[
                ft.dropdown.Option(key=str(person.id), text=person.full_name)
                for person in personnel
                if person.id is not None
            ],
        )
        client_dropdown = ft.Dropdown(
            label="Máy nhân sự đang ngồi",
            dense=True,
            width=260,
            options=[
                ft.dropdown.Option(
                    key=client.client_code,
                    text=f"{client.client_code} - {client.share_path}",
                )
                for client in clients
                if client.enabled
            ],
        )
        error_text = ft.Text("", color=DANGER)

        def submit(_submit_event=None) -> None:
            if directory_levels:
                parts = [(field.value or "").strip() for field in record_fields]
            else:
                raw_key = (record_fields[0].value or "").strip()
                parts = [part for part in raw_key.replace("\\", "/").split("/") if part]
            job_code = job_dropdown.value or ""
            personnel_id = int(personnel_dropdown.value) if personnel_dropdown.value else None
            client_code = (client_dropdown.value or "").strip()
            if not parts or any(not part for part in parts):
                error_text.value = "Cần nhập đầy đủ thông tin hồ sơ."
                ctx.page.update()
                return
            if not job_code:
                error_text.value = "Cần chọn tên công việc."
                ctx.page.update()
                return
            if personnel_id is None:
                error_text.value = "Cần chọn nhân sự đảm nhiệm."
                ctx.page.update()
                return
            if not client_code:
                error_text.value = "Cần chọn máy nhân sự đang ngồi."
                ctx.page.update()
                return
            job_label = next(
                (item.display_name for item in job_types if item.job_code == job_code),
                job_code,
            )
            assignee_name = personnel_name(str(personnel_id))
            try:
                row_id = ctx.mapfiles.add_manual_record(
                    ctx.project_id,
                    parts,
                    file_name="1.pdf",
                    client_code=client_code,
                    workstation_owner=assignee_name,
                    workstation_date=datetime.now().strftime("%d-%m-%Y"),
                    workstation_task=job_label,
                )
                ctx.db.save_task(
                    ProjectTask(
                        None,
                        ctx.project_id,
                        task_code_for(parts, job_code),
                        job_label,
                        f"Thư mục hồ sơ: {'/'.join(parts)}\nMáy trạm: {client_code}\nDòng mapfile: {row_id}",
                        personnel_id,
                        "",
                    )
                )
            except ValueError as exc:
                error_text.value = str(exc)
                ctx.page.update()
                return
            ctx.page.pop_dialog()
            state["flash"] = f"Đã tạo công việc {job_label} và thêm thư mục hồ sơ {'/'.join(parts)}."
            state["page"] = 0
            ctx.refresh()

        dialog = kit.dialog(
            "Tạo công việc và thêm dòng hồ sơ",
            ft.Column(
                spacing=12,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Row(record_fields, wrap=True, spacing=8),
                    ft.Row([job_dropdown, personnel_dropdown, client_dropdown], wrap=True, spacing=8),
                    error_text,
                ],
            ),
            [
                kit.ghost_button("Hủy", on_click=lambda _e: ctx.page.pop_dialog()),
                kit.primary_button("Tạo công việc", icon=ft.Icons.ADD_TASK, on_click=submit),
            ],
            icon=ft.Icons.ADD_TASK,
            width=720,
        )
        ctx.page.show_dialog(dialog)

    def paper_scan_cell(record: dict, paper_format) -> ft.DataCell:
        current = dict(record["paper_statuses"].get(paper_format.code) or {})
        saved = {
            "scanner_id": str(current.get("scanner_id") or ""),
            "scan_date": current.get("scan_date", "") or "",
            "scan_pages": str(current.get("scan_pages", 0) or 0),
            "scan_files": str(current.get("scan_files", 0) or 0),
        }
        def scan_line(icon: str, control: ft.Control) -> ft.Control:
            return ft.Row(
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(icon, size=14, color=TEXT_MUTED),
                    control,
                ],
            )

        scan_column_width = column_width(f"scan_{paper_format.code}")
        field_width = max(170, scan_column_width - 58)
        date_width = 96
        name_width = max(88, field_width - date_width - 10)
        metric_width = max(92, int((field_width - 8) / 2))
        file_color = SCAN_FILE_COLORS.get(paper_format.code, ft.Colors.PRIMARY)
        scanner = ft.Dropdown(
            dense=True,
            width=name_width,
            height=PAPER_FIELD_HEIGHT,
            value=saved["scanner_id"],
            hint_text="Tên",
            tooltip=personnel_name(saved["scanner_id"]) or "Người scan",
            border=ft.InputBorder.NONE,
            text_size=12,
            content_padding=ft.Padding.symmetric(vertical=0, horizontal=0),
            options=[
                ft.dropdown.Option(key="", text="--"),
                *[
                    ft.dropdown.Option(key=str(person.id), text=person.full_name)
                    for person in personnel
                    if person.id is not None
                ],
            ],
        )
        scan_date = ft.TextField(
            value=iso_to_display(saved["scan_date"]),
            dense=True,
            width=date_width,
            height=PAPER_FIELD_HEIGHT,
            hint_text=DISPLAY_DATE_HINT,
            tooltip=f"Ngày thực hiện ({DISPLAY_DATE_HINT})",
            border=ft.InputBorder.NONE,
            text_size=12,
            content_padding=ft.Padding.symmetric(vertical=0, horizontal=0),
        )
        pages = ft.TextField(
            value=saved["scan_pages"],
            dense=True,
            height=22,
            width=max(34, metric_width - 52),
            hint_text="Trang",
            tooltip="Số trang",
            keyboard_type=ft.KeyboardType.NUMBER,
            border=ft.InputBorder.NONE,
            text_size=12,
            color=SCAN_PAGE_COLOR,
            text_align=ft.TextAlign.CENTER,
            content_padding=ft.Padding.symmetric(vertical=0, horizontal=0),
        )
        files = ft.TextField(
            value=saved["scan_files"],
            dense=True,
            height=22,
            width=max(34, metric_width - 44),
            hint_text="File",
            tooltip=f"Số file Scan {paper_format.code}",
            keyboard_type=ft.KeyboardType.NUMBER,
            border=ft.InputBorder.NONE,
            text_size=12,
            color=file_color,
            text_align=ft.TextAlign.CENTER,
            content_padding=ft.Padding.symmetric(vertical=0, horizontal=0),
        )

        def metric_box(label: str, control: ft.Control, color: str) -> ft.Control:
            return ft.Container(
                width=metric_width,
                height=40,
                border_radius=6,
                padding=ft.Padding.symmetric(horizontal=7, vertical=3),
                bgcolor=ft.Colors.with_opacity(0.08, color),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.24, color)),
                content=ft.Column(
                    spacing=0,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    tight=True,
                    controls=[
                        ft.Text(
                            label,
                            size=10,
                            weight=ft.FontWeight.W_600,
                            color=color,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        control,
                    ],
                ),
            )

        metric_row = ft.Row(
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                metric_box("Trang", pages, SCAN_PAGE_COLOR),
                metric_box("File", files, file_color),
            ],
        )

        def commit(_event=None) -> None:
            try:
                normalized_date = display_to_iso(scan_date.value or "")
            except ValueError as exc:
                status_banner.value = str(exc)
                status_banner.color = ft.Colors.ERROR
                ctx.page.update()
                return
            next_values = {
                "scanner_id": scanner.value or "",
                "scan_date": normalized_date,
                "scan_pages": pages.value or "0",
                "scan_files": files.value or "0",
            }
            if next_values == saved:
                return

            def mutate(values: dict) -> None:
                for item in values["paper_statuses"]:
                    if int(item["paper_format_id"]) == int(paper_format.id):
                        item["scanner_id"] = next_values["scanner_id"] or None
                        item["scan_date"] = next_values["scan_date"]
                        item["scan_pages"] = next_values["scan_pages"]
                        item["scan_files"] = next_values["scan_files"]
                        item["scan_status"] = (
                            "SCANNED"
                            if int(next_values["scan_pages"] or "0") > 0
                            or int(next_values["scan_files"] or "0") > 0
                            else "UNKNOWN"
                        )
                        return

            ok = save_inline(
                record,
                mutate,
                message=f"Đã lưu Scan {paper_format.code} cho {record['record_key']}.",
            )
            if ok:
                saved.update(next_values)
            else:
                scanner.value = saved["scanner_id"]
                scan_date.value = iso_to_display(saved["scan_date"])
                pages.value = saved["scan_pages"]
                files.value = saved["scan_files"]

        name_date_row = ft.Row(
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                scan_line(ft.Icons.PERSON_OUTLINE, scanner),
                scan_line(ft.Icons.EVENT_OUTLINED, scan_date),
            ],
        )

        return ft.DataCell(
            ft.Container(
                width=scan_column_width,
                height=PAPER_TABLE_ROW_HEIGHT - 14,
                padding=ft.Padding.symmetric(vertical=6, horizontal=6),
                border_radius=8,
                bgcolor=ft.Colors.with_opacity(0.05, file_color),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.16, file_color)),
                content=ft.Row(
                    spacing=2,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Column(
                            spacing=8,
                            tight=True,
                            expand=True,
                            controls=[
                                name_date_row,
                                scan_line(ft.Icons.FILTER_9_PLUS_OUTLINED, metric_row),
                            ],
                        ),
                        ft.IconButton(
                            icon=ft.Icons.SAVE_OUTLINED,
                            icon_size=16,
                            width=28,
                            height=28,
                            padding=0,
                            tooltip=f"Lưu Scan {paper_format.code}",
                            on_click=commit,
                        ),
                    ],
                ),
            ),
        )

    def check_cell(record: dict) -> ft.DataCell:
        saved = {
            "checker_id": str(record.get("checker_id") or ""),
            "check_date": record.get("check_date", "") or "",
            "check_pages": str(record.get("check_pages", 0) or 0),
            "check_files": str(record.get("check_files", 0) or 0),
        }
        check_color = COLUMN_ACCENT_COLORS["check"]

        def check_line(icon: str, control: ft.Control) -> ft.Control:
            return ft.Row(
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(icon, size=14, color=TEXT_MUTED),
                    control,
                ],
            )

        check_column_width = column_width("check")
        field_width = max(170, check_column_width - 58)
        date_width = 96
        name_width = max(88, field_width - date_width - 10)
        metric_width = max(92, int((field_width - 8) / 2))
        checker = ft.Dropdown(
            dense=True,
            width=name_width,
            height=PAPER_FIELD_HEIGHT,
            value=saved["checker_id"],
            hint_text="Tên",
            tooltip=personnel_name(saved["checker_id"]) or "Người check",
            border=ft.InputBorder.NONE,
            text_size=12,
            content_padding=ft.Padding.symmetric(vertical=0, horizontal=0),
            options=[
                ft.dropdown.Option(key="", text="--"),
                *[
                    ft.dropdown.Option(key=str(person.id), text=person.full_name)
                    for person in personnel
                    if person.id is not None
                ],
            ],
        )
        check_date = ft.TextField(
            value=iso_to_display(saved["check_date"]),
            dense=True,
            width=date_width,
            height=PAPER_FIELD_HEIGHT,
            hint_text=DISPLAY_DATE_HINT,
            tooltip=f"Ngày thực hiện ({DISPLAY_DATE_HINT})",
            border=ft.InputBorder.NONE,
            text_size=12,
            content_padding=ft.Padding.symmetric(vertical=0, horizontal=0),
        )
        pages = ft.TextField(
            value=saved["check_pages"],
            dense=True,
            height=22,
            width=max(34, metric_width - 52),
            hint_text="Trang",
            tooltip="Số trang check",
            keyboard_type=ft.KeyboardType.NUMBER,
            border=ft.InputBorder.NONE,
            text_size=12,
            color=SCAN_PAGE_COLOR,
            text_align=ft.TextAlign.CENTER,
            content_padding=ft.Padding.symmetric(vertical=0, horizontal=0),
        )
        files = ft.TextField(
            value=saved["check_files"],
            dense=True,
            height=22,
            width=max(34, metric_width - 44),
            hint_text="File",
            tooltip="Số file check",
            keyboard_type=ft.KeyboardType.NUMBER,
            border=ft.InputBorder.NONE,
            text_size=12,
            color=check_color,
            text_align=ft.TextAlign.CENTER,
            content_padding=ft.Padding.symmetric(vertical=0, horizontal=0),
        )

        def metric_box(label: str, control: ft.Control, color: str) -> ft.Control:
            return ft.Container(
                width=metric_width,
                height=40,
                border_radius=6,
                padding=ft.Padding.symmetric(horizontal=7, vertical=3),
                bgcolor=ft.Colors.with_opacity(0.08, color),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.24, color)),
                content=ft.Column(
                    spacing=0,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    tight=True,
                    controls=[
                        ft.Text(
                            label,
                            size=10,
                            weight=ft.FontWeight.W_600,
                            color=color,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        control,
                    ],
                ),
            )

        metric_row = ft.Row(
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                metric_box("Trang", pages, SCAN_PAGE_COLOR),
                metric_box("File", files, check_color),
            ],
        )

        def commit(_event=None) -> None:
            try:
                normalized_date = display_to_iso(check_date.value or "")
            except ValueError as exc:
                status_banner.value = str(exc)
                status_banner.color = ft.Colors.ERROR
                ctx.page.update()
                return
            next_values = {
                "checker_id": checker.value or "",
                "check_date": normalized_date,
                "check_pages": pages.value or "0",
                "check_files": files.value or "0",
            }
            if next_values == saved:
                return

            def mutate(values: dict) -> None:
                values["checker_id"] = optional_personnel_id(next_values["checker_id"])
                values["check_date"] = next_values["check_date"]
                values["check_pages"] = next_values["check_pages"]
                values["check_files"] = next_values["check_files"]

            ok = save_inline(
                record,
                mutate,
                message=f"Đã lưu Check hồ sơ {record['record_key']}.",
            )
            if ok:
                saved.update(next_values)
            else:
                checker.value = saved["checker_id"]
                check_date.value = iso_to_display(saved["check_date"])
                pages.value = saved["check_pages"]
                files.value = saved["check_files"]

        name_date_row = ft.Row(
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                check_line(ft.Icons.PERSON_OUTLINE, checker),
                check_line(ft.Icons.EVENT_OUTLINED, check_date),
            ],
        )

        return ft.DataCell(
            ft.Container(
                width=check_column_width,
                height=PAPER_TABLE_ROW_HEIGHT - 14,
                padding=ft.Padding.symmetric(vertical=6, horizontal=6),
                border_radius=8,
                bgcolor=ft.Colors.with_opacity(0.05, check_color),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.16, check_color)),
                content=ft.Row(
                    spacing=2,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Column(
                            spacing=8,
                            tight=True,
                            expand=True,
                            controls=[
                                name_date_row,
                                check_line(ft.Icons.FILTER_9_PLUS_OUTLINED, metric_row),
                            ],
                        ),
                        ft.IconButton(
                            icon=ft.Icons.SAVE_OUTLINED,
                            icon_size=16,
                            width=28,
                            height=28,
                            padding=0,
                            tooltip="Lưu Check hồ sơ",
                            on_click=commit,
                        ),
                    ],
                ),
            ),
        )

    column_specs: list[tuple[str, str, bool]] = [("stt", "STT", True)]
    if mapfile_levels:
        column_specs.extend(
            (f"level_{level.position}", level.display_name, False)
            for level in mapfile_levels
        )
    elif not directory_levels:
        column_specs.append(("record_key", "Mã hồ sơ", False))
    column_specs.extend(
        [
            *[
                (f"scan_{paper_format.code}", f"Scan {paper_format.code}", False)
                for paper_format in paper_formats
            ],
            ("check", "Check hồ sơ", False),
            ("record_status", "Trạng thái hồ sơ", False),
            ("backup_status", "Tình trạng backup", False),
            ("client_codes", "Máy đang lưu", False),
            ("actions", "Thao tác", False),
        ]
    )

    # Header subtitles/accents summarize the *entire* filtered dataset (not just
    # the current page), so they change whenever search/filters change.
    filtered_record_keys = records_summary["record_keys"]
    column_subtitles: dict[str, str] = {}
    column_accents: dict[str, str] = {}
    if mapfile_levels:
        for level in mapfile_levels:
            distinct_values = {
                level_part_value(record_key, level) for record_key in filtered_record_keys
            }
            column_subtitles[f"level_{level.position}"] = f"{len(distinct_values)} hồ sơ"
    elif not directory_levels:
        column_subtitles["record_key"] = f"{len(set(filtered_record_keys))} hồ sơ"
    for paper_format in paper_formats:
        totals = records_summary["paper_totals"].get(
            paper_format.code, {"scan_pages": 0, "scan_files": 0}
        )
        column_subtitles[f"scan_{paper_format.code}"] = (
            f"{totals['scan_pages']} trang · {totals['scan_files']} file"
        )
        column_accents[f"scan_{paper_format.code}"] = COLUMN_ACCENT_COLORS.get(
            paper_format.code, DEFAULT_COLUMN_ACCENT
        )
    column_subtitles["check"] = (
        f"{records_summary['check_pages']} trang · {records_summary['check_files']} file"
    )
    column_accents["check"] = COLUMN_ACCENT_COLORS["check"]

    columns = [
        col(
            label,
            key,
            next_key=column_specs[index + 1][0] if index + 1 < len(column_specs) else None,
            numeric=numeric,
            subtitle=column_subtitles.get(key),
            accent=column_accents.get(key),
        )
        for index, (key, label, numeric) in enumerate(column_specs)
    ]

    data_rows = []
    for row_offset, record in enumerate(records):
        cells = [
            cell(ft.Text(str(page_index * page_size + row_offset + 1), text_align=ft.TextAlign.CENTER), key="stt")
        ]
        if mapfile_levels:
            for level in mapfile_levels:
                value = level_part_value(record["record_key"], level)
                cells.append(
                    cell(
                        ft.Text(value, tooltip=value, text_align=ft.TextAlign.CENTER),
                        key=f"level_{level.position}",
                    )
                )
        elif not directory_levels:
            cells.append(
                cell(
                    ft.Text(
                        record["record_key"],
                        max_lines=2,
                        tooltip=record["record_key"],
                        text_align=ft.TextAlign.CENTER,
                    ),
                    key="record_key",
                )
            )
        cells.extend(
            [
                *[
                    paper_scan_cell(record, paper_format)
                    for paper_format in paper_formats
                ],
                check_cell(record),
                record_status_cell(record),
                cell(
                    kit.badge(
                        BACKUP_STATUS_LABELS.get(
                            record["backup_status"], record["backup_status"]
                        ),
                        BACKUP_STATUS_COLORS.get(
                            record["backup_status"], "#9CA3AF"
                        ),
                    ),
                    key="backup_status",
                ),
                cell(
                    ft.Text(
                        record["client_codes"] or "—",
                        tooltip=record["client_codes"] or "",
                        text_align=ft.TextAlign.CENTER,
                    ),
                    key="client_codes",
                ),
                cell(
                    ft.Row(
                        spacing=2,
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[
                            ft.IconButton(
                                icon=ft.Icons.FOLDER_OPEN,
                                tooltip="Mở thư mục hồ sơ",
                                disabled=not bool(record["sample_dest_path"]),
                                on_click=lambda _e, current=record: open_folder(
                                    current
                                ),
                            ),
                        ],
                    ),
                    key="actions",
                ),
            ]
        )
        data_rows.append(
            ft.DataRow(
                cells=cells,
                selected=record["record_key"] in state["selected_records"],
                on_select_change=lambda event, key=record["record_key"]: (
                    state["selected_records"].add(key)
                    if event.control.selected
                    else state["selected_records"].discard(key),
                    ctx.page.update(),
                ),
            )
        )

    table = ft.DataTable(
        columns=columns,
        rows=data_rows,
        width=actual_table_width(),
        expand=True,
        data_row_min_height=PAPER_TABLE_ROW_HEIGHT,
        data_row_max_height=PAPER_TABLE_ROW_HEIGHT,
        heading_row_height=54,
        column_spacing=12,
        horizontal_margin=8,
    )
    kit.style_table(table)
    has_filters = any(str(value).strip() for value in filters.values())
    toolbar = kit.card(ft.Row(
        spacing=8,
        wrap=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.FilledButton(
                "Thêm công việc mới",
                icon=ft.Icons.ADD_TASK,
                on_click=open_create_job_dialog,
            ),
            ft.IconButton(
                icon=ft.Icons.CONTENT_COPY,
                tooltip="Copy dòng",
                on_click=lambda _e: copy_selected_rows(),
            ),
            ft.IconButton(
                icon=ft.Icons.CONTENT_PASTE,
                tooltip="Dán dòng",
                on_click=lambda _e: paste_copied_rows(),
            ),
            ft.IconButton(
                icon=ft.Icons.VERTICAL_ALIGN_BOTTOM,
                tooltip="Điền xuống",
                on_click=lambda _e: fill_down_selected_rows(),
            ),
            search_field,
            ft.FilledButton("Tìm kiếm", icon=ft.Icons.SEARCH, on_click=apply_search),
            ft.OutlinedButton(
                "Xóa lọc",
                icon=ft.Icons.FILTER_ALT_OFF,
                disabled=not bool(state["search"]),
                on_click=clear_search,
            ),
            ft.Container(width=1, height=36, bgcolor=LINE),
            record_key_filter,
            *[field for _key, field in level_filter_fields],
            client_filter,
            record_status_filter,
            backup_status_filter,
            ft.FilledButton("Lọc cột", icon=ft.Icons.FILTER_ALT, on_click=apply_filters),
            ft.OutlinedButton(
                "Xóa lọc cột",
                icon=ft.Icons.FILTER_ALT_OFF,
                disabled=not has_filters,
                on_click=clear_filters,
            ),
            ft.IconButton(
                icon=ft.Icons.REFRESH,
                tooltip="Làm mới dữ liệu",
                on_click=lambda _e: ctx.refresh(),
            ),
            status_banner,
        ],
    ), padding=12)

    page_size_dropdown = ft.Dropdown(
        label="Dòng/trang",
        dense=True,
        width=118,
        value=str(page_size),
        options=[
            ft.dropdown.Option(key=str(option), text=str(option))
            for option in PAGE_SIZE_OPTIONS
        ],
    )
    page_size_dropdown.on_change = change_page_size

    if not records:
        empty_text = ft.Text(
            "Không tìm thấy hồ sơ phù hợp."
            if state["search"] or has_filters
            else "Hệ thống chưa ghi nhận hồ sơ nào cho dự án này.",
            color=TEXT_MUTED,
        )
        body: ft.Control = ft.Column(
            spacing=8,
            controls=[empty_text],
        )
    else:
        start_row = page_index * page_size + 1
        end_row = start_row + len(records) - 1
        body = ft.Column(
            expand=True,
            spacing=8,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(
                            f"Hiển thị {start_row}–{end_row} trong {total_rows} hồ sơ",
                            size=12,
                            color=TEXT_MUTED,
                        ),
                        ft.Row(
                            spacing=2,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                page_size_dropdown,
                                ft.IconButton(
                                    icon=ft.Icons.CHEVRON_LEFT,
                                    tooltip="Trang trước",
                                    disabled=page_index <= 0,
                                    on_click=lambda _e: change_page(-1),
                                ),
                                ft.Text(f"Trang {page_index + 1}"),
                                ft.IconButton(
                                    icon=ft.Icons.CHEVRON_RIGHT,
                                    tooltip="Trang sau",
                                    disabled=(page_index + 1) * page_size >= total_rows,
                                    on_click=lambda _e: change_page(1),
                                ),
                            ],
                        ),
                    ],
                ),
                kit.card(
                    ft.Row(
                        expand=True,
                        scroll=ft.ScrollMode.AUTO,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[table],
                    ),
                    padding=6,
                ),
            ],
        )

    return ft.Column(
        expand=True,
        spacing=14,
        controls=[
            ft.Text(
                "Theo dõi hồ sơ theo các cấp thư mục cấu hình, nghiệp vụ Scan / Check, "
                "khổ giấy và tình trạng backup tự động.",
                size=13,
                color=TEXT_MUTED,
            ),
            toolbar,
            body,
        ],
    )
