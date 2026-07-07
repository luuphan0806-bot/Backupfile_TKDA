from __future__ import annotations

import flet as ft

from ...theme import content_switcher

(
    TAB_DASHBOARD,
    TAB_CATALOG,
    TAB_SYSTEM_MAPFILE,
    TAB_STATISTICS,
    TAB_SETTINGS,
) = range(5)
TAB_LABELS = [
    "Bảng điều hành",
    "Danh mục hồ sơ",
    "Mapfile hệ thống",
    "Thống kê",
    "Cấu hình",
]


class ConsoleContext:
    """Owns the sub-navigation state for one open project's console.

    Created fresh every time a project is opened from the shell; the 6
    sub-tabs are plain function modules (dashboard_tab, mapfile_tab, ...)
    that take this context and return a control, mirroring the top-level
    shell's own render pattern.
    """

    def __init__(self, shell, project_id: int):
        self.shell = shell
        self.page = shell.page
        self.db = shell.state.db
        self.backup = shell.state.backup
        self.mapfiles = shell.state.mapfiles
        self.reports = shell.state.reports
        self.stats = shell.state.stats
        self.project_id = project_id
        self.project = self.db.get_project(project_id)
        self.tab_index = TAB_DASHBOARD
        self.view_state: dict[str, dict] = {}
        self.root = ft.Column(expand=True, spacing=14)
        self.content_container = content_switcher()

    def switch_tab(self, index: int) -> None:
        if index == self.tab_index:
            return
        self.tab_index = index
        self.project = self.db.get_project(self.project_id)
        self.render()
        self.page.update()

    def refresh(self) -> None:
        self.project = self.db.get_project(self.project_id)
        self.render()
        self.page.update()

    def render(self) -> None:
        self.content_container.content = self._build_tab_content()
        self.root.controls = [
            self._build_header(),
            self._build_tab_bar(),
            ft.Divider(height=1),
            self.content_container,
        ]

    def _build_tab_content(self) -> ft.Control:
        from . import (
            catalog_tab,
            dashboard_tab,
            settings_tab,
            statistics_tab,
            system_mapfile_tab,
        )

        builders = {
            TAB_DASHBOARD: dashboard_tab.build,
            TAB_CATALOG: catalog_tab.build,
            TAB_SYSTEM_MAPFILE: system_mapfile_tab.build,
            TAB_STATISTICS: statistics_tab.build,
            TAB_SETTINGS: settings_tab.build,
        }
        return builders[self.tab_index](self)

    def _build_header(self) -> ft.Control:
        name = self.project.display_name if self.project else "?"
        code = self.project.project_code if self.project else ""
        return ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Row(
                    spacing=12,
                    controls=[
                        ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip="Quay lại danh sách dự án", on_click=lambda _e: self.shell.close_project()),
                        ft.Column(
                            spacing=0,
                            controls=[
                                ft.Text(name, size=18, weight=ft.FontWeight.BOLD),
                                ft.Text(code, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                            ],
                        ),
                    ],
                ),
            ],
        )

    def _build_tab_bar(self) -> ft.Control:
        buttons = []
        for index, label in enumerate(TAB_LABELS):
            if index == self.tab_index:
                buttons.append(ft.FilledButton(label, on_click=lambda _e, i=index: self.switch_tab(i)))
            else:
                buttons.append(ft.OutlinedButton(label, on_click=lambda _e, i=index: self.switch_tab(i)))
        return ft.Row(spacing=8, wrap=True, controls=buttons)


def build(shell, project_id: int) -> ft.Control:
    ctx = ConsoleContext(shell, project_id)
    ctx.render()
    return ctx.root
