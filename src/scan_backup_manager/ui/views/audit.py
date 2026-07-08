from __future__ import annotations

import flet as ft

from .. import kit
from ..date_format import DISPLAY_DATE_HINT, display_to_iso, iso_datetime_to_display
from ..theme import TEXT_MUTED


def build(shell) -> ft.Control:
    db = shell.state.db
    projects = db.list_projects()
    project_options = [ft.dropdown.Option(key="", text="Tất cả dự án")] + [
        ft.dropdown.Option(key=str(p.id), text=p.display_name) for p in projects
    ]

    project_dropdown = ft.Dropdown(label="Dự án", width=220, value="", options=project_options)
    action_field = ft.TextField(label="Hành động", width=200, hint_text="VD: COPIED, ERROR")
    client_field = ft.TextField(label="Máy trạm", width=160)
    date_from_field = ft.TextField(label="Từ ngày", width=160, hint_text=DISPLAY_DATE_HINT)
    date_to_field = ft.TextField(label="Đến ngày", width=160, hint_text=DISPLAY_DATE_HINT)

    results_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Thời điểm")),
            ft.DataColumn(ft.Text("Dự án")),
            ft.DataColumn(ft.Text("Hành động")),
            ft.DataColumn(ft.Text("Máy trạm")),
            ft.DataColumn(ft.Text("Thông báo")),
        ],
        rows=[],
    )
    empty_text = ft.Text("Không có bản ghi nào khớp bộ lọc.", color=TEXT_MUTED, visible=False)

    project_names = {p.id: p.display_name for p in projects}

    def apply_filters(_event=None) -> None:
        project_id = int(project_dropdown.value) if project_dropdown.value else None
        try:
            date_from = display_to_iso(date_from_field.value) if date_from_field.value else None
            date_to = display_to_iso(date_to_field.value) if date_to_field.value else None
        except ValueError:
            empty_text.value = f"Ngày lọc phải có định dạng {DISPLAY_DATE_HINT}."
            empty_text.visible = True
            shell.page.update()
            return
        rows = db.list_audit_logs(
            project_id=project_id,
            action=(action_field.value or "").strip() or None,
            date_from=date_from,
            date_to=(date_to + "T23:59:59") if date_to else None,
            client_code=(client_field.value or "").strip() or None,
            limit=500,
        )
        results_table.rows = [
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(iso_datetime_to_display(row["created_at"]))),
                    ft.DataCell(ft.Text(project_names.get(row["project_id"], "-"))),
                    ft.DataCell(ft.Text(row["action"])),
                    ft.DataCell(ft.Text(row["client_code"] or "")),
                    ft.DataCell(ft.Text(row["message"] or "", max_lines=2)),
                ]
            )
            for row in rows
        ]
        empty_text.visible = not rows
        shell.page.update()

    apply_filters()

    filter_bar = kit.card(
        ft.Row(
            wrap=True,
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                project_dropdown, action_field, client_field, date_from_field, date_to_field,
                kit.primary_button("Lọc", icon=ft.Icons.SEARCH, on_click=apply_filters),
            ],
        ),
        padding=14,
    )

    return ft.Column(
        expand=True,
        spacing=16,
        controls=[
            kit.page_header(
                "Nhật ký hệ thống",
                "Toàn bộ hoạt động của hệ thống: backup, lỗi, xung đột, nhập mapfile, xuất báo cáo...",
                eyebrow_text="Giám sát",
            ),
            filter_bar,
            ft.Container(
                expand=True,
                content=ft.Column(
                    expand=True, scroll=ft.ScrollMode.AUTO,
                    controls=[empty_text, kit.table_frame(results_table)],
                ),
            ),
        ],
    )
