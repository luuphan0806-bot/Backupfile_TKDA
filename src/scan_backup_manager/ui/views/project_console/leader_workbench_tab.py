from __future__ import annotations

from datetime import date

import flet as ft

from ... import kit
from ...date_format import DISPLAY_DATE_HINT, display_to_iso, iso_to_display
from ...theme import DANGER, SUCCESS, TEXT_MUTED, WARNING


def _kind_label(kind: str) -> str:
    return "Check" if kind == "CHECK" else "Scan"


def _attendance_color(status: str) -> str:
    return {
        "APPROVED": SUCCESS,
        "PENDING": WARNING,
        "REJECTED": DANGER,
        "VOID": TEXT_MUTED,
    }.get(status, TEXT_MUTED)


def _ready_label(row) -> tuple[str, str]:
    if row["status"] == "APPROVED":
        return "Đã duyệt", SUCCESS
    if row["task_status"] != "COMPLETED":
        return "Chưa chốt việc", WARNING
    if row["task_kind"] == "SCAN":
        return ("Đủ điều kiện", SUCCESS) if row["has_scan_backup"] else ("Thiếu backup", DANGER)
    if row["record_status"] == "COMPLETED" and (row["check_pages"] or row["check_files"]):
        return "Đủ điều kiện", SUCCESS
    return "Thiếu kết quả check", DANGER


