from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

import flet as ft

from ...theme import DANGER, INFO, SUCCESS, WARNING


PAGE_SIZE = 50

PAPER_STATUS_LABELS = {
    "UNKNOWN": "Chưa xác định",
    "NOT_PRESENT": "Không có",
    "PENDING_SCAN": "Có - Chưa scan",
    "SCANNED": "Đã scan",
    "CHECKED": "Đã check",
    "RESCAN_REQUIRED": "Cần scan lại",
}
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


def _badge(label: str, color: str) -> ft.Control:
    return ft.Container(
        padding=ft.Padding.symmetric(vertical=3, horizontal=8),
        border_radius=999,
        bgcolor=ft.Colors.with_opacity(0.15, color),
        content=ft.Text(label, size=11, color=color, weight=ft.FontWeight.BOLD),
    )


def build(ctx) -> ft.Control:
    state = ctx.view_state.setdefault(
        "system_mapfile",
        {"search": "", "page": 0},
    )
    state.setdefault("flash", "")
    state.setdefault("adding", False)
    state.setdefault("new_record", {})
    state.setdefault("selected_records", set())
    state.setdefault("clipboard_records", [])
    if not isinstance(state["selected_records"], set):
        state["selected_records"] = set(state["selected_records"])
    status_banner = ft.Text(state.get("flash", ""), color=ft.Colors.PRIMARY)
    search_field = ft.TextField(
        label="Tìm theo hồ sơ, máy trạm hoặc đường dẫn",
        value=state["search"],
        width=360,
        dense=True,
    )

    def apply_search(_event=None) -> None:
        state["search"] = (search_field.value or "").strip()
        state["page"] = 0
        ctx.refresh()

    def clear_search(_event) -> None:
        state["search"] = ""
        state["page"] = 0
        ctx.refresh()

    def change_page(delta: int) -> None:
        state["page"] = max(0, int(state["page"]) + delta)
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
            "record_status": workflow.get("record_status", "NOT_STARTED"),
            "notes": workflow.get("notes", ""),
            "paper_statuses": [
                {
                    "paper_format_id": paper["paper_format_id"],
                    "scanner_id": paper.get("scanner_id"),
                    "scan_date": paper.get("scan_date", ""),
                    "scan_status": paper["scan_status"],
                    "scan_pages": str(paper["scan_pages"]),
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
                record_status=values["record_status"],
                notes=values["notes"],
                paper_statuses=values["paper_statuses"],
            )
        except ValueError as exc:
            status_banner.value = str(exc)
            status_banner.color = ft.Colors.ERROR
            ctx.page.update()
            return False
        state["flash"] = message
        ctx.refresh()
        return True

    def personnel_cell(record: dict, field_name: str, selected_id: int | None) -> ft.DataCell:
        control = ft.Dropdown(
            dense=True,
            width=190,
            value=str(selected_id) if selected_id else "",
            options=[
                ft.dropdown.Option(key="", text="--"),
                *[
                    ft.dropdown.Option(
                        key=str(person.id),
                        text=f"{person.personnel_code} - {person.full_name}",
                    )
                    for person in personnel
                    if person.id is not None
                ],
            ],
        )
        control.on_change = lambda event: save_inline(
            record,
            lambda values: values.__setitem__(
                field_name, optional_personnel_id(event.control.value)
            ),
            message=f"Đã lưu {record['record_key']}.",
        )
        return ft.DataCell(control)

    def date_cell(record: dict, field_name: str, value: str) -> ft.DataCell:
        saved_value = {"value": value or ""}
        display = ft.TextField(
            value=saved_value["value"],
            dense=True,
            width=118,
            read_only=True,
            hint_text="YYYY-MM-DD",
            content_padding=ft.Padding.symmetric(vertical=6, horizontal=8),
        )

        def initial_date() -> date:
            try:
                return datetime.strptime(saved_value["value"], "%Y-%m-%d").date()
            except ValueError:
                return date.today()

        def commit(selected: str) -> None:
            if selected == saved_value["value"]:
                return
            saved = save_inline(
                record,
                lambda values: values.__setitem__(field_name, selected),
                message=f"Đã lưu {record['record_key']}.",
            )
            if saved:
                saved_value["value"] = selected
                display.value = selected

        def open_picker(_event) -> None:
            def on_change(event) -> None:
                selected = event.control.value
                if isinstance(selected, datetime):
                    commit(selected.date().isoformat())
                elif isinstance(selected, date):
                    commit(selected.isoformat())

            ctx.page.show_dialog(
                ft.DatePicker(
                    value=initial_date(),
                    first_date=date(2000, 1, 1),
                    last_date=date(2100, 12, 31),
                    help_text="Chọn ngày",
                    cancel_text="Hủy",
                    confirm_text="Chọn",
                    on_change=on_change,
                )
            )

        return ft.DataCell(
            ft.Row(
                spacing=2,
                controls=[
                    display,
                    ft.IconButton(
                        icon=ft.Icons.CALENDAR_MONTH,
                        tooltip="Chọn ngày",
                        on_click=open_picker,
                    ),
                ],
            )
        )

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
        return ft.DataCell(control)

    def paper_inline_cell(record: dict, paper_format) -> ft.DataCell:
        current = dict(record["paper_statuses"].get(paper_format.code) or {})
        saved = {
            "scan_status": current.get("scan_status", "UNKNOWN"),
            "quantity": str(current.get("scan_pages", 0) or current.get("check_pages", 0) or 0),
        }
        status = ft.Dropdown(
            dense=True,
            width=150,
            value=saved["scan_status"],
            options=[
                ft.dropdown.Option(key=key, text=label)
                for key, label in PAPER_STATUS_LABELS.items()
            ],
        )
        quantity = ft.TextField(
            value=saved["quantity"],
            dense=True,
            width=76,
            label="SL",
            keyboard_type=ft.KeyboardType.NUMBER,
            content_padding=ft.Padding.symmetric(vertical=6, horizontal=8),
        )

        def commit(_event=None) -> None:
            next_values = {
                "scan_status": status.value or "UNKNOWN",
                "quantity": quantity.value or "0",
            }
            if next_values == saved:
                return

            def mutate(values: dict) -> None:
                for item in values["paper_statuses"]:
                    if int(item["paper_format_id"]) == int(paper_format.id):
                        item["scan_status"] = next_values["scan_status"]
                        item["scan_pages"] = next_values["quantity"]
                        item["check_pages"] = next_values["quantity"]
                        return

            ok = save_inline(
                record,
                mutate,
                message=f"Đã lưu {paper_format.code} cho {record['record_key']}.",
            )
            if ok:
                saved.update(next_values)
            else:
                status.value = saved["scan_status"]
                quantity.value = saved["quantity"]

        return ft.DataCell(
            ft.Row(
                spacing=6,
                controls=[
                    status,
                    quantity,
                    ft.IconButton(
                        icon=ft.Icons.SAVE,
                        tooltip="Lưu khổ giấy",
                        on_click=commit,
                    ),
                ],
            )
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
    records, total_rows = ctx.db.list_system_records_page(
        ctx.project_id,
        limit=PAGE_SIZE,
        offset=page_index * PAGE_SIZE,
        search=state["search"],
    )
    paper_formats = ctx.db.list_paper_formats(ctx.project_id, enabled_only=True)
    directory_levels = ctx.db.list_directory_levels(ctx.project_id)
    personnel = ctx.db.list_personnel(ctx.project_id, enabled_only=True)
    clients = ctx.db.list_clients(ctx.project_id)
    add_fields: list[ft.TextField] = []

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
            "record_status": workflow.get("record_status", "NOT_STARTED"),
            "notes": workflow.get("notes", ""),
            "paper_statuses": [
                {
                    "paper_format_id": paper["paper_format_id"],
                    "scanner_id": paper.get("scanner_id"),
                    "scan_date": paper.get("scan_date", ""),
                    "scan_status": paper["scan_status"],
                    "scan_pages": str(paper["scan_pages"]),
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

    def build_add_panel() -> ft.Control:
        add_fields.clear()
        client_dropdown = ft.Dropdown(
            label="Máy nhận hồ sơ cứng",
            dense=True,
            width=240,
            value=state["new_record"].get("client_code", ""),
            options=[
                ft.dropdown.Option(key="", text="-- Chưa chọn --"),
                *[
                    ft.dropdown.Option(
                        key=client.client_code,
                        text=f"{client.client_code} - {client.share_path}",
                    )
                    for client in clients
                    if client.enabled
                ],
            ],
        )
        client_dropdown.on_change = lambda event: state["new_record"].__setitem__(
            "client_code", event.control.value or ""
        )
        controls: list[ft.Control] = [client_dropdown]
        for key, label in new_record_keys():
            field = ft.TextField(
                label=label,
                value=state["new_record"].get(key, ""),
                dense=True,
                width=170,
                content_padding=ft.Padding.symmetric(vertical=7, horizontal=10),
                on_change=lambda event, current_key=key: state["new_record"].__setitem__(
                    current_key, event.control.value or ""
                ),
            )
            add_fields.append(field)
            controls.append(field)

        def add_record(_event=None) -> None:
            if directory_levels:
                parts = [
                    (state["new_record"].get(f"level_{index}", "") or "").strip()
                    for index, _level in enumerate(directory_levels)
                ]
            else:
                raw_key = (state["new_record"].get("record_key", "") or "").strip()
                parts = [part for part in raw_key.replace("\\", "/").split("/") if part]
            try:
                ctx.mapfiles.add_manual_record(
                    ctx.project_id,
                    parts,
                    client_code=(state["new_record"].get("client_code") or "").strip() or None,
                )
            except ValueError as exc:
                status_banner.value = str(exc)
                status_banner.color = ft.Colors.ERROR
                ctx.page.update()
                return
            state["new_record"] = {}
            state["adding"] = False
            state["flash"] = "Đã thêm dòng mapfile mới."
            state["page"] = 0
            ctx.refresh()

        return ft.Container(
            padding=12,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            content=ft.Row(
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
                controls=[
                    *controls,
                    ft.FilledButton("Lưu dòng", icon=ft.Icons.SAVE, on_click=add_record),
                    ft.TextButton(
                        "Hủy",
                        on_click=lambda _e: (
                            state.__setitem__("adding", False),
                            state.__setitem__("new_record", {}),
                            ctx.refresh(),
                        ),
                    ),
                ],
            ),
        )

    def paper_scan_cell(record: dict, paper_format) -> ft.DataCell:
        current = dict(record["paper_statuses"].get(paper_format.code) or {})
        saved = {
            "scanner_id": str(current.get("scanner_id") or ""),
            "scan_date": current.get("scan_date", "") or "",
            "scan_pages": str(current.get("scan_pages", 0) or 0),
        }
        scanner = ft.Dropdown(
            dense=True,
            width=180,
            value=saved["scanner_id"],
            options=[
                ft.dropdown.Option(key="", text="--"),
                *[
                    ft.dropdown.Option(key=str(person.id), text=f"{person.personnel_code} - {person.full_name}")
                    for person in personnel
                    if person.id is not None
                ],
            ],
        )
        scan_date = ft.TextField(
            value=saved["scan_date"],
            dense=True,
            width=112,
            hint_text="YYYY-MM-DD",
            content_padding=ft.Padding.symmetric(vertical=6, horizontal=8),
        )
        pages = ft.TextField(
            value=saved["scan_pages"],
            dense=True,
            width=76,
            label="Trang",
            keyboard_type=ft.KeyboardType.NUMBER,
            content_padding=ft.Padding.symmetric(vertical=6, horizontal=8),
        )

        def commit(_event=None) -> None:
            next_values = {
                "scanner_id": scanner.value or "",
                "scan_date": scan_date.value or "",
                "scan_pages": pages.value or "0",
            }
            if next_values == saved:
                return

            def mutate(values: dict) -> None:
                for item in values["paper_statuses"]:
                    if int(item["paper_format_id"]) == int(paper_format.id):
                        item["scanner_id"] = next_values["scanner_id"] or None
                        item["scan_date"] = next_values["scan_date"]
                        item["scan_pages"] = next_values["scan_pages"]
                        item["scan_status"] = (
                            "SCANNED" if int(next_values["scan_pages"] or "0") > 0 else "UNKNOWN"
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
                scan_date.value = saved["scan_date"]
                pages.value = saved["scan_pages"]

        return ft.DataCell(
            ft.Row(
                spacing=6,
                controls=[
                    scanner,
                    scan_date,
                    pages,
                    ft.IconButton(icon=ft.Icons.SAVE, tooltip=f"Lưu Scan {paper_format.code}", on_click=commit),
                ],
            )
        )

    def paper_check_pages_cell(record: dict, paper_format) -> ft.DataCell:
        current = dict(record["paper_statuses"].get(paper_format.code) or {})
        saved = {"check_pages": str(current.get("check_pages", 0) or 0)}
        pages = ft.TextField(
            value=saved["check_pages"],
            dense=True,
            width=76,
            keyboard_type=ft.KeyboardType.NUMBER,
            content_padding=ft.Padding.symmetric(vertical=6, horizontal=8),
        )

        def commit(_event=None) -> None:
            next_value = pages.value or "0"
            if next_value == saved["check_pages"]:
                return

            def mutate(values: dict) -> None:
                for item in values["paper_statuses"]:
                    if int(item["paper_format_id"]) == int(paper_format.id):
                        item["check_pages"] = next_value
                        return

            ok = save_inline(
                record,
                mutate,
                message=f"Đã lưu Check {paper_format.code} cho {record['record_key']}.",
            )
            if ok:
                saved["check_pages"] = next_value
            else:
                pages.value = saved["check_pages"]

        return ft.DataCell(
            ft.Row(
                spacing=4,
                controls=[
                    pages,
                    ft.IconButton(icon=ft.Icons.SAVE, tooltip=f"Lưu Check {paper_format.code}", on_click=commit),
                ],
            )
        )

    columns = [ft.DataColumn(ft.Text("STT"), numeric=True)]
    if directory_levels:
        columns.extend(
            ft.DataColumn(ft.Text(level.display_name)) for level in directory_levels
        )
    else:
        columns.append(ft.DataColumn(ft.Text("Mã hồ sơ")))
    columns.extend(
        [
            *[
                ft.DataColumn(ft.Text(f"{paper_format.code}: Người Scan / Ngày Scan / Số Trang"))
                for paper_format in paper_formats
            ],
            ft.DataColumn(ft.Text("Người Check")),
            *[
                ft.DataColumn(ft.Text(f"Check {paper_format.code}"))
                for paper_format in paper_formats
            ],
            ft.DataColumn(ft.Text("Trạng thái hồ sơ")),
            ft.DataColumn(ft.Text("Tình trạng backup")),
            ft.DataColumn(ft.Text("Máy đang lưu")),
            ft.DataColumn(ft.Text("Thao tác")),
        ]
    )

    data_rows = []
    for row_offset, record in enumerate(records):
        record_parts = record["record_key"].replace("\\", "/").split("/")
        cells = [
            ft.DataCell(ft.Text(str(page_index * PAGE_SIZE + row_offset + 1)))
        ]
        if directory_levels:
            for index, _level in enumerate(directory_levels):
                value = record_parts[index] if index < len(record_parts) else "—"
                if index == len(directory_levels) - 1 and len(record_parts) > len(directory_levels):
                    value = "/".join(record_parts[index:])
                cells.append(ft.DataCell(ft.Text(value)))
        else:
            cells.append(
                ft.DataCell(
                    ft.Text(
                        record["record_key"],
                        max_lines=2,
                        tooltip=record["record_key"],
                    )
                )
            )
        cells.extend(
            [
                *[
                    paper_scan_cell(record, paper_format)
                    for paper_format in paper_formats
                ],
                personnel_cell(record, "checker_id", record["checker_id"]),
                *[
                    paper_check_pages_cell(record, paper_format)
                    for paper_format in paper_formats
                ],
                record_status_cell(record),
                ft.DataCell(
                    _badge(
                        BACKUP_STATUS_LABELS.get(
                            record["backup_status"], record["backup_status"]
                        ),
                        BACKUP_STATUS_COLORS.get(
                            record["backup_status"], "#9CA3AF"
                        ),
                    )
                ),
                ft.DataCell(ft.Text(record["client_codes"] or "—")),
                ft.DataCell(
                    ft.Row(
                        spacing=2,
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
                    )
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

    table = ft.DataTable(columns=columns, rows=data_rows)
    toolbar = ft.Row(
        spacing=8,
        wrap=True,
        controls=[
            ft.FilledButton(
                "Thêm dòng",
                icon=ft.Icons.ADD,
                on_click=lambda _e: (
                    state.__setitem__("adding", True),
                    ctx.refresh(),
                ),
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
            ft.IconButton(
                icon=ft.Icons.REFRESH,
                tooltip="Làm mới dữ liệu",
                on_click=lambda _e: ctx.refresh(),
            ),
            status_banner,
        ],
    )

    add_panel = build_add_panel() if state["adding"] else None
    if not records:
        empty_text = ft.Text(
            "Không tìm thấy hồ sơ phù hợp."
            if state["search"]
            else "Hệ thống chưa ghi nhận hồ sơ nào cho dự án này.",
            color=ft.Colors.ON_SURFACE_VARIANT,
        )
        body: ft.Control = ft.Column(
            spacing=8,
            controls=[*([add_panel] if add_panel else []), empty_text],
        )
    else:
        start_row = page_index * PAGE_SIZE + 1
        end_row = start_row + len(records) - 1
        body = ft.Column(
            expand=True,
            spacing=8,
            controls=[
                *([add_panel] if add_panel else []),
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(
                            f"Hiển thị {start_row}–{end_row} trong {total_rows} hồ sơ",
                            size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        ft.Row(
                            spacing=2,
                            controls=[
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
                                    disabled=(page_index + 1) * PAGE_SIZE >= total_rows,
                                    on_click=lambda _e: change_page(1),
                                ),
                            ],
                        ),
                    ],
                ),
                ft.Row(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[table],
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
                color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            toolbar,
            body,
        ],
    )
