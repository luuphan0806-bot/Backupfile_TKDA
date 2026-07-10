from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

import flet as ft

from ....models import ProjectTask
from ... import kit
from ...date_format import iso_to_display
from ...theme import DANGER, INFO, LINE, SUCCESS, WARNING, TEXT_MUTED


DEFAULT_PAGE_SIZE = 50
PAGE_SIZE_OPTIONS = [25, 50, 100]
PAPER_CELL_WIDTH = 320
PAPER_TABLE_ROW_HEIGHT = 116
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
COUNTABLE_BACKUP_STATUSES = {"HASH_PENDING", "VERIFIED_HASH", "LOCKED", "ALREADY_EXISTS"}


def build(ctx) -> ft.Control:
    state = ctx.view_state.setdefault(
        "system_mapfile",
        {"search": "", "page": 0},
    )
    state.setdefault("flash", "")
    state.setdefault("filters", {})
    state.setdefault("page_size", DEFAULT_PAGE_SIZE)
    state.setdefault("column_weights", {})
    state.setdefault("column_widths", {})
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

    def show_success_toast(message: str) -> None:
        snack = ft.SnackBar(
            ft.Row(
                spacing=10,
                controls=[
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.WHITE),
                    ft.Text(message, color=ft.Colors.WHITE, weight=ft.FontWeight.W_600),
                ],
            ),
            bgcolor=SUCCESS,
            show_close_icon=True,
            duration=3500,
            open=True,
        )
        ctx.page.overlay.append(snack)
        ctx.page.update()

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
            "duplicate_column": duplicate_filter.value or "",
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

    def backup_record(record: dict) -> None:
        try:
            result = ctx.backup.backup_record(ctx.project_id, record["record_key"])
        except (OSError, ValueError) as exc:
            status_banner.value = f"Không thể sao lưu hồ sơ {record['record_key']}: {exc}"
            status_banner.color = ft.Colors.ERROR
            ctx.page.update()
            return
        state["flash"] = (
            f"Đã sao lưu {result['processed']} file cho {record['record_key']} "
            f"({result['errors']} lỗi, {result['conflicts']} xung đột)."
        )
        state["page"] = page_index
        ctx.refresh()

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
    paper_formats = ctx.db.list_paper_formats(ctx.project_id, enabled_only=True)

    def level_part_value(record_key: str, level) -> str:
        record_parts = record_key.replace("\\", "/").split("/")
        part_index = max(0, int(level.position) - 1)
        value = record_parts[part_index] if part_index < len(record_parts) else "—"
        if part_index == len(directory_levels) - 1 and len(record_parts) > len(directory_levels):
            value = "/".join(record_parts[part_index:])
        return value

    duplicate_options = [
        ft.dropdown.Option(key="", text="Không lọc trùng"),
        ft.dropdown.Option(key="record_key", text="Mã hồ sơ"),
        *[
            ft.dropdown.Option(key=f"level_{level.position}", text=level.display_name)
            for level in mapfile_levels
        ],
        ft.dropdown.Option(key="client_codes", text="Máy đang lưu"),
    ]
    duplicate_filter = ft.Dropdown(
        label="Lọc trùng",
        dense=True,
        width=170,
        value=filters.get("duplicate_column", ""),
        options=duplicate_options,
    )
    duplicate_filter.on_change = apply_filters

    base_filters = {
        key: value
        for key, value in filters.items()
        if key != "duplicate_column"
    }
    duplicate_column = str(filters.get("duplicate_column", "") or "")
    if duplicate_column:
        all_records, _all_total = ctx.db.list_system_records_page(
            ctx.project_id,
            limit=5000,
            offset=0,
            search=state["search"],
            filters=base_filters,
        )

        def duplicate_value(record: dict) -> str:
            if duplicate_column.startswith("level_"):
                position = int(duplicate_column.split("_", 1)[1])
                level = next((item for item in mapfile_levels if item.position == position), None)
                return level_part_value(record["record_key"], level) if level else ""
            return str(record.get(duplicate_column, "") or "").strip()

        counts: dict[str, int] = {}
        for record in all_records:
            value = duplicate_value(record)
            if value:
                counts[value] = counts.get(value, 0) + 1
        duplicate_values = {value for value, count in counts.items() if count > 1}
        filtered_records = [
            record for record in all_records if duplicate_value(record) in duplicate_values
        ]
        total_rows = len(filtered_records)
        records = filtered_records[page_index * page_size : (page_index + 1) * page_size]
        records_summary = ctx.db.get_system_records_summary(
            ctx.project_id, search=state["search"], filters=base_filters
        )
    else:
        records, total_rows = ctx.db.list_system_records_page(
            ctx.project_id,
            limit=page_size,
            offset=page_index * page_size,
            search=state["search"],
            filters=base_filters,
        )
        records_summary = ctx.db.get_system_records_summary(
            ctx.project_id, search=state["search"], filters=base_filters
        )

    personnel = ctx.db.list_personnel(ctx.project_id, enabled_only=True)
    clients = ctx.db.list_clients(ctx.project_id)
    job_types = ctx.db.list_job_types(ctx.project_id, enabled_only=True)

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
        "actions": 4,
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
        "actions": 176,
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

    def normalize_lookup(value: str) -> str:
        return " ".join(value.strip().lower().split())

    def find_job(value: str):
        needle = normalize_lookup(value)
        for item in job_types:
            if needle in {
                normalize_lookup(item.job_code),
                normalize_lookup(item.display_name),
            }:
                return item
        return None

    def find_person(value: str):
        needle = normalize_lookup(value)
        for item in personnel:
            if item.id is None:
                continue
            if needle in {
                normalize_lookup(item.personnel_code),
                normalize_lookup(item.full_name),
            }:
                return item
        return None

    def find_client(value: str):
        needle = normalize_lookup(value)
        for item in clients:
            if not item.enabled:
                continue
            if needle in {
                normalize_lookup(item.client_code),
                normalize_lookup(item.staff_name),
                normalize_lookup(item.share_path),
            }:
                return item
        return None

    def assignment_kind(job_label: str, job_code: str) -> str:
        text = normalize_lookup(f"{job_code} {job_label}")
        return "check" if "check" in text else "scan"

    def job_implies_a3(job_label: str, job_code: str) -> bool:
        return "a3" in normalize_lookup(f"{job_code} {job_label}")

    def copy_backup_files_for_check(record_key: str, target_folder: Path) -> int:
        rows = ctx.db.list_backup_files_for_record(
            ctx.project_id,
            record_key,
            statuses=COUNTABLE_BACKUP_STATUSES,
        )
        if not rows:
            raise ValueError("Chưa có dữ liệu backup để copy sang thư mục check.")
        copied = 0
        target_folder.mkdir(parents=True, exist_ok=True)
        for row in rows:
            source = Path(row["dest_path"])
            if not source.exists():
                source = Path(row["source_path"])
            if not source.exists() or not source.is_file():
                continue
            shutil.copy2(source, target_folder / source.name)
            copied += 1
        if copied == 0:
            raise ValueError("Không tìm thấy file backup hợp lệ để copy sang thư mục check.")
        return copied

    def open_setup_dialog(record: dict) -> None:
        parts = [part for part in record["record_key"].replace("\\", "/").split("/") if part]
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
            value=str(record.get("scanner_id") or ""),
            options=[
                ft.dropdown.Option(key=str(person.id), text=person.full_name)
                for person in personnel
                if person.id is not None
            ],
        )
        client_dropdown = ft.Dropdown(
            label="Máy trạm",
            dense=True,
            width=300,
            options=[
                ft.dropdown.Option(
                    key=client.client_code,
                    text=f"{client.client_code} - {client.share_path}",
                )
                for client in clients
                if client.enabled
            ],
        )
        finish_previous_checkbox = ft.Checkbox(
            label="Chốt việc cũ của nhân sự và sao lưu trước khi giao việc mới",
            value=False,
        )
        a3_current = dict(record.get("paper_statuses", {}).get("A3") or {})
        a3_presence_checkbox = ft.Checkbox(
            label="Hồ sơ có A3 cần scan tiếp",
            value=a3_current.get("scan_status") in {"PENDING_SCAN", "SCANNED", "CHECKED"}
            or int(a3_current.get("scan_pages", 0) or 0) > 0
            or int(a3_current.get("scan_files", 0) or 0) > 0,
        )
        error_text = ft.Text("", color=DANGER)

        def submit(_event=None) -> None:
            job_code = job_dropdown.value or ""
            personnel_id = int(personnel_dropdown.value) if personnel_dropdown.value else None
            client_code = client_dropdown.value or ""
            if not parts:
                error_text.value = "Không xác định được cấu trúc hồ sơ."
                ctx.page.update()
                return
            if not job_code or personnel_id is None or not client_code:
                error_text.value = "Cần chọn đủ công việc, nhân sự và máy trạm."
                ctx.page.update()
                return
            job = next((item for item in job_types if item.job_code == job_code), None)
            person = next((item for item in personnel if item.id == personnel_id), None)
            if not job or not person:
                error_text.value = "Công việc hoặc nhân sự không hợp lệ."
                ctx.page.update()
                return
            work_date_display = datetime.now().strftime("%d/%m/%Y")
            work_date_folder = datetime.now().strftime("%d-%m-%Y")
            try:
                completed_previous = []
                if finish_previous_checkbox.value and personnel_id is not None:
                    completed_previous = ctx.db.complete_open_tasks_for_assignee(
                        ctx.project_id,
                        personnel_id,
                    )
                    for previous_key in completed_previous:
                        try:
                            ctx.backup.backup_record(ctx.project_id, previous_key)
                        except Exception as exc:
                            ctx.db.record_audit(
                                "ASSIGNMENT_PREVIOUS_BACKUP_ERROR",
                                str(exc),
                                project_id=ctx.project_id,
                            )
                target = ctx.mapfiles.create_client_record_folder(
                    ctx.project_id,
                    client_code,
                    parts,
                    owner_name=person.full_name,
                    work_date=work_date_folder,
                    task_name=job.display_name,
                )
                ctx.db.save_task(
                    ProjectTask(
                        None,
                        ctx.project_id,
                        task_code_for(parts, job.job_code),
                        job.display_name,
                        f"Thu muc ho so: {'/'.join(parts)}\nMay tram: {client_code}\nThu muc: {target}",
                        personnel_id,
                        "",
                    )
                )
                ctx.db.save_record_assignment(
                    project_id=ctx.project_id,
                    record_key="/".join(parts),
                    personnel_id=personnel_id,
                    work_date=work_date_display,
                    assignment_kind=assignment_kind(job.display_name, job.job_code),
                    paper_presence={
                        "A3": bool(a3_presence_checkbox.value)
                        or job_implies_a3(job.display_name, job.job_code)
                    },
                )
                copied_for_check = 0
                if assignment_kind(job.display_name, job.job_code) == "check":
                    copied_for_check = copy_backup_files_for_check("/".join(parts), target)
            except ValueError as exc:
                error_text.value = str(exc)
                ctx.page.update()
                return
            ctx.page.pop_dialog()
            extras = []
            if completed_previous:
                extras.append(f"đã chốt/backup {len(completed_previous)} việc cũ")
            if copied_for_check:
                extras.append(f"đã copy {copied_for_check} file sang thư mục check")
            suffix = f" ({'; '.join(extras)})" if extras else ""
            state["flash"] = f"Đã setup thư mục công việc cho {record['record_key']}.{suffix}"
            show_success_toast(f"Đã tạo thư mục ở máy trạm: {target}")
            ctx.refresh()

        dialog = kit.dialog(
            f"Setup công việc {record['record_key']}",
            ft.Column(
                spacing=12,
                tight=True,
                controls=[
                    ft.Text("/".join(parts), color=TEXT_MUTED),
                    ft.Row([job_dropdown, personnel_dropdown, client_dropdown], wrap=True, spacing=8),
                    finish_previous_checkbox,
                    a3_presence_checkbox,
                    error_text,
                ],
            ),
            [
                kit.ghost_button("Hủy", on_click=lambda _e: ctx.page.pop_dialog()),
                kit.primary_button("Setup", icon=ft.Icons.SETTINGS, on_click=submit),
            ],
            icon=ft.Icons.SETTINGS,
            width=900,
        )
        ctx.page.show_dialog(dialog)

    def open_edit_record_dialog(record: dict) -> None:
        current_parts = [
            part for part in record["record_key"].replace("\\", "/").split("/") if part
        ]
        record_fields = []
        for index, (_key, label) in enumerate(new_record_keys()):
            if index == len(new_record_keys()) - 1 and len(current_parts) > len(new_record_keys()):
                value = "/".join(current_parts[index:])
            else:
                value = current_parts[index] if index < len(current_parts) else ""
            record_fields.append(
                ft.TextField(label=label, value=value, dense=True, width=220)
            )
        error_text = ft.Text("", color=DANGER)

        def submit(_event=None) -> None:
            new_parts = [(field.value or "").strip() for field in record_fields]
            if not new_parts or any(not part for part in new_parts):
                error_text.value = "Can nhap du thong tin ho so."
                ctx.page.update()
                return
            try:
                new_key = ctx.mapfiles.update_manual_record(
                    ctx.project_id,
                    record["record_key"],
                    new_parts,
                )
            except ValueError as exc:
                error_text.value = str(exc)
                ctx.page.update()
                return
            ctx.page.pop_dialog()
            state["flash"] = f"Da cap nhat ho so {record['record_key']} -> {new_key}."
            ctx.refresh()

        dialog = kit.dialog(
            f"Sua thong tin ho so {record['record_key']}",
            ft.Column(
                spacing=12,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Row(record_fields, wrap=True, spacing=8),
                    error_text,
                ],
            ),
            [
                kit.ghost_button("Huy", on_click=lambda _e: ctx.page.pop_dialog()),
                kit.primary_button("Luu", icon=ft.Icons.SAVE_OUTLINED, on_click=submit),
            ],
            icon=ft.Icons.EDIT_OUTLINED,
            width=860,
        )
        ctx.page.show_dialog(dialog)

    def open_create_job_dialog(_event=None) -> None:
        record_fields = [
            (key, label, ft.TextField(label=label, dense=True, width=220))
            for key, label in new_record_keys()
        ]
        job_dropdown = ft.Dropdown(
            label="Cong viec",
            dense=True,
            width=240,
            value=job_types[0].job_code if job_types else "",
            options=[
                ft.dropdown.Option(key=item.job_code, text=item.display_name)
                for item in job_types
            ],
        )
        personnel_dropdown = ft.Dropdown(
            label="Nhan su dam nhiem",
            dense=True,
            width=260,
            options=[
                ft.dropdown.Option(key=str(person.id), text=person.full_name)
                for person in personnel
                if person.id is not None
            ],
        )
        client_dropdown = ft.Dropdown(
            label="May tram",
            dense=True,
            width=300,
            options=[
                ft.dropdown.Option(
                    key=client.client_code,
                    text=f"{client.client_code} - {client.share_path}",
                )
                for client in clients
                if client.enabled
            ],
        )
        finish_previous_checkbox = ft.Checkbox(
            label="Chot viec cu cua nhan su va sao luu truoc khi giao viec moi",
            value=False,
        )
        a3_presence_checkbox = ft.Checkbox(
            label="Ho so co A3 can scan tiep",
            value=False,
        )
        error_text = ft.Text("", color=DANGER)

        def submit(_submit_event=None) -> None:
            parts = [(field.value or "").strip() for _key, _label, field in record_fields]
            job_code = job_dropdown.value or ""
            personnel_id = int(personnel_dropdown.value) if personnel_dropdown.value else None
            client_code = client_dropdown.value or ""
            if not parts or any(not part for part in parts):
                error_text.value = "Can nhap du cau truc ho so cho dong mapfile."
                ctx.page.update()
                return
            if not job_code or personnel_id is None or not client_code:
                error_text.value = "Can chon du cong viec, nhan su va may tram."
                ctx.page.update()
                return
            job = next((item for item in job_types if item.job_code == job_code), None)
            person = next((item for item in personnel if item.id == personnel_id), None)
            client = next((item for item in clients if item.client_code == client_code), None)
            if not job or not person or not client:
                error_text.value = "Cong viec, nhan su hoac may tram khong hop le."
                ctx.page.update()
                return
            work_date_display = datetime.now().strftime("%d/%m/%Y")
            work_date_folder = datetime.now().strftime("%d-%m-%Y")
            try:
                completed_previous = []
                if finish_previous_checkbox.value:
                    completed_previous = ctx.db.complete_open_tasks_for_assignee(
                        ctx.project_id,
                        personnel_id,
                    )
                    for previous_key in completed_previous:
                        try:
                            ctx.backup.backup_record(ctx.project_id, previous_key)
                        except Exception as exc:
                            ctx.db.record_audit(
                                "ASSIGNMENT_PREVIOUS_BACKUP_ERROR",
                                str(exc),
                                project_id=ctx.project_id,
                            )
                row_id = ctx.mapfiles.add_manual_record(
                    ctx.project_id,
                    parts,
                    client_code=client.client_code,
                    workstation_owner=person.full_name,
                    workstation_date=work_date_folder,
                    workstation_task=job.display_name,
                )
                target = ctx.mapfiles.create_client_record_folder(
                    ctx.project_id,
                    client.client_code,
                    parts,
                    owner_name=person.full_name,
                    work_date=work_date_folder,
                    task_name=job.display_name,
                )
                ctx.db.save_task(
                    ProjectTask(
                        None,
                        ctx.project_id,
                        task_code_for(parts, job.job_code),
                        job.display_name,
                        f"Thu muc ho so: {'/'.join(parts)}\nMay tram: {client.client_code}\nDong mapfile: {row_id}\nThu muc: {target}",
                        int(person.id),
                        "",
                    )
                )
                ctx.db.save_record_assignment(
                    project_id=ctx.project_id,
                    record_key="/".join(parts),
                    personnel_id=int(person.id),
                    work_date=work_date_display,
                    assignment_kind=assignment_kind(job.display_name, job.job_code),
                    paper_presence={
                        "A3": bool(a3_presence_checkbox.value)
                        or job_implies_a3(job.display_name, job.job_code)
                    },
                )
                copied_for_check = 0
                if assignment_kind(job.display_name, job.job_code) == "check":
                    copied_for_check = copy_backup_files_for_check("/".join(parts), target)
            except ValueError as exc:
                error_text.value = str(exc)
                ctx.page.update()
                return
            ctx.page.pop_dialog()
            extras = []
            if completed_previous:
                extras.append(f"da chot/backup {len(completed_previous)} viec cu")
            if copied_for_check:
                extras.append(f"da copy {copied_for_check} file sang thu muc check")
            suffix = f" ({'; '.join(extras)})" if extras else ""
            state["flash"] = f"Da tao 1 cong viec va thu muc ho so tren may tram.{suffix}"
            state["page"] = 0
            show_success_toast(f"Đã tạo thư mục ở máy trạm: {target}")
            ctx.refresh()

        dialog = kit.dialog(
            "Tao cong viec va them dong ho so",
            ft.Column(
                spacing=12,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        "Moi lan giao viec tao dung 1 dong mapfile cho 1 nhan su va 1 cong viec.",
                        color=TEXT_MUTED,
                    ),
                    ft.Row([field for _key, _label, field in record_fields], wrap=True, spacing=8),
                    ft.Row([job_dropdown, personnel_dropdown, client_dropdown], wrap=True, spacing=8),
                    finish_previous_checkbox,
                    a3_presence_checkbox,
                    error_text,
                ],
            ),
            [
                kit.ghost_button("Huy", on_click=lambda _e: ctx.page.pop_dialog()),
                kit.primary_button("Tao cong viec", icon=ft.Icons.ADD_TASK, on_click=submit),
            ],
            icon=ft.Icons.ADD_TASK,
            width=940,
        )
        ctx.page.show_dialog(dialog)

    def readonly_metric_box(label: str, value: int | str, color: str, width: int) -> ft.Control:
        return ft.Container(
            width=width,
            height=36,
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
            bgcolor=ft.Colors.with_opacity(0.08, color),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.22, color)),
            content=ft.Row(
                spacing=6,
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text(str(value), size=13, weight=ft.FontWeight.W_700, color=color),
                    ft.Text(label, size=10, color=color),
                ],
            ),
        )

    def readonly_assignment_line(name: str, date_value: str, width: int) -> ft.Control:
        display_date = iso_to_display(date_value or "") if date_value else "--"
        return ft.Row(
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Row(
                    spacing=5,
                    expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.PERSON_OUTLINE, size=14, color=TEXT_MUTED),
                        ft.Text(name or "--", size=12, tooltip=name or "", max_lines=1, expand=True),
                    ],
                ),
                ft.Row(
                    spacing=5,
                    width=min(106, max(86, int(width * 0.34))),
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.EVENT_OUTLINED, size=14, color=TEXT_MUTED),
                        ft.Text(display_date, size=12, color=TEXT_MUTED, max_lines=1),
                    ],
                ),
            ],
        )

    def scan_status_badge(paper_code: str, pages: int, files: int, color: str) -> ft.Control:
        done = pages > 0 or files > 0
        label = f"Scan xong {paper_code}" if done else f"Cần scan {paper_code}"
        badge_color = color if done else WARNING
        return ft.Container(
            height=22,
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=8, vertical=2),
            bgcolor=ft.Colors.with_opacity(0.10, badge_color),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.24, badge_color)),
            content=ft.Row(
                spacing=5,
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(
                        ft.Icons.CHECK_CIRCLE_OUTLINE if done else ft.Icons.PENDING_ACTIONS,
                        size=13,
                        color=badge_color,
                    ),
                    ft.Text(label, size=11, weight=ft.FontWeight.W_600, color=badge_color),
                ],
            ),
        )

    def paper_scan_cell(record: dict, paper_format) -> ft.DataCell:
        current = dict(record["paper_statuses"].get(paper_format.code) or {})
        scan_column_width = column_width(f"scan_{paper_format.code}")
        metric_width = max(82, int((scan_column_width - 36) / 2))
        file_color = SCAN_FILE_COLORS.get(paper_format.code, ft.Colors.PRIMARY)
        scanner_name = current.get("scanner_name") or record.get("scanner_name") or ""
        scan_date = current.get("scan_date") or ""
        pages = int(current.get("scan_pages", 0) or 0)
        files = int(current.get("scan_files", 0) or 0)
        return ft.DataCell(
            ft.Container(
                width=scan_column_width,
                height=PAPER_TABLE_ROW_HEIGHT - 18,
                padding=ft.Padding.symmetric(vertical=8, horizontal=8),
                border_radius=8,
                bgcolor=ft.Colors.with_opacity(0.045, file_color),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.14, file_color)),
                content=ft.Column(
                    spacing=6,
                    alignment=ft.MainAxisAlignment.CENTER,
                    tight=True,
                    controls=[
                        scan_status_badge(paper_format.code, pages, files, file_color),
                        readonly_assignment_line(scanner_name, scan_date, scan_column_width),
                        ft.Row(
                            spacing=8,
                            alignment=ft.MainAxisAlignment.CENTER,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                readonly_metric_box("trang", pages, SCAN_PAGE_COLOR, metric_width),
                                readonly_metric_box("file", files, file_color, metric_width),
                            ],
                        ),
                    ],
                ),
            ),
        )

    def check_cell(record: dict) -> ft.DataCell:
        check_column_width = column_width("check")
        metric_width = max(82, int((check_column_width - 36) / 2))
        check_color = COLUMN_ACCENT_COLORS["check"]
        checker_name = record.get("checker_name") or ""
        check_date = record.get("check_date") or ""
        pages = int(record.get("check_pages", 0) or 0)
        files = int(record.get("check_files", 0) or 0)
        return ft.DataCell(
            ft.Container(
                width=check_column_width,
                height=PAPER_TABLE_ROW_HEIGHT - 18,
                padding=ft.Padding.symmetric(vertical=8, horizontal=8),
                border_radius=8,
                bgcolor=ft.Colors.with_opacity(0.045, check_color),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.14, check_color)),
                content=ft.Column(
                    spacing=9,
                    alignment=ft.MainAxisAlignment.CENTER,
                    tight=True,
                    controls=[
                        readonly_assignment_line(checker_name, check_date, check_column_width),
                        ft.Row(
                            spacing=8,
                            alignment=ft.MainAxisAlignment.CENTER,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                readonly_metric_box("trang", pages, SCAN_PAGE_COLOR, metric_width),
                                readonly_metric_box("file", files, check_color, metric_width),
                            ],
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
                                icon=ft.Icons.EDIT_OUTLINED,
                                tooltip="Sua thong tin ho so",
                                on_click=lambda _e, current=record: open_edit_record_dialog(
                                    current
                                ),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.BACKUP_OUTLINED,
                                tooltip="Sao luu ho so",
                                on_click=lambda _e, current=record: backup_record(
                                    current
                                ),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.SETTINGS_OUTLINED,
                                tooltip="Setup cong viec",
                                on_click=lambda _e, current=record: open_setup_dialog(
                                    current
                                ),
                            ),
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
            duplicate_filter,
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
            scroll=ft.ScrollMode.AUTO,
            controls=[empty_text],
        )
    else:
        start_row = page_index * page_size + 1
        end_row = start_row + len(records) - 1
        body = ft.Column(
            expand=True,
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
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