def build(ctx) -> ft.Control:
    state = ctx.view_state.setdefault(
        "leader_workbench",
        {"work_date": date.today().isoformat(), "message": ""},
    )
    date_field = ft.TextField(
        label=f"Ngày công ({DISPLAY_DATE_HINT})",
        value=iso_to_display(state["work_date"]),
        dense=True,
        width=180,
    )
    message = ft.Text(state.get("message", ""), color=TEXT_MUTED)

    def load_rows() -> list:
        work_date = state["work_date"]
        return ctx.db.list_attendance_entries(ctx.project_id, work_date, work_date)

    rows = load_rows()
    pending_rows = [row for row in rows if row["status"] == "PENDING"]
    approved_rows = [row for row in rows if row["status"] == "APPROVED"]
    rejected_rows = [row for row in rows if row["status"] in {"REJECTED", "VOID"}]
    ready_rows = [
        row for row in pending_rows
        if _ready_label(row)[0] == "Đủ điều kiện"
    ]

    def set_message(text: str, *, failed: bool = False) -> None:
        state["message"] = text
        message.value = text
        message.color = DANGER if failed else SUCCESS
        ctx.page.update()

    def refresh(_event=None) -> None:
        try:
            state["work_date"] = display_to_iso(date_field.value)
        except ValueError as exc:
            set_message(str(exc), failed=True)
            return
        ctx.refresh()

    date_field.on_submit = refresh

    def approve(entry_id: int) -> None:
        try:
            ctx.db.approve_attendance_entry(entry_id)
        except ValueError as exc:
            set_message(str(exc), failed=True)
            return
        state["message"] = f"Đã duyệt công #{entry_id}."
        ctx.refresh()

    def approve_all(_event=None) -> None:
        approved = 0
        errors: list[str] = []
        for row in ready_rows:
            try:
                ctx.db.approve_attendance_entry(int(row["id"]))
                approved += 1
            except ValueError as exc:
                errors.append(str(exc))
        if errors:
            state["message"] = f"Đã duyệt {approved} dòng; {len(errors)} dòng lỗi."
        else:
            state["message"] = f"Đã duyệt {approved} dòng đủ điều kiện."
        ctx.refresh()

    def open_override(row) -> None:
        quantity = ft.TextField(label="Sản lượng tính công", value=str(row["quantity"]), width=180)
        completed = ft.TextField(label="Số đã chốt", value=str(row["completed_count"]), width=160)
        reason = ft.TextField(label="Lý do override", multiline=True, min_lines=2, width=420)
        error = ft.Text("", color=DANGER)

        def submit(_event=None) -> None:
            try:
                ctx.db.approve_attendance_entry(
                    int(row["id"]),
                    quantity=int(quantity.value or 0),
                    completed_count=int(completed.value or 0),
                    override_reason=reason.value or "",
                )
            except ValueError as exc:
                error.value = str(exc)
                ctx.page.update()
                return
            ctx.page.pop_dialog()
            state["message"] = f"Đã duyệt override #{row['id']}."
            ctx.refresh()

        ctx.page.open(
            kit.dialog(
                f"Override công #{row['id']}",
                ft.Column(
                    tight=True,
                    spacing=10,
                    controls=[
                        ft.Text(row["record_key"], color=TEXT_MUTED),
                        ft.Row([quantity, completed], spacing=8),
                        reason,
                        error,
                    ],
                ),
                [
                    kit.ghost_button("Hủy", on_click=lambda _e: ctx.page.pop_dialog()),
                    kit.primary_button("Duyệt override", on_click=submit),
                ],
                width=460,
            )
        )

    def open_reject(row) -> None:
        reason = ft.TextField(label="Lý do không tính công", multiline=True, min_lines=2, width=420)
        error = ft.Text("", color=DANGER)

        def submit(_event=None) -> None:
            try:
                ctx.db.reject_attendance_entry(int(row["id"]), reason=reason.value or "")
            except ValueError as exc:
                error.value = str(exc)
                ctx.page.update()
                return
            ctx.page.pop_dialog()
            state["message"] = f"Đã loại khỏi bảng công #{row['id']}."
            ctx.refresh()

        ctx.page.open(
            kit.dialog(
                f"Không tính công #{row['id']}",
                ft.Column(
                    tight=True,
                    spacing=10,
                    controls=[ft.Text(row["record_key"], color=TEXT_MUTED), reason, error],
                ),
                [
                    kit.ghost_button("Hủy", on_click=lambda _e: ctx.page.pop_dialog()),
                    kit.primary_button("Không tính công", on_click=submit),
                ],
                width=460,
            )
        )

    def row_cells(row) -> list[ft.DataCell]:
        ready_text, ready_color = _ready_label(row)
        actions: list[ft.Control] = []
        if row["status"] == "PENDING":
            actions = [
                ft.IconButton(
                    icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                    tooltip="Duyệt nếu đủ điều kiện",
                    icon_color=SUCCESS,
                    on_click=lambda _e, entry_id=int(row["id"]): approve(entry_id),
                ),
                ft.IconButton(
                    icon=ft.Icons.EDIT_NOTE,
                    tooltip="Duyệt override",
                    icon_color=WARNING,
                    on_click=lambda _e, item=row: open_override(item),
                ),
                ft.IconButton(
                    icon=ft.Icons.BLOCK,
                    tooltip="Không tính công",
                    icon_color=DANGER,
                    on_click=lambda _e, item=row: open_reject(item),
                ),
            ]
        return [
            ft.DataCell(ft.Text(str(row["id"]))),
            ft.DataCell(ft.Text(row["full_name"], max_lines=1)),
            ft.DataCell(ft.Text(_kind_label(row["task_kind"]))),
            ft.DataCell(ft.Text(row["job_title"], max_lines=1)),
            ft.DataCell(ft.Text(row["record_key"], max_lines=1)),
            ft.DataCell(ft.Text(str(row["quantity"]))),
            ft.DataCell(ft.Text(str(row["completed_count"]))),
            ft.DataCell(kit.badge(row["status"], _attendance_color(row["status"]))),
            ft.DataCell(kit.badge(ready_text, ready_color)),
            ft.DataCell(ft.Row(spacing=0, controls=actions)),
        ]

    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("#")),
            ft.DataColumn(ft.Text("Nhân sự")),
            ft.DataColumn(ft.Text("Loại")),
            ft.DataColumn(ft.Text("Công việc")),
            ft.DataColumn(ft.Text("Hồ sơ")),
            ft.DataColumn(ft.Text("SL")),
            ft.DataColumn(ft.Text("Chốt")),
            ft.DataColumn(ft.Text("Công")),
            ft.DataColumn(ft.Text("Nghiệm thu")),
            ft.DataColumn(ft.Text("")),
        ],
        rows=[ft.DataRow(cells=row_cells(row)) for row in rows],
    )

    kpis = ft.Row(
        spacing=12,
        controls=[
            kit.stat_tile("Chờ duyệt", len(pending_rows), WARNING, icon=ft.Icons.PENDING_ACTIONS),
            kit.stat_tile("Đủ điều kiện", len(ready_rows), SUCCESS, icon=ft.Icons.RULE),
            kit.stat_tile("Đã duyệt", len(approved_rows), SUCCESS, icon=ft.Icons.CHECK_CIRCLE),
            kit.stat_tile("Không tính", len(rejected_rows), DANGER, icon=ft.Icons.BLOCK),
        ],
    )

    return ft.Column(
        expand=True,
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            kit.page_header(
                "Leader Workbench",
                "Điều phối và chốt công theo ngày trước khi xuất bảng công.",
                eyebrow_text="Attendance Ledger",
                actions=[
                    kit.primary_button("Duyệt dòng đủ điều kiện", icon=ft.Icons.DONE_ALL, on_click=approve_all),
                    kit.ghost_button("Làm mới", icon=ft.Icons.REFRESH, on_click=refresh),
                ],
            ),
            kit.card(
                ft.Row(
                    spacing=10,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[date_field, kit.primary_button("Xem ngày", icon=ft.Icons.SEARCH, on_click=refresh), message],
                ),
                padding=14,
                radius=8,
            ),
            kpis,
            kit.table_frame(table) if rows else ft.Text("Chưa có dòng công nào trong ngày này.", color=TEXT_MUTED),
        ],
    )
