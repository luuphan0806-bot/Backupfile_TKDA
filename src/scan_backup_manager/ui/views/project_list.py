from __future__ import annotations

import flet as ft

from .. import kit
from ..theme import SUCCESS, TEXT_MUTED
from ...models import Project


def _directory_field(shell, label: str, initial: str = "") -> tuple[ft.TextField, ft.Control]:
    field = ft.TextField(label=label, value=initial, expand=True)
    picker = ft.FilePicker()
    if picker not in shell.page.services:
        shell.page.services.append(picker)

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


def _open_delete_project_dialog(shell, project: Project) -> None:
    password_field = ft.TextField(
        label="Mật khẩu admin",
        password=True,
        can_reveal_password=True,
        autofocus=True,
    )
    error_text = ft.Text("", color=ft.Colors.ERROR)

    def submit(_event) -> None:
        if not shell.db.verify_admin_password(password_field.value or ""):
            error_text.value = "Mật khẩu admin không đúng."
            shell.page.update()
            return
        try:
            shell.db.delete_project(project.id or 0)
        except ValueError as exc:
            error_text.value = str(exc)
            shell.page.update()
            return
        shell.page.pop_dialog()
        if shell.current_project_id == project.id:
            shell.current_project_id = None
        shell.refresh_content()

    dialog = kit.dialog(
        f"Xóa dự án {project.project_code}",
        ft.Column(
            spacing=12,
            tight=True,
            controls=[
                ft.Text(
                    "Thao tác này xóa dữ liệu quản lý của dự án trong ứng dụng và file SQLite phụ. "
                    "Thư mục backup vật lý sẽ được giữ nguyên.",
                    color=TEXT_MUTED,
                ),
                password_field,
                error_text,
            ],
        ),
        actions=[
            ft.TextButton("Hủy", on_click=lambda _e: shell.page.pop_dialog()),
            ft.FilledButton("Xóa dự án", icon=ft.Icons.DELETE_FOREVER, on_click=submit),
        ],
        icon=ft.Icons.WARNING_AMBER,
        width=520,
    )
    shell.page.show_dialog(dialog)


def build(shell) -> ft.Control:
    db = shell.state.db
    projects = db.list_projects()

    def project_card(project: Project) -> ft.Control:
        project_id = project.id or 0
        return kit.card(
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Column(
                        spacing=4,
                        controls=[
                            ft.Text(project.display_name, size=15, weight=ft.FontWeight.BOLD),
                            ft.Text(project.project_code, size=12, color=TEXT_MUTED),
                        ],
                    ),
                    ft.Row(
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            kit.badge("Đang bật", SUCCESS) if project.enabled else kit.badge("Đã tắt", TEXT_MUTED),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                tooltip="Xóa dự án",
                                icon_color=ft.Colors.ERROR,
                                on_click=lambda _e, p=project: _open_delete_project_dialog(shell, p),
                            ),
                            kit.primary_button("Mở trang điều khiển", icon=ft.Icons.ARROW_FORWARD, on_click=lambda _e, pid=project_id: shell.open_project(pid)),
                        ],
                    ),
                ],
            ),
            padding=16, radius=12,
        )

    if projects:
        listing: ft.Control = ft.Column(spacing=10, controls=[project_card(p) for p in projects])
    else:
        listing = ft.Text(
            "Chưa có dự án nào. Bấm \"Tạo dự án mới\" để bắt đầu.",
            color=TEXT_MUTED,
        )

    return ft.Column(
        expand=True,
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            kit.page_header(
                "Danh sách dự án",
                "Bấm vào một dự án để mở trang điều khiển riêng của dự án đó.",
                eyebrow_text="Quản lý dự án",
                actions=[
                    kit.primary_button(
                        "Tạo dự án mới", icon=ft.Icons.ADD,
                        on_click=lambda _e: _open_create_project_dialog(shell),
                    ),
                ],
            ),
            listing,
        ],
    )
