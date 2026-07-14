from __future__ import annotations

from datetime import date

import flet as ft

from ... import kit
from ....db import ATTENDANCE_TYPES
from ...date_format import DISPLAY_DATE_HINT, display_to_iso, iso_to_display
from ...theme import DANGER, SUCCESS, TEXT_MUTED, WARNING


def _hours_text(row) -> str:
    hours = row["work_hours"] or 0
    if hours:
        return f"{hours:g}h"
    if row["start_time"]:
        return f"{row['start_time']}–{row['finish_time']}"
    return ""


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

    # Which job types are done outside the app (no productivity captured): the
    # volume is entered by hand instead of read from scan/check data.
    off_app_jobs = {
        (job.display_name or "").strip().lower(): bool(job.off_app)
        for job in ctx.db.list_job_types(ctx.project_id)
    }

    def slot_job_name(entries: list) -> str:
        rep = entries[0]
        return (rep["job_content"] or rep["job_title"] or "").strip()

    def slot_job_key(entry) -> str:
        return (entry["job_title"] or entry["job_content"] or "").strip().casefold()

    def slot_is_off_app(entries: list) -> bool:
        rep = entries[0]
        keys = {
            (rep["job_content"] or "").strip().lower(),
            (rep["job_title"] or "").strip().lower(),
        }
        return any(off_app_jobs.get(key) for key in keys if key)

    def slot_actual_quantity(entries: list) -> int:
        # Real output rolled up across every record of this job type.
        return sum(
            int(
                ctx.db.suggested_attendance_quantity(
                    ctx.project_id, entry["record_key"], entry["task_kind"]
                )
                or 0
            )
            for entry in entries
        )

    def slot_status(entries: list) -> str:
        statuses = {entry["status"] for entry in entries}
        if statuses == {"APPROVED"}:
            return "APPROVED"
        if "PENDING" in statuses:
            return "PENDING"
        return "REJECTED"

    def slot_ready(entries: list) -> tuple[str, str]:
        pending = [entry for entry in entries if entry["status"] == "PENDING"]
        if not pending:
            return _ready_label(entries[0])
        labels = [_ready_label(entry) for entry in pending]
        # Surface a blocker if any pending row is not yet eligible.
        for text, color in labels:
            if text != "Đủ điều kiện":
                return text, color
        return "Đủ điều kiện", SUCCESS

    def approve_entries(entries: list) -> None:
        approved = 0
        errors: list[str] = []
        for entry in entries:
            if entry["status"] != "PENDING":
                continue
            try:
                ctx.db.approve_attendance_entry(int(entry["id"]))
                approved += 1
            except ValueError as exc:
                errors.append(str(exc))
        if approved:
            state["message"] = (
                f"Đã duyệt {approved} dòng." if not errors
                else f"Đã duyệt {approved} dòng; {len(errors)} dòng chưa đủ điều kiện."
            )
            ctx.refresh()
        elif errors:
            set_message(errors[0], failed=True)

    def approve_all(_event=None) -> None:
        approve_entries([row for row in pending_rows if _ready_label(row)[0] == "Đủ điều kiện"])

    def open_override(entries: list) -> None:
        reason = ft.TextField(label="Lý do override", multiline=True, min_lines=2, width=420)
        error = ft.Text("", color=DANGER)

        def submit(_event=None) -> None:
            approved = 0
            try:
                for entry in entries:
                    if entry["status"] != "PENDING":
                        continue
                    ctx.db.approve_attendance_entry(
                        int(entry["id"]),
                        override_reason=reason.value or "",
                    )
                    approved += 1
            except ValueError as exc:
                error.value = str(exc)
                ctx.page.update()
                return
            ctx.page.pop_dialog()
            state["message"] = f"Đã duyệt override {approved} dòng."
            ctx.refresh()

        ctx.page.show_dialog(
            kit.dialog(
                "Duyệt override (bỏ qua kiểm tra backup)",
                ft.Column(
                    tight=True,
                    spacing=10,
                    controls=[ft.Text(slot_job_name(entries), color=TEXT_MUTED), reason, error],
                ),
                [
                    kit.ghost_button("Hủy", on_click=lambda _e: ctx.page.pop_dialog()),
                    kit.primary_button("Duyệt override", on_click=submit),
                ],
                width=460,
            )
        )

    def open_reject(entries: list) -> None:
        reason = ft.TextField(label="Lý do không tính công", multiline=True, min_lines=2, width=420)
        error = ft.Text("", color=DANGER)

        def submit(_event=None) -> None:
            rejected = 0
            try:
                for entry in entries:
                    if entry["status"] not in {"PENDING", "APPROVED"}:
                        continue
                    ctx.db.reject_attendance_entry(int(entry["id"]), reason=reason.value or "")
                    rejected += 1
            except ValueError as exc:
                error.value = str(exc)
                ctx.page.update()
                return
            ctx.page.pop_dialog()
            state["message"] = f"Đã loại {rejected} dòng khỏi bảng công."
            ctx.refresh()

        ctx.page.show_dialog(
            kit.dialog(
                "Không tính công",
                ft.Column(
                    tight=True,
                    spacing=10,
                    controls=[ft.Text(slot_job_name(entries), color=TEXT_MUTED), reason, error],
                ),
                [
                    kit.ghost_button("Hủy", on_click=lambda _e: ctx.page.pop_dialog()),
                    kit.primary_button("Không tính công", on_click=submit),
                ],
                width=460,
            )
        )

    def _fmt_hours(hours: float) -> str:
        return f"{hours:g}h" if hours else "—"

    # Group entries per person, then per distinct job type → one timesheet slot
    # (Công việc 1..N). Same job type repeated across many records collapses into
    # one slot with the output summed. Each slot's Loại CC + giờ are editable
    # inline; the volume is read-only (auto) unless the job runs off-app.
    grouped: dict[int, list] = {}
    for row in sorted(rows, key=lambda r: ((r["full_name"] or "").lower(), int(r["id"]))):
        grouped.setdefault(row["personnel_id"], []).append(row)

    slot_editors: list[dict] = []
    data_rows: list[ft.DataRow] = []
    for person_entries in grouped.values():
        code = person_entries[0]["personnel_code"]
        name = person_entries[0]["full_name"]
        slots: dict[str, list] = {}
        for entry in person_entries:
            slots.setdefault(slot_job_key(entry) or "—", []).append(entry)
        for slot_index, entries in enumerate(slots.values()):
            job_name = slot_job_name(entries) or "—"
            rep = entries[0]
            off_app = slot_is_off_app(entries)
            status = slot_status(entries)
            editable = status != "APPROVED"

            type_dd = ft.Dropdown(
                dense=True,
                width=104,
                value=(rep["attendance_type"] or ""),
                disabled=not editable,
                options=[ft.dropdown.Option(key="", text="—")]
                + [ft.dropdown.Option(key=value, text=value) for value in ATTENDANCE_TYPES],
            )
            start_tf = ft.TextField(
                dense=True, width=76, value=rep["start_time"] or "", hint_text="07:30",
                disabled=not editable,
            )
            finish_tf = ft.TextField(
                dense=True, width=76, value=rep["finish_time"] or "", hint_text="17:30",
                disabled=not editable,
            )
            hours_text = ft.Text(
                _fmt_hours(ctx.db.work_hours_between(start_tf.value or "", finish_tf.value or "")),
                size=12,
            )

            def _update_hours(_e=None, s=start_tf, f=finish_tf, h=hours_text) -> None:
                h.value = _fmt_hours(ctx.db.work_hours_between(s.value or "", f.value or ""))
                ctx.page.update()

            start_tf.on_change = _update_hours
            finish_tf.on_change = _update_hours

            if off_app:
                manual_total = sum(int(entry["quantity"] or 0) for entry in entries)
                qty_control: ft.Control = ft.TextField(
                    dense=True, width=96, value=str(manual_total),
                    disabled=not editable, hint_text="nhập tay",
                    tooltip="Việc ngoài app: nhập sản lượng thủ công",
                )
            else:
                qty_control = ft.Text(
                    str(slot_actual_quantity(entries)),
                    tooltip="Sản lượng thực tự động (khóa, không sửa)",
                )

            slot_editors.append(
                {
                    "entries": entries,
                    "off_app": off_app,
                    "editable": editable,
                    "type_dd": type_dd,
                    "start": start_tf,
                    "finish": finish_tf,
                    "qty": qty_control if off_app else None,
                }
            )

            ready_text, ready_color = slot_ready(entries)
            actions: list[ft.Control] = []
            if any(entry["status"] == "PENDING" for entry in entries):
                actions += [
                    ft.IconButton(
                        icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                        tooltip="Duyệt nếu đủ điều kiện",
                        icon_color=SUCCESS,
                        on_click=lambda _e, items=entries: approve_entries(items),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.EDIT_NOTE,
                        tooltip="Duyệt override",
                        icon_color=WARNING,
                        on_click=lambda _e, items=entries: open_override(items),
                    ),
                ]
            if any(entry["status"] in {"PENDING", "APPROVED"} for entry in entries):
                actions.append(
                    ft.IconButton(
                        icon=ft.Icons.BLOCK,
                        tooltip="Không tính công",
                        icon_color=DANGER,
                        on_click=lambda _e, items=entries: open_reject(items),
                    )
                )

            first = slot_index == 0
            job_tooltip = "; ".join(
                f"[{_kind_label(entry['task_kind'])}] {entry['record_key']}" for entry in entries
            )
            job_label = f"{job_name} ({len(entries)} hồ sơ)" if len(entries) > 1 else job_name
            data_rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(code if first else "", max_lines=1)),
                        ft.DataCell(ft.Text(name if first else "", max_lines=1)),
                        ft.DataCell(ft.Text(f"Công việc {slot_index + 1}")),
                        ft.DataCell(hours_text),
                        ft.DataCell(type_dd),
                        ft.DataCell(ft.Text(job_label, max_lines=1, tooltip=job_tooltip)),
                        ft.DataCell(
                            ft.Row(
                                spacing=6,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[start_tf, ft.Text("→", color=TEXT_MUTED), finish_tf],
                            )
                        ),
                        ft.DataCell(qty_control),
                        ft.DataCell(kit.badge(status, _attendance_color(status))),
                        ft.DataCell(kit.badge(ready_text, ready_color)),
                        ft.DataCell(ft.Row(spacing=0, controls=actions)),
                    ]
                )
            )

    def save_attendance(_event=None) -> None:
        saved = 0
        errors: list[str] = []
        for editor in slot_editors:
            if not editor["editable"]:
                continue
            attendance_type = editor["type_dd"].value or ""
            start_value = editor["start"].value or ""
            finish_value = editor["finish"].value or ""
            entries = editor["entries"]
            try:
                manual_total = int(editor["qty"].value or 0) if editor["off_app"] else 0
                for index, entry in enumerate(entries):
                    if editor["off_app"]:
                        # Keep the summed total intact: carry it on the first
                        # record of the slot, zero the rest.
                        quantity = manual_total if index == 0 else 0
                    else:
                        quantity = int(
                            ctx.db.suggested_attendance_quantity(
                                ctx.project_id, entry["record_key"], entry["task_kind"]
                            )
                            or 0
                        )
                    ctx.db.set_attendance_details(
                        int(entry["id"]),
                        attendance_type=attendance_type,
                        start_time=start_value,
                        finish_time=finish_value,
                        quantity=quantity,
                    )
                    saved += 1
            except (ValueError, TypeError) as exc:
                errors.append(str(exc))
        if errors:
            set_message(f"Đã lưu {saved} dòng; lỗi: {errors[0]}", failed=True)
        else:
            state["message"] = f"Đã lưu dữ liệu chấm công ({saved} dòng). Có thể xuất mẫu."
            ctx.refresh()

    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Mã NV")),
            ft.DataColumn(ft.Text("Họ và Tên")),
            ft.DataColumn(ft.Text("Số lượng CV (CV1–4)")),
            ft.DataColumn(ft.Text("Thời gian thực hiện")),
            ft.DataColumn(ft.Text("Loại chấm công")),
            ft.DataColumn(ft.Text("Tên công việc")),
            ft.DataColumn(ft.Text("Giờ nhận → hoàn thành")),
            ft.DataColumn(ft.Text("Khối lượng hoàn thành")),
            ft.DataColumn(ft.Text("Công")),
            ft.DataColumn(ft.Text("Nghiệm thu")),
            ft.DataColumn(ft.Text("")),
        ],
        rows=data_rows,
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
                "Sửa trực tiếp Loại CC + giờ trên bảng, bấm Lưu rồi mới xuất. "
                "Giờ công đã trừ nghỉ trưa 12:00–13:00; sản lượng lấy thực tế tự động.",
                eyebrow_text="Attendance Ledger",
                actions=[
                    kit.primary_button("Lưu dữ liệu chấm công", icon=ft.Icons.SAVE, on_click=save_attendance),
                    kit.ghost_button("Duyệt dòng đủ điều kiện", icon=ft.Icons.DONE_ALL, on_click=approve_all),
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
