from __future__ import annotations

import flet as ft

from ... import kit
from ... import theme as ui_theme
from ...theme import content_switcher

(
    TAB_DASHBOARD,
    TAB_CATALOG,
    TAB_SYSTEM_MAPFILE,
    TAB_LEADER_WORKBENCH,
    TAB_STATISTICS,
    TAB_SETTINGS,
) = range(6)
TAB_LABELS = [
    "Bảng điều hành",
    "Danh mục hồ sơ",
    "Mapfile hệ thống",
    "Leader Workbench",
    "Thống kê",
    "Cấu hình",
]
TAB_ICONS = [
    ft.Icons.SPACE_DASHBOARD_OUTLINED,
    ft.Icons.VIEW_LIST_OUTLINED,
    ft.Icons.GRID_ON_OUTLINED,
    ft.Icons.ASSIGNMENT_TURNED_IN_OUTLINED,
    ft.Icons.INSIGHTS_OUTLINED,
    ft.Icons.TUNE_OUTLINED,
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
            ft.Divider(height=1, color=ui_theme.line()),
            self.content_container,
        ]

    def _build_tab_content(self) -> ft.Control:
        from . import (
            catalog_tab,
            dashboard_tab,
            leader_workbench_tab,
            settings_tab,
            statistics_tab,
            system_mapfile_tab,
        )

        builders = {
            TAB_DASHBOARD: dashboard_tab.build,
            TAB_CATALOG: catalog_tab.build,
            TAB_SYSTEM_MAPFILE: system_mapfile_tab.build,
            TAB_LEADER_WORKBENCH: leader_workbench_tab.build,
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
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        kit.ghost_button("Dự án", icon=ft.Icons.ARROW_BACK, on_click=lambda _e: self.shell.close_project()),
                        ft.Column(
                            spacing=1,
                            controls=[
                                kit.eyebrow(code) if code else kit.eyebrow("Bảng điều khiển"),
                                ft.Text(name, size=20, weight=ft.FontWeight.BOLD),
                            ],
                        ),
                    ],
                ),
            ],
        )

    def _build_tab_bar(self) -> ft.Control:
        items = list(zip(TAB_LABELS, TAB_ICONS))
        return kit.tab_bar(items, self.tab_index, self.switch_tab)


def build(shell, project_id: int) -> ft.Control:
    ctx = ConsoleContext(shell, project_id)
    ctx.render()
    return ctx.root
