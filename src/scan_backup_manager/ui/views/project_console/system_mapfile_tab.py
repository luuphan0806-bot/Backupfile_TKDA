from __future__ import annotations

import os
from pathlib import Path

import flet as ft

from ... import kit
from ...theme import DANGER, INFO, LINE, SUCCESS, WARNING, TEXT_MUTED


PAGE_SIZE = 50
PAPER_CELL_WIDTH = 178
# Each Scan/Check cell stacks up to three labelled Material fields. A field
# with a floating label needs ~48-52px of height or the label collides with
# its value (the "chồng chéo" seen in the A4/A3/A0 columns). The row height
# must in turn fit three such fields plus spacing so nothing clips into the
# next row: 3*52 + 2*6 spacing + 2*6 container padding = 180, rounded up.
PAPER_FIELD_HEIGHT = 52
PAPER_TABLE_ROW_HEIGHT = 210
PAPER_SAVE_BUTTON_SIZE = PAPER_FIELD_HEIGHT

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
            "check_pages": workflow.get("check_pages", 0),
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
                check_pages=values["check_pages"],
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
        return ft.DataCell(control)

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
            "check_pages": workflow.get("check_pages", 0),
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
            check_pages=payload["check_pages"],
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
            border=ft.Border.all(1, LINE),
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
            width=158,
            height=PAPER_FIELD_HEIGHT,
            value=saved["scanner_id"],
            label="Người Scan",
            content_padding=ft.Padding.symmetric(vertical=4, horizontal=8),
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
            width=158,
            height=PAPER_FIELD_HEIGHT,
            label="Ngày Scan",
            hint_text="YYYY-MM-DD",
            content_padding=ft.Padding.symmetric(vertical=4, horizontal=8),
        )
        pages = ft.TextField(
            value=saved["scan_pages"],
            dense=True,
            height=PAPER_FIELD_HEIGHT,
            width=92,
            label="Số Trang",
            keyboard_type=ft.KeyboardType.NUMBER,
            content_padding=ft.Padding.symmetric(vertical=4, horizontal=8),
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
            ft.Container(
                width=PAPER_CELL_WIDTH,
                height=PAPER_TABLE_ROW_HEIGHT - 14,
                padding=ft.Padding.symmetric(vertical=6, horizontal=0),
                content=ft.Column(
                    spacing=6,
                    tight=True,
                    controls=[
                        scanner,
                        ft.Row(
                            spacing=4,
                            controls=[
                                pages,
                                ft.IconButton(
                                    icon=ft.Icons.SAVE,
                                    icon_size=18,
                                    width=PAPER_SAVE_BUTTON_SIZE,
                                    height=PAPER_SAVE_BUTTON_SIZE,
                                    padding=0,
                                    tooltip=f"Lưu Scan {paper_format.code}",
                                    on_click=commit,
                                ),
                            ],
                        ),
                        scan_date,
                    ],
                ),
            )
        )

    def check_cell(record: dict) -> ft.DataCell:
        saved = {
            "checker_id": str(record.get("checker_id") or ""),
            "check_pages": str(record.get("check_pages", 0) or 0),
        }
        checker = ft.Dropdown(
            dense=True,
            width=158,
            height=PAPER_FIELD_HEIGHT,
            value=saved["checker_id"],
            label="Người Check",
            content_padding=ft.Padding.symmetric(vertical=4, horizontal=8),
            options=[
                ft.dropdown.Option(key="", text="--"),
                *[
                    ft.dropdown.Option(key=str(person.id), text=f"{person.personnel_code} - {person.full_name}")
                    for person in personnel
                    if person.id is not None
                ],
            ],
        )
        pages = ft.TextField(
            value=saved["check_pages"],
            dense=True,
            height=PAPER_FIELD_HEIGHT,
            width=92,
            label="Số Trang",
            keyboard_type=ft.KeyboardType.NUMBER,
            content_padding=ft.Padding.symmetric(vertical=4, horizontal=8),
        )

        def commit(_event=None) -> None:
            next_values = {
                "checker_id": checker.value or "",
                "check_pages": pages.value or "0",
            }
            if next_values == saved:
                return

            def mutate(values: dict) -> None:
                values["checker_id"] = optional_personnel_id(next_values["checker_id"])
                values["check_pages"] = next_values["check_pages"]

            ok = save_inline(
                record,
                mutate,
                message=f"Đã lưu Check hồ sơ {record['record_key']}.",
            )
            if ok:
                saved.update(next_values)
            else:
                checker.value = saved["checker_id"]
                pages.value = saved["check_pages"]

        return ft.DataCell(
            ft.Container(
                width=PAPER_CELL_WIDTH,
                height=PAPER_TABLE_ROW_HEIGHT - 14,
                padding=ft.Padding.symmetric(vertical=6, horizontal=0),
                content=ft.Column(
                    spacing=6,
                    tight=True,
                    controls=[
                        checker,
                        ft.Row(
                            spacing=4,
                            controls=[
                                pages,
                                ft.IconButton(
                                    icon=ft.Icons.SAVE,
                                    icon_size=18,
                                    width=PAPER_SAVE_BUTTON_SIZE,
                                    height=PAPER_SAVE_BUTTON_SIZE,
                                    padding=0,
                                    tooltip="Lưu Check hồ sơ",
                                    on_click=commit,
                                ),
                            ],
                        ),
                    ],
                ),
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
                ft.DataColumn(ft.Text(f"Scan {paper_format.code}"))
                for paper_format in paper_formats
            ],
            ft.DataColumn(ft.Text("Check hồ sơ")),
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
                check_cell(record),
                record_status_cell(record),
                ft.DataCell(
                    kit.badge(
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

    table = ft.DataTable(
        columns=columns,
        rows=data_rows,
        data_row_min_height=PAPER_TABLE_ROW_HEIGHT,
        data_row_max_height=PAPER_TABLE_ROW_HEIGHT,
        heading_row_height=48,
        column_spacing=12,
        horizontal_margin=8,
    )
    kit.style_table(table)
    toolbar = kit.card(ft.Row(
        spacing=8,
        wrap=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
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
    ), padding=12)

    add_panel = build_add_panel() if state["adding"] else None
    if not records:
        empty_text = ft.Text(
            "Không tìm thấy hồ sơ phù hợp."
            if state["search"]
            else "Hệ thống chưa ghi nhận hồ sơ nào cho dự án này.",
            color=TEXT_MUTED,
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
                            color=TEXT_MUTED,
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
