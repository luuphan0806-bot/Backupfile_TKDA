from __future__ import annotations

import flet as ft

from ..constants import APP_NAME, runtime_db_path
from ..db import Database
from ..logging_config import get_logger, setup_logging
from . import kit
from . import theme as ui_theme
from .state import AppState
from .theme import (
    TEXT_MUTED,
    apply_theme,
    background_gradient,
    content_switcher,
)
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
        self.sidebar_collapsed = False
        self.navigation_rail: ft.NavigationRail | None = None
        self.sidebar_container: ft.Container | None = None
        self.sidebar_toggle: ft.IconButton | None = None

        self.page.title = APP_NAME
        self.page.window.width = 1360
        self.page.window.height = 860
        self.page.window.min_width = 1100
        self.page.window.min_height = 700
        apply_theme(self.page, self.state.theme_mode)
        self.page.on_resize = self._on_page_resize

        get_logger().info("App started (db_path=%s)", self.db.db_path)
        self.show_role_selection()

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------
    def set_root(self, control: ft.Control) -> None:
        """Every screen sits on the deep-space gradient plane."""
        self.page.controls.clear()
        self.page.controls.append(
            ft.Container(
                expand=True,
                gradient=background_gradient(self.state.theme_mode),
                content=control,
            )
        )
        self.page.update()

    def _toggle_theme_mode(self, _event=None) -> None:
        self.state.theme_mode = "light" if self.state.theme_mode == "dark" else "dark"
        self.db.set_setting("theme_mode", self.state.theme_mode)
        apply_theme(self.page, self.state.theme_mode)
        if self.state.authenticated:
            self._build_shell()
        else:
            self.show_role_selection()

    def _theme_mode_button(self) -> ft.Control:
        is_light = self.state.theme_mode == "light"
        return kit.ghost_button(
            "Chế độ sáng" if is_light else "Chế độ tối",
            icon=ft.Icons.LIGHT_MODE if is_light else ft.Icons.DARK_MODE,
            tooltip="Chuyển sang chế độ tối" if is_light else "Chuyển sang chế độ sáng",
            on_click=self._toggle_theme_mode,
        )

    def _on_page_resize(self, _event=None) -> None:
        if self.state.authenticated and hasattr(self, "content_switcher"):
            self.refresh_content()

    def _auth_screen(self, card: ft.Control) -> ft.Control:
        return ft.Container(expand=True, alignment=ft.Alignment.CENTER, content=card)

    def _hero(self, heading: str, subtitle: str) -> ft.Control:
        return ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
            controls=[
                kit.logo_mark(52),
                kit.eyebrow("Secure Archive System"),
                ft.Text(heading, size=28, weight=ft.FontWeight.BOLD),
                ft.Text(subtitle, size=13, color=TEXT_MUTED, text_align=ft.TextAlign.CENTER),
            ],
        )

    # ------------------------------------------------------------------
    # Auth flow
    # ------------------------------------------------------------------
    def show_role_selection(self) -> None:
        self.state.authenticated = False

        def go_admin(_event) -> None:
            self.show_admin_login()

        def go_personnel(_event) -> None:
            self.show_personnel_login()

        card = kit.card(
            ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=26,
                controls=[
                    self._hero(APP_NAME, "Chọn khu vực để tiếp tục"),
                    ft.Row(
                        spacing=16,
                        controls=[
                            kit.primary_button(
                                "Quản trị viên", on_click=go_admin, icon=ft.Icons.ADMIN_PANEL_SETTINGS,
                                height=88, width=300,
                            ),
                            kit.ghost_button(
                                "Nhân sự dự án", on_click=go_personnel, icon=ft.Icons.BADGE,
                                height=88, width=300,
                            ),
                        ],
                    ),
                ],
            ),
            glow_color=ui_theme.primary(),
            padding=48,
            radius=20,
        )
        card.width = 760
        self.set_root(self._auth_screen(card))

    def show_personnel_placeholder(self) -> None:
        card = kit.card(
            ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=16,
                controls=[
                    ft.Text("Nhân sự dự án", size=24, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "Chức năng đang được phát triển và sẽ cấu hình ở giai đoạn sau.",
                        size=14, color=TEXT_MUTED,
                    ),
                    kit.ghost_button("Quay lại", on_click=lambda _e: self.show_role_selection()),
                ],
            ),
            padding=48, radius=20,
        )
        card.width = 560
        self.set_root(self._auth_screen(card))

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

        card = kit.card(
            ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=14,
                controls=[
                    self._hero("Đăng nhập nhân sự", "Nhập thông tin được cấp để tiếp tục"),
                    project_field, code_field, pin_field, error,
                    kit.primary_button("Đăng nhập", on_click=submit, width=220),
                    ft.TextButton("Quay lại", on_click=lambda _e: self.show_role_selection()),
                ],
            ),
            glow_color=ui_theme.primary(), padding=44, radius=20,
        )
        card.width = 460
        self.set_root(self._auth_screen(card))

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

        card = kit.card(
            ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=14,
                controls=[
                    ft.Text("Đổi mã PIN", size=24, weight=ft.FontWeight.BOLD),
                    new_pin, confirm, error,
                    kit.primary_button("Lưu mã PIN", on_click=save, width=220),
                ],
            ),
            padding=44, radius=20,
        )
        card.width = 440
        self.set_root(self._auth_screen(card))

    def show_personnel_home(self) -> None:
        personnel_id = self.state.personnel_id
        project_id = self.state.personnel_project_id
        if personnel_id is None or project_id is None:
            self.show_role_selection()
            return
        person = next(
            (p for p in self.db.list_personnel(project_id) if p.id == personnel_id), None
        )
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
            spacing=0,
            controls=[
                ft.Container(
                    padding=20,
                    bgcolor=ui_theme.surface(),
                    border=ft.Border.only(bottom=ft.BorderSide(1, ui_theme.line())),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Row(spacing=12, controls=[
                                kit.logo_mark(38),
                                ft.Column(spacing=2, controls=[
                                    ft.Text(f"Xin chào, {person.full_name if person else ''}", size=20, weight=ft.FontWeight.BOLD),
                                    ft.Text("Theo dõi công việc và xác nhận hồ sơ đã quét xong.", size=12, color=TEXT_MUTED),
                                ]),
                            ]),
                            kit.ghost_button("Đăng xuất", icon=ft.Icons.LOGOUT, on_click=lambda _e: self.show_role_selection()),
                        ],
                    ),
                ),
                ft.Container(
                    expand=True, padding=24,
                    content=ft.Column(
                        scroll=ft.ScrollMode.AUTO,
                        spacing=14,
                        controls=[
                            kit.eyebrow("Danh mục hồ sơ"),
                            ft.Text(f"Tổng {total} hồ sơ", size=18, weight=ft.FontWeight.BOLD),
                            kit.table_frame(record_table) if rows else ft.Text("Chưa có danh mục hồ sơ.", color=TEXT_MUTED),
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

        card = kit.card(
            ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16,
                controls=[
                    self._hero("Quản trị hệ thống", "Đăng nhập để mở bảng điều khiển"),
                    password_field,
                    error_text,
                    kit.primary_button("Đăng nhập", on_click=submit, width=220),
                    ft.TextButton("Quay lại", on_click=lambda _e: self.show_role_selection()),
                ],
            ),
            glow_color=ui_theme.primary(), padding=44, radius=20,
        )
        card.width = 460
        self.set_root(self._auth_screen(card))

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
            kit.primary_button("Lưu", on_click=submit, width=220),
        ]
        if not force:
            controls.append(ft.TextButton("Quay lại", on_click=lambda _e: self.show_main_shell()))

        card = kit.card(
            ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=14, controls=controls),
            padding=44, radius=20,
        )
        card.width = 480
        self.set_root(self._auth_screen(card))

    # ------------------------------------------------------------------
    # Main shell (post-login)
    # ------------------------------------------------------------------
    def show_main_shell(self) -> None:
        self.state.authenticated = True
        self.nav_index = NAV_OVERVIEW
        self.current_project_id = None
        self._build_shell()

    def _build_shell(self) -> None:
        self.sidebar_collapsed = self.current_project_id is not None
        self.sidebar_toggle = ft.IconButton(
            icon=ft.Icons.MENU if self.sidebar_collapsed else ft.Icons.MENU_OPEN,
            icon_color=ui_theme.primary(),
            tooltip="Mở rộng menu" if self.sidebar_collapsed else "Thu gọn menu",
            on_click=lambda _e: self._set_sidebar_collapsed(not self.sidebar_collapsed),
        )
        rail = ft.NavigationRail(
            selected_index=self.nav_index,
            extended=not self.sidebar_collapsed,
            label_type=ft.NavigationRailLabelType.NONE,
            min_width=72,
            min_extended_width=220,
            bgcolor=ft.Colors.TRANSPARENT,
            indicator_color=ft.Colors.with_opacity(0.16, ui_theme.primary()),
            selected_label_text_style=ft.TextStyle(color=ui_theme.primary(), weight=ft.FontWeight.BOLD),
            unselected_label_text_style=ft.TextStyle(color=ui_theme.text_muted()),
            leading=self.sidebar_toggle,
            destinations=[
                ft.NavigationRailDestination(icon=ft.Icons.SPACE_DASHBOARD_OUTLINED, selected_icon=ft.Icons.SPACE_DASHBOARD, label="Tổng Quan"),
                ft.NavigationRailDestination(icon=ft.Icons.FOLDER_OUTLINED, selected_icon=ft.Icons.FOLDER, label="Danh sách dự án"),
                ft.NavigationRailDestination(icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS, label="Cấu hình"),
                ft.NavigationRailDestination(icon=ft.Icons.HISTORY, selected_icon=ft.Icons.HISTORY, label="Nhật ký hệ thống"),
            ],
            on_change=self._on_nav_change,
        )
        self.navigation_rail = rail
        self.sidebar_container = ft.Container(
            width=72 if self.sidebar_collapsed else 220,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            bgcolor=ui_theme.surface(),
            border=ft.Border.only(right=ft.BorderSide(1, ui_theme.line())),
            content=rail,
        )

        top_bar = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Row(spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    kit.logo_mark(34),
                    ft.Column(spacing=0, controls=[
                        ft.Text(APP_NAME, size=17, weight=ft.FontWeight.BOLD),
                        kit.eyebrow("Secure Archive System"),
                    ]),
                ]),
                ft.Row(
                    spacing=8,
                    controls=[
                        self._theme_mode_button(),
                        kit.ghost_button("Đổi mật khẩu", icon=ft.Icons.KEY, on_click=lambda _e: self.show_change_password()),
                        kit.ghost_button("Đăng xuất", icon=ft.Icons.LOGOUT, on_click=lambda _e: self.show_role_selection()),
                    ],
                ),
            ],
        )

        self.content_switcher = content_switcher()
        self.content_area = ft.Container(expand=True, padding=24, content=self.content_switcher)
        self._render_content()

        layout = ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.Container(
                    content=top_bar,
                    padding=ft.Padding.symmetric(vertical=14, horizontal=20),
                    bgcolor=ui_theme.surface(),
                    border=ft.Border.only(bottom=ft.BorderSide(1, ui_theme.line())),
                ),
                ft.Row(
                    expand=True,
                    spacing=0,
                    controls=[
                        self.sidebar_container,
                        self.content_area,
                    ],
                ),
            ],
        )
        self.set_root(layout)

    def _set_sidebar_collapsed(self, collapsed: bool, *, update: bool = True) -> None:
        self.sidebar_collapsed = collapsed
        if self.navigation_rail is None or self.sidebar_container is None:
            return
        self.navigation_rail.extended = not collapsed
        self.sidebar_container.width = 72 if collapsed else 220
        if self.sidebar_toggle is not None:
            self.sidebar_toggle.icon = ft.Icons.MENU if collapsed else ft.Icons.MENU_OPEN
            self.sidebar_toggle.tooltip = "Mở rộng menu" if collapsed else "Thu gọn menu"
        if update:
            self.page.update()

    def _on_nav_change(self, event: ft.ControlEvent) -> None:
        self.nav_index = event.control.selected_index
        self.current_project_id = None
        self._set_sidebar_collapsed(False, update=False)
        self._render_content()
        self.page.update()

    def _render_content(self) -> None:
        if self.current_project_id is not None:
            self.content_switcher.content = console_view.build(self, self.current_project_id)
        elif self.nav_index == NAV_OVERVIEW:
            self.content_switcher.content = overview_view.build(self)
        elif self.nav_index == NAV_PROJECTS:
            self.content_switcher.content = project_list_view.build(self)
        elif self.nav_index == NAV_SETTINGS:
            self.content_switcher.content = settings_view.build(self)
        elif self.nav_index == NAV_AUDIT:
            self.content_switcher.content = audit_view.build(self)

    def refresh_content(self) -> None:
        self._render_content()
        self.page.update()

    def open_project(self, project_id: int) -> None:
        self.current_project_id = project_id
        self.content_switcher.content = console_view.build(self, project_id)
        self._set_sidebar_collapsed(True)

    def close_project(self) -> None:
        self.current_project_id = None
        self._set_sidebar_collapsed(False, update=False)
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
