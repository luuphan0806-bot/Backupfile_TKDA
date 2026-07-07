from __future__ import annotations

import asyncio
import json
from pathlib import Path

import flet as ft

from ...theme import DANGER, SUCCESS, WARNING, status_label
from ...workers import run_worker

FILTER_ALL = "all"
FILTER_NOT_DONE = "not_done"
FILTER_DONE_PENDING = "done_pending"
FILTER_MATCHED = "matched"
FILTER_MISSING = "missing"


def _status_badge(status: str) -> ft.Control:
    color = SUCCESS if status == "MATCHED" else DANGER if status == "MISSING" else WARNING
    return ft.Container(
        padding=ft.Padding.symmetric(vertical=2, horizontal=8),
        border_radius=999,
        bgcolor=ft.Colors.with_opacity(0.15, color),
        content=ft.Text(status_label(status), size=11, color=color, weight=ft.FontWeight.BOLD),
    )


def build(ctx) -> ft.Control:
    db = ctx.db
    project_id = ctx.project_id

    status_banner = ft.Text("", color=ft.Colors.PRIMARY)
    state = ctx.view_state.setdefault(
        "mapfile", {"filter": FILTER_ALL, "search": "", "page": 0}
    )
    state.setdefault("flash", "")
    status_banner.value = state.get("flash", "")
    search_field = ft.TextField(
        label="Tìm kiếm", width=260, dense=True, value=state["search"]
    )
    active_filter = {"value": state["filter"]}

    def set_busy(message: str) -> None:
        status_banner.value = message
        status_banner.color = ft.Colors.PRIMARY
        ctx.page.update()

    def set_done(message: str, *, failed: bool = False) -> None:
        status_banner.value = message
        status_banner.color = ft.Colors.ERROR if failed else ft.Colors.PRIMARY
        ctx.refresh()

    picker = ft.FilePicker()

    async def do_import(_event) -> None:
        result = await picker.pick_files(
            dialog_title="Chọn file mapfile Excel", allowed_extensions=["xlsx", "xlsm"]
        )
        if not result:
            return
        file_path = result[0].path
        set_busy("Đang nhập mapfile...")
        run_worker(
            ctx.page,
            lambda: ctx.mapfiles.import_excel(project_id, Path(file_path)),
            on_success=lambda _r: set_done("Đã nhập mapfile."),
            on_error=lambda err: set_done(f"Nhập mapfile thất bại:\n{err}", failed=True),
        )

    import_id = db.latest_mapfile_import_id(project_id)
    page_size = 50
    filter_value = active_filter["value"]
    status_filter = FILTER_MATCHED.upper() if filter_value == FILTER_MATCHED else (
        FILTER_MISSING.upper() if filter_value == FILTER_MISSING else None
    )
    done_filter = False if filter_value == FILTER_NOT_DONE else (
        True if filter_value == FILTER_DONE_PENDING else None
    )
    exclude_status = "MATCHED" if filter_value == FILTER_DONE_PENDING else None
    rows, total_rows = db.list_mapfile_rows_page(
        import_id,
        limit=page_size,
        offset=int(state["page"]) * page_size,
        status=status_filter,
        exclude_status=exclude_status,
        done=done_filter,
        search=state["search"],
    ) if import_id else ([], 0)

    headers: list[str] = []
    raw_by_row: dict[int, dict[str, str]] = {}
    for row in rows:
        raw = json.loads(row["raw_json"])
        raw_by_row[row["id"]] = raw
        for key in raw:
            if key not in headers:
                headers.append(key)

    def matches_filter(row) -> bool:
        value = active_filter["value"]
        if value == FILTER_NOT_DONE:
            return not row["is_done"]
        if value == FILTER_DONE_PENDING:
            return bool(row["is_done"]) and row["status"] != "MATCHED"
        if value == FILTER_MATCHED:
            return row["status"] == "MATCHED"
        if value == FILTER_MISSING:
            return row["status"] == "MISSING"
        return True

    def matches_search(row) -> bool:
        query = (search_field.value or "").strip().lower()
        if not query:
            return True
        haystack = " ".join(raw_by_row.get(row["id"], {}).values()) + " " + row["expected_relative_path"]
        return query in haystack.lower()

    def toggle_done(row_id: int, value: bool) -> None:
        if value:
            db.mark_mapfile_row_done(row_id, None)
        else:
            db.unmark_mapfile_row_done(row_id)
        # No ctx.refresh() here on purpose: the checkbox already reflects the
        # new value instantly on its own, and this is the highest-frequency
        # click in the console -- rebuilding the whole tab (re-query, toolbar,
        # filters, table) on every tick would be the heaviest interaction in
        # the app. The row falls in line with the active filter next time the
        # user changes filter/page/search, which already calls ctx.refresh().

    def save_cell(
        row_id: int,
        row_number: int,
        column_name: str,
        saved_value: dict[str, str],
        control: ft.TextField,
    ) -> None:
        new_value = control.value or ""
        if new_value == saved_value["value"]:
            return
        try:
            ctx.mapfiles.update_row_cell(project_id, row_id, column_name, new_value)
        except Exception as exc:  # noqa: BLE001 - show validation/storage errors in UI
            control.value = saved_value["value"]
            status_banner.value = f"Không thể lưu dòng {row_number}: {exc}"
            status_banner.color = ft.Colors.ERROR
            ctx.page.update()
            return
        saved_value["value"] = new_value
        state["flash"] = f"Đã lưu dòng {row_number}, cột {column_name}."
        ctx.refresh()

    def editable_cell(row, column_name: str, value: str) -> ft.DataCell:
        saved_value = {"value": value}
        field = ft.TextField(
            value=value,
            dense=True,
            width=max(120, min(260, len(value) * 8 + 40)),
            content_padding=ft.Padding.symmetric(vertical=6, horizontal=8),
        )
        field.on_submit = lambda _e, c=field: save_cell(
            row["id"], row["row_number"], column_name, saved_value, c
        )
        field.on_blur = lambda _e, c=field: save_cell(
            row["id"], row["row_number"], column_name, saved_value, c
        )
        return ft.DataCell(field)

    filtered_rows = rows

    columns = [ft.DataColumn(ft.Text("#"))]
    columns.extend(ft.DataColumn(ft.Text(header)) for header in headers)
    columns.append(ft.DataColumn(ft.Text("Trạng thái hệ thống")))
    columns.append(ft.DataColumn(ft.Text("Đã quét xong")))

    data_rows = []
    for row in filtered_rows[:200]:
        raw = raw_by_row.get(row["id"], {})
        cells = [ft.DataCell(ft.Text(str(row["row_number"])))]
        cells.extend(
            editable_cell(row, header, raw.get(header, "")) for header in headers
        )
        cells.append(ft.DataCell(_status_badge(row["status"])))
        cells.append(
            ft.DataCell(
                ft.Checkbox(
                    value=bool(row["is_done"]),
                    on_change=lambda e, rid=row["id"]: toggle_done(rid, e.control.value),
                )
            )
        )
        data_rows.append(ft.DataRow(cells=cells))

    table = ft.DataTable(columns=columns, rows=data_rows)

    def filter_button(label: str, value: str) -> ft.Control:
        selected = active_filter["value"] == value

        def on_click(_e) -> None:
            active_filter["value"] = value
            state["filter"] = value
            state["page"] = 0
            ctx.refresh()

        return (ft.FilledButton if selected else ft.OutlinedButton)(label, on_click=on_click)

    filter_bar = ft.Row(
        spacing=8, wrap=True,
        controls=[
            filter_button("Tất cả", FILTER_ALL),
            filter_button("Chưa quét xong", FILTER_NOT_DONE),
            filter_button("Đã quét xong", FILTER_DONE_PENDING),
            filter_button("Đã khớp", FILTER_MATCHED),
            filter_button("Thiếu", FILTER_MISSING),
        ],
    )

    search_generation = {"value": 0}

    def on_search(event) -> None:
        # Debounced: typing a whole search term used to trigger a full tab
        # rebuild + paginated DB query per keystroke. Wait for a short pause
        # in typing instead, and drop any stale/superseded runs.
        text = event.control.value or ""
        search_generation["value"] += 1
        this_generation = search_generation["value"]

        async def apply_after_pause() -> None:
            await asyncio.sleep(0.35)
            if search_generation["value"] != this_generation:
                return
            state["search"] = text
            state["page"] = 0
            ctx.refresh()

        ctx.page.run_task(apply_after_pause)

    search_field.on_change = on_search

    toolbar = ft.Row(
        spacing=10,
        controls=[
            ft.FilledButton("Nhập danh mục Excel", icon=ft.Icons.UPLOAD_FILE, on_click=do_import),
            search_field,
            status_banner,
        ],
    )

    if not rows:
        body: ft.Control = ft.Text(
            "Chưa có mapfile nào được nhập cho dự án này. Bấm \"Nhập mapfile\" để bắt đầu.",
            color=ft.Colors.ON_SURFACE_VARIANT,
        )
    else:
        body = ft.Column(
            expand=True, scroll=ft.ScrollMode.AUTO,
            controls=[
                filter_bar,
                ft.Row(controls=[
                    ft.Text(
                        f"Trang {int(state['page']) + 1} · {total_rows} hồ sơ",
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.CHEVRON_LEFT,
                        disabled=int(state["page"]) <= 0,
                        on_click=lambda _e: (
                            state.__setitem__("page", max(0, int(state["page"]) - 1)),
                            ctx.refresh(),
                        ),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.CHEVRON_RIGHT,
                        disabled=(int(state["page"]) + 1) * page_size >= total_rows,
                        on_click=lambda _e: (
                            state.__setitem__("page", int(state["page"]) + 1),
                            ctx.refresh(),
                        ),
                    ),
                ]),
                table,
            ],
        )

    return ft.Column(
        expand=True,
        spacing=16,
        controls=[
            ft.Text(
                "Đối chiếu danh sách hồ sơ trong file Excel với dữ liệu đã backup thực tế. "
                "Nhân sự xác nhận \"Đã quét xong\" để theo dõi tiến độ. Dịch vụ tự động sao lưu theo lịch.",
                size=13, color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            toolbar,
            body,
        ],
    )
