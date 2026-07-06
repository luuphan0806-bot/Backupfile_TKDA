from __future__ import annotations

import flet as ft

from ....models import ProjectTask
from ...theme import PRIORITY_LABELS, status_label

PRIORITIES = ["LOW", "NORMAL", "HIGH", "URGENT"]
STATUSES = ["NEW", "IN_PROGRESS", "COMPLETED", "CANCELLED"]


def build(ctx) -> ft.Control:
    db = ctx.db
    project_id = ctx.project_id
    personnel = db.list_personnel(project_id, enabled_only=True)
    error_text = ft.Text("", color=ft.Colors.ERROR)

    code_field = ft.TextField(label="Mã công việc", width=160)
    title_field = ft.TextField(label="Tiêu đề", width=260)
    description_field = ft.TextField(label="Mô tả", width=300)
    due_field = ft.TextField(label="Hạn hoàn thành", width=140, hint_text="YYYY-MM-DD")
    priority_dropdown = ft.Dropdown(
        label="Độ ưu tiên", width=140, value="NORMAL",
        options=[ft.dropdown.Option(key=p, text=PRIORITY_LABELS[p]) for p in PRIORITIES],
    )
    status_dropdown = ft.Dropdown(
        label="Trạng thái", width=160, value="NEW",
        options=[ft.dropdown.Option(key=s, text=status_label(s)) for s in STATUSES],
    )
    assignee_dropdown = ft.Dropdown(
        label="Người phụ trách", width=240,
        options=[ft.dropdown.Option(key=str(p.id), text=f"{p.personnel_code} - {p.full_name}") for p in personnel],
    )

    def clear_form() -> None:
        code_field.value = ""
        title_field.value = ""
        description_field.value = ""
        due_field.value = ""
        priority_dropdown.value = "NORMAL"
        status_dropdown.value = "NEW"
        assignee_dropdown.value = None

    def save_task(_event) -> None:
        if not personnel:
            error_text.value = "Cần có ít nhất một nhân sự đang hoạt động trước khi tạo công việc."
            ctx.page.update()
            return
        if not (code_field.value or "").strip() or not (title_field.value or "").strip() or not assignee_dropdown.value:
            error_text.value = "Cần nhập mã, tiêu đề và chọn người phụ trách."
            ctx.page.update()
            return
        try:
            db.save_task(
                ProjectTask(
                    None, project_id, code_field.value or "", title_field.value or "",
                    description_field.value or "", int(assignee_dropdown.value),
                    due_field.value or "", priority_dropdown.value or "NORMAL",
                    status_dropdown.value or "NEW",
                )
            )
        except ValueError as exc:
            error_text.value = str(exc)
            ctx.page.update()
            return
        clear_form()
        ctx.refresh()

    def delete_task(task_id: int) -> None:
        db.delete_task(task_id)
        ctx.refresh()

    def edit_task(row) -> None:
        code_field.value = row["task_code"]
        title_field.value = row["title"]
        description_field.value = row["description"]
        due_field.value = row["due_date"]
        priority_dropdown.value = row["priority"]
        status_dropdown.value = row["status"]
        assignee_dropdown.value = str(row["assignee_id"])
        ctx.page.update()

    form = ft.Container(
        padding=16, border_radius=12, bgcolor=ft.Colors.SURFACE,
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Row(controls=[code_field, title_field, description_field], wrap=True),
                ft.Row(controls=[due_field, priority_dropdown, status_dropdown, assignee_dropdown], wrap=True),
                error_text,
                ft.Row(
                    controls=[
                        ft.FilledButton("Lưu công việc", on_click=save_task),
                        ft.OutlinedButton("Xóa nội dung nhập", on_click=lambda _e: (clear_form(), ctx.page.update())),
                    ]
                ),
            ],
        ),
    )

    tasks = db.list_tasks(project_id)
    rows = []
    for row in tasks:
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(row["task_code"])),
                    ft.DataCell(ft.Text(row["title"])),
                    ft.DataCell(ft.Text(f"{row['personnel_code']} - {row['assignee_name']}")),
                    ft.DataCell(ft.Text(row["due_date"])),
                    ft.DataCell(ft.Text(PRIORITY_LABELS.get(row["priority"], row["priority"]))),
                    ft.DataCell(ft.Text(status_label(row["status"]))),
                    ft.DataCell(
                        ft.Row(
                            spacing=4,
                            controls=[
                                ft.IconButton(icon=ft.Icons.EDIT, tooltip="Sửa", on_click=lambda _e, r=row: edit_task(r)),
                                ft.IconButton(icon=ft.Icons.DELETE, tooltip="Xóa", on_click=lambda _e, tid=row["id"]: delete_task(tid)),
                            ],
                        )
                    ),
                ]
            )
        )
    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Mã")),
            ft.DataColumn(ft.Text("Tiêu đề")),
            ft.DataColumn(ft.Text("Người phụ trách")),
            ft.DataColumn(ft.Text("Hạn")),
            ft.DataColumn(ft.Text("Ưu tiên")),
            ft.DataColumn(ft.Text("Trạng thái")),
            ft.DataColumn(ft.Text("")),
        ],
        rows=rows,
    )

    return ft.Column(
        expand=True,
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text(
                "Theo dõi các công việc được giao cho nhân sự dự án.",
                size=13, color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            form,
            table if tasks else ft.Text("Chưa có công việc nào.", color=ft.Colors.ON_SURFACE_VARIANT),
        ],
    )
