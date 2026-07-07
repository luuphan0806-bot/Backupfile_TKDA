from __future__ import annotations

import flet as ft

from ...models import Project


def _directory_field(shell, label: str, initial: str = "") -> tuple[ft.TextField, ft.Control]:
    field = ft.TextField(label=label, value=initial, expand=True)
    picker = ft.FilePicker()
    if picker not in shell.page.overlay:
        shell.page.overlay.append(picker)

    async def browse(_event) -> None:
        selected = await picker.get_directory_path(dialog_title=label)
        if selected:
            field.value = selected
            shell.page.update()

    row = ft.Row(
        controls=[field, ft.IconButton(icon=ft.Icons.FOLDER_OPEN, tooltip="Chọn thư mục", on_click=browse)]
    )
    return field, row


def _open_create_project_dialog(shell) -> None:
    code_field = ft.TextField(label="Mã dự án", hint_text="VD: PROJECT_ALPHA")
    name_field = ft.TextField(label="Tên hiển thị")
    backup_field, backup_row = _directory_field(shell, "Thư mục backup")
    staging_field, staging_row = _directory_field(shell, "Thư mục staging", "data/staging")
    conflict_field, conflict_row = _directory_field(shell, "Kho xung đột", "data/conflict_archive")
    reports_field, reports_row = _directory_field(shell, "Thư mục báo cáo", "data/reports")
    error_text = ft.Text("", color=ft.Colors.ERROR)

    def submit(_event) -> None:
        try:
            project_id = shell.db.create_project(
                Project(
                    None,
                    code_field.value or "",
                    name_field.value or "",
                    backup_field.value or "",
                    staging_field.value or "",
                    conflict_field.value or "",
                    reports_field.value or "",
                )
            )
        except ValueError as exc:
            error_text.value = str(exc)
            shell.page.update()
            return
        shell.page.pop_dialog()
        shell.open_project(project_id)

    dialog = ft.AlertDialog(
        title=ft.Text("Tạo dự án mới"),
        content=ft.Container(
            width=520,
            content=ft.Column(
                spacing=12, tight=True, scroll=ft.ScrollMode.AUTO,
                controls=[
                    code_field, name_field,
                    backup_row, staging_row, conflict_row, reports_row,
                    error_text,
                ],
            ),
        ),
        actions=[
            ft.TextButton("Hủy", on_click=lambda _e: shell.page.pop_dialog()),
            ft.FilledButton("Tạo dự án", on_click=submit),
        ],
    )
    shell.page.show_dialog(dialog)


def build(shell) -> ft.Control:
    db = shell.state.db
    projects = db.list_projects()

    def project_card(project: Project) -> ft.Control:
        project_id = project.id or 0
        return ft.Container(
            padding=16,
            border_radius=12,
            bgcolor=ft.Colors.SURFACE,
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Column(
                        spacing=2,
                        controls=[
                            ft.Text(project.display_name, size=15, weight=ft.FontWeight.BOLD),
                            ft.Text(project.project_code, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(
                                "Đang bật" if project.enabled else "Đã tắt",
                                size=12,
                                color=ft.Colors.PRIMARY if project.enabled else ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                    ),
                    ft.FilledButton("Mở trang điều khiển", on_click=lambda _e, pid=project_id: shell.open_project(pid)),
                ],
            ),
        )

    if projects:
        listing: ft.Control = ft.Column(spacing=10, controls=[project_card(p) for p in projects])
    else:
        listing = ft.Text(
            "Chưa có dự án nào. Bấm \"Tạo dự án mới\" để bắt đầu.",
            color=ft.Colors.ON_SURFACE_VARIANT,
        )

    return ft.Column(
        expand=True,
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Column(
                        spacing=2,
                        controls=[
                            ft.Text("Danh sách dự án", size=22, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "Bấm vào một dự án để mở trang điều khiển riêng của dự án đó.",
                                size=13, color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                    ),
                    ft.FilledButton(
                        "Tạo dự án mới", icon=ft.Icons.ADD,
                        on_click=lambda _e: _open_create_project_dialog(shell),
                    ),
                ],
            ),
            listing,
        ],
    )
