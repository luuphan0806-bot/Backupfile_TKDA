from __future__ import annotations

import flet as ft

from ..constants import APP_NAME, runtime_db_path
from ..db import Database
from ..logging_config import get_logger, setup_logging
from .state import AppState
from .theme import apply_theme
from .views import audit as audit_view
from .views import global_settings as settings_view
from .views import overview as overview_view
from .views import project_console as console_view
from .views import project_list as project_list_view


NAV_OVERVIEW, NAV_PROJECTS, NAV_SETTINGS, NAV_AUDIT = range(4)


class ScanBackupFletApp:
    def __init__(self, page: ft.Page, db_path=None):
        self.page = page
        self.db = Database(db_path or runtime_db_path())
        self.state = AppState.create(self.db)
        self.current_project_id: int | None = None
        self.nav_index = NAV_OVERVIEW

        self.page.title = APP_NAME
        self.page.window.width = 1360
        self.page.window.height = 860
        self.page.window.min_width = 1100
        self.page.window.min_height = 700
        apply_theme(self.page, self.state.theme_mode)

        get_logger().info("App started (db_path=%s)", self.db.db_path)
        self.show_role_selection()

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------
    def set_root(self, control: ft.Control) -> None:
        self.page.controls.clear()
        self.page.controls.append(control)
        self.page.update()

    def toggle_theme(self) -> None:
        self.state.theme_mode = "light" if self.state.theme_mode == "dark" else "dark"
        self.db.set_setting("theme_mode", self.state.theme_mode)
        apply_theme(self.page, self.state.theme_mode)
        self.page.update()

    # ------------------------------------------------------------------
    # Auth flow
    # ------------------------------------------------------------------
    def show_role_selection(self) -> None:
        self.state.authenticated = False

        def go_admin(_event) -> None:
            self.show_admin_login()

        def go_personnel(_event) -> None:
            self.show_personnel_login()

        card = ft.Container(
            width=760,
            padding=48,
            border_radius=20,
            bgcolor=ft.Colors.SURFACE,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=18,
                controls=[
                    ft.Text(APP_NAME, size=30, weight=ft.FontWeight.BOLD),
                    ft.Text("Chọn khu vực để tiếp tục", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Row(
                        spacing=16,
                        controls=[
                            ft.FilledButton(
                                "Quản trị viên", on_click=go_admin,
                                height=90, width=310,
                                style=ft.ButtonStyle(text_style=ft.TextStyle(size=16)),
                            ),
                            ft.OutlinedButton(
                                "Nhân sự dự án", on_click=go_personnel,
                                height=90, width=310,
                                style=ft.ButtonStyle(text_style=ft.TextStyle(size=16)),
                            ),
                        ],
                    ),
                ],
            ),
        )
        self.set_root(
            ft.Container(
                expand=True,
                alignment=ft.Alignment.CENTER,
                content=card,
            )
        )

    def show_personnel_placeholder(self) -> None:
        self.set_root(
            ft.Container(
                expand=True,
                alignment=ft.Alignment.CENTER,
                content=ft.Container(
                    width=560,
                    padding=48,
                    border_radius=20,
                    bgcolor=ft.Colors.SURFACE,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=16,
                        controls=[
                            ft.Text("Nhân sự dự án", size=24, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "Chức năng đang được phát triển và sẽ cấu hình ở giai đoạn sau.",
                                size=14, color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                            ft.OutlinedButton("Quay lại", on_click=lambda _e: self.show_role_selection()),
                        ],
                    ),
                ),
            )
        )

    def show_personnel_login(self) -> None:
        project_field = ft.TextField(label="Mã dự án", width=320)
        code_field = ft.TextField(label="Mã nhân sự", width=320)
        pin_field = ft.TextField(
            label="Mã PIN 6 số", password=True, can_reveal_password=True,
            max_length=6, width=320,
        )
        error = ft.Text("", color=ft.Colors.ERROR)

        def submit(_event) -> None:
            try:
                person = self.db.verify_personnel_pin(
                    project_field.value or "", code_field.value or "", pin_field.value or ""
                )
            except ValueError:
                error.value = "Tài khoản đang tạm khóa. Vui lòng thử lại sau 15 phút."
                self.page.update()
                return
            if not person:
                error.value = "Thông tin đăng nhập không đúng."
                self.page.update()
                return
            self.state.personnel_id = int(person["id"])
            self.state.personnel_project_id = int(person["project_id"])
            if person["must_change_pin"]:
                self.show_personnel_change_pin(
                    project_field.value or "", code_field.value or "", pin_field.value or ""
                )
            else:
                self.show_personnel_home()

        self.set_root(
            ft.Container(
                expand=True, alignment=ft.Alignment.CENTER,
                content=ft.Container(
                    width=460, padding=48, border_radius=20, bgcolor=ft.Colors.SURFACE,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12,
                        controls=[
                            ft.Text("Đăng nhập nhân sự", size=24, weight=ft.FontWeight.BOLD),
                            project_field, code_field, pin_field, error,
                            ft.FilledButton("Đăng nhập", on_click=submit, width=200),
                            ft.TextButton("Quay lại", on_click=lambda _e: self.show_role_selection()),
                        ],
                    ),
                ),
            )
        )

    def show_personnel_change_pin(
        self, project_code: str, personnel_code: str, current_pin: str
    ) -> None:
        new_pin = ft.TextField(label="PIN mới gồm 6 số", password=True, max_length=6, width=320)
        confirm = ft.TextField(label="Nhập lại PIN mới", password=True, max_length=6, width=320)
        error = ft.Text("", color=ft.Colors.ERROR)

        def save(_event) -> None:
            if new_pin.value != confirm.value:
                error.value = "Hai lần nhập PIN không khớp."
            else:
                try:
                    self.db.change_personnel_pin(
                        project_code, personnel_code, current_pin, new_pin.value or ""
                    )
                except ValueError as exc:
                    error.value = str(exc)
                else:
                    self.show_personnel_home()
                    return
            self.page.update()

        self.set_root(ft.Container(
            expand=True, alignment=ft.Alignment.CENTER,
            content=ft.Container(
                width=440, padding=48, border_radius=20, bgcolor=ft.Colors.SURFACE,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text("Đổi mã PIN", size=24, weight=ft.FontWeight.BOLD),
                        new_pin, confirm, error, ft.FilledButton("Lưu mã PIN", on_click=save),
                    ],
                ),
            ),
        ))

    def show_personnel_home(self) -> None:
        personnel_id = self.state.personnel_id
        project_id = self.state.personnel_project_id
        if personnel_id is None or project_id is None:
            self.show_role_selection()
            return
        person = next(
            (p for p in self.db.list_personnel(project_id) if p.id == personnel_id), None
        )
        tasks = [row for row in self.db.list_tasks(project_id) if row["assignee_id"] == personnel_id]
        import_id = self.db.latest_mapfile_import_id(project_id)
        rows, total = (
            self.db.list_mapfile_rows_page(import_id, limit=50) if import_id else ([], 0)
        )

        def toggle_done(row_id: int, done: bool) -> None:
            if done:
                self.db.mark_mapfile_row_done(row_id, personnel_id)
            else:
                self.db.unmark_mapfile_row_done(row_id)
            self.show_personnel_home()

        task_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Mã việc")), ft.DataColumn(ft.Text("Nội dung")),
                ft.DataColumn(ft.Text("Hạn hoàn thành")), ft.DataColumn(ft.Text("Trạng thái")),
            ],
            rows=[
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(row["task_code"])),
                    ft.DataCell(ft.Text(row["title"])),
                    ft.DataCell(ft.Text(row["due_date"])),
                    ft.DataCell(ft.Text(row["status"])),
                ]) for row in tasks
            ],
        )
        record_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Dòng")), ft.DataColumn(ft.Text("Hồ sơ")),
                ft.DataColumn(ft.Text("Tình trạng sao lưu")),
                ft.DataColumn(ft.Text("Đã quét xong")),
            ],
            rows=[
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(str(row["row_number"]))),
                    ft.DataCell(ft.Text(row["expected_relative_path"])),
                    ft.DataCell(ft.Text(row["status"])),
                    ft.DataCell(ft.Checkbox(
                        value=bool(row["is_done"]),
                        on_change=lambda e, rid=row["id"]: toggle_done(rid, bool(e.control.value)),
                    )),
                ]) for row in rows
            ],
        )
        self.set_root(ft.Column(
            expand=True,
            controls=[
                ft.Container(
                    padding=20, bgcolor=ft.Colors.SURFACE,
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(spacing=2, controls=[
                                ft.Text(f"Xin chào, {person.full_name if person else ''}", size=22, weight=ft.FontWeight.BOLD),
                                ft.Text("Theo dõi công việc và xác nhận hồ sơ đã quét xong."),
                            ]),
                            ft.OutlinedButton("Đăng xuất", on_click=lambda _e: self.show_role_selection()),
                        ],
                    ),
                ),
                ft.Container(
                    expand=True, padding=24,
                    content=ft.Column(
                        scroll=ft.ScrollMode.AUTO,
                        controls=[
                            ft.Text("Công việc của tôi", size=18, weight=ft.FontWeight.BOLD),
                            task_table if tasks else ft.Text("Chưa có công việc được giao."),
                            ft.Text(f"Danh mục hồ sơ ({total})", size=18, weight=ft.FontWeight.BOLD),
                            record_table if rows else ft.Text("Chưa có danh mục hồ sơ."),
                        ],
                    ),
                ),
            ],
        ))

    def show_admin_login(self) -> None:
        password_field = ft.TextField(label="Mật khẩu", password=True, can_reveal_password=True, width=320)
        error_text = ft.Text("", color=ft.Colors.ERROR)

        def submit(_event) -> None:
            if not self.db.verify_admin_password(password_field.value or ""):
                error_text.value = "Mật khẩu không đúng."
                self.page.update()
                return
            self.state.authenticated = True
            if self.db.admin_must_change_password():
                self.show_change_password(force=True, current_password=password_field.value or "")
            else:
                self.show_main_shell()

        password_field.on_submit = submit

        self.set_root(
            ft.Container(
                expand=True,
                alignment=ft.Alignment.CENTER,
                content=ft.Container(
                    width=440,
                    padding=48,
                    border_radius=20,
                    bgcolor=ft.Colors.SURFACE,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=14,
                        controls=[
                            ft.Text("Đăng nhập quản trị hệ thống", size=22, weight=ft.FontWeight.BOLD),
                            password_field,
                            error_text,
                            ft.FilledButton("Đăng nhập", on_click=submit, width=200),
                            ft.TextButton("Quay lại", on_click=lambda _e: self.show_role_selection()),
                        ],
                    ),
                ),
            )
        )

    def show_change_password(self, *, force: bool = False, current_password: str = "") -> None:
        current_field = ft.TextField(label="Mật khẩu hiện tại", password=True, value=current_password, width=340)
        new_field = ft.TextField(label="Mật khẩu mới (ít nhất 8 ký tự)", password=True, can_reveal_password=True, width=340)
        confirm_field = ft.TextField(label="Xác nhận mật khẩu mới", password=True, can_reveal_password=True, width=340)
        error_text = ft.Text("", color=ft.Colors.ERROR)

        def submit(_event) -> None:
            if new_field.value != confirm_field.value:
                error_text.value = "Xác nhận mật khẩu không khớp."
                self.page.update()
                return
            try:
                self.db.change_admin_password(current_field.value or "", new_field.value or "")
            except ValueError as exc:
                error_text.value = str(exc)
                self.page.update()
                return
            self.show_main_shell()

        controls = [
            ft.Text("Đổi mật khẩu", size=22, weight=ft.FontWeight.BOLD),
            current_field, new_field, confirm_field, error_text,
            ft.FilledButton("Lưu", on_click=submit, width=200),
        ]
        if not force:
            controls.append(ft.TextButton("Quay lại", on_click=lambda _e: self.show_main_shell()))

        self.set_root(
            ft.Container(
                expand=True,
                alignment=ft.Alignment.CENTER,
                content=ft.Container(
                    width=460, padding=48, border_radius=20, bgcolor=ft.Colors.SURFACE,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=14, controls=controls,
                    ),
                ),
            )
        )

    # ------------------------------------------------------------------
    # Main shell (post-login)
    # ------------------------------------------------------------------
    def show_main_shell(self) -> None:
        self.state.authenticated = True
        self.nav_index = NAV_OVERVIEW
        self.current_project_id = None
        self._build_shell()

    def _build_shell(self) -> None:
        rail = ft.NavigationRail(
            selected_index=self.nav_index,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=96,
            min_extended_width=220,
            destinations=[
                ft.NavigationRailDestination(icon=ft.Icons.SPACE_DASHBOARD_OUTLINED, selected_icon=ft.Icons.SPACE_DASHBOARD, label="Tổng Quan"),
                ft.NavigationRailDestination(icon=ft.Icons.FOLDER_OUTLINED, selected_icon=ft.Icons.FOLDER, label="Danh sách dự án"),
                ft.NavigationRailDestination(icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS, label="Cấu hình"),
                ft.NavigationRailDestination(icon=ft.Icons.HISTORY, selected_icon=ft.Icons.HISTORY, label="Nhật ký hệ thống"),
            ],
            on_change=self._on_nav_change,
        )

        top_bar = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Text(APP_NAME, size=18, weight=ft.FontWeight.BOLD),
                ft.Row(
                    spacing=6,
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.DARK_MODE if self.state.theme_mode == "light" else ft.Icons.LIGHT_MODE,
                            tooltip="Đổi giao diện sáng/tối",
                            on_click=lambda _e: (self.toggle_theme(), self._build_shell()),
                        ),
                        ft.OutlinedButton("Đổi mật khẩu", on_click=lambda _e: self.show_change_password()),
                        ft.OutlinedButton("Đăng xuất", icon=ft.Icons.LOGOUT, on_click=lambda _e: self.show_role_selection()),
                    ],
                ),
            ],
        )

        self.content_area = ft.Container(expand=True, padding=20)
        self._render_content()

        layout = ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.Container(
                    content=top_bar,
                    padding=ft.Padding.symmetric(vertical=16, horizontal=20),
                    bgcolor=ft.Colors.SURFACE,
                ),
                ft.Row(
                    expand=True,
                    spacing=0,
                    controls=[rail, ft.VerticalDivider(width=1), self.content_area],
                ),
            ],
        )
        self.set_root(layout)

    def _on_nav_change(self, event: ft.ControlEvent) -> None:
        self.nav_index = event.control.selected_index
        self.current_project_id = None
        self._render_content()
        self.page.update()

    def _render_content(self) -> None:
        if self.nav_index == NAV_OVERVIEW:
            self.content_area.content = overview_view.build(self)
        elif self.nav_index == NAV_PROJECTS:
            self.content_area.content = project_list_view.build(self)
        elif self.nav_index == NAV_SETTINGS:
            self.content_area.content = settings_view.build(self)
        elif self.nav_index == NAV_AUDIT:
            self.content_area.content = audit_view.build(self)

    def refresh_content(self) -> None:
        self._render_content()
        self.page.update()

    def open_project(self, project_id: int) -> None:
        self.current_project_id = project_id
        self.content_area.content = console_view.build(self, project_id)
        self.page.update()

    def close_project(self) -> None:
        self.current_project_id = None
        self.refresh_content()


def main(page: ft.Page) -> None:
    ScanBackupFletApp(page)


def run() -> None:
    setup_logging()
    # Explicit (not relying on Flet's default) so this always opens as a
    # native desktop window, never a browser tab / web server.
    ft.run(main, view=ft.AppView.FLET_APP)


if __name__ == "__main__":
    run()
