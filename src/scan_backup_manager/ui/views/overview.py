from __future__ import annotations

from datetime import datetime, timezone

import flet as ft

from ..theme import DANGER, INFO, SUCCESS, WARNING


def _kpi_card(title: str, value: int, color: str) -> ft.Control:
    return ft.Container(
        expand=True,
        padding=18,
        border_radius=14,
        bgcolor=ft.Colors.with_opacity(0.12, color),
        content=ft.Column(
            spacing=4,
            controls=[
                ft.Text(title, size=12, weight=ft.FontWeight.BOLD, color=color),
                ft.Text(str(value), size=30, weight=ft.FontWeight.BOLD, color=color),
            ],
        ),
    )


def build(shell) -> ft.Control:
    db = shell.state.db
    counts = db.dashboard_counts_all_projects()
    projects = db.list_projects()
    heartbeat = db.latest_heartbeat()
    heartbeat_ok = False
    if heartbeat:
        heartbeat_ok = (
            datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat["last_seen_at"])
        ).total_seconds() < 30
    job_counts = db.job_summary()

    service_banner = ft.Container(
        padding=14,
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.12, SUCCESS if heartbeat_ok else DANGER),
        content=ft.Row(
            controls=[
                ft.Icon(
                    ft.Icons.CLOUD_DONE if heartbeat_ok else ft.Icons.CLOUD_OFF,
                    color=SUCCESS if heartbeat_ok else DANGER,
                ),
                ft.Text(
                    "Dịch vụ sao lưu đang hoạt động"
                    if heartbeat_ok else "Mất kết nối dịch vụ sao lưu",
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    f"Đang xử lý: {job_counts.get('RUNNING', 0)} · "
                    f"Đang chờ: {job_counts.get('PENDING', 0)}",
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ],
        ),
    )

    kpi_row = ft.Row(
        spacing=14,
        controls=[
            _kpi_card("Dự án", counts.get("PROJECTS", 0), INFO),
            _kpi_card("Chờ kiểm tra toàn vẹn", counts.get("HASH_PENDING", 0), WARNING),
            _kpi_card("File đã khóa", counts.get("LOCKED", 0), SUCCESS),
            _kpi_card("Lỗi cần xử lý", counts.get("ERROR", 0), DANGER),
            _kpi_card("Xung đột mở", counts.get("OPEN_CONFLICTS", 0), WARNING),
        ],
    )

    def project_row(project) -> ft.Control:
        project_id = project.id or 0
        project_counts = db.dashboard_counts(project_id)
        errors = project_counts.get("ERROR", 0) + project_counts.get("INVALID_STRUCTURE", 0)
        conflicts = project_counts.get("OPEN_CONFLICTS", 0)
        health_color = DANGER if errors or conflicts else SUCCESS
        health_label = "Cần chú ý" if errors or conflicts else "Ổn định"

        return ft.Container(
            padding=14,
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
                        ],
                    ),
                    ft.Row(
                        spacing=16,
                        controls=[
                            ft.Container(
                                padding=ft.Padding.symmetric(vertical=4, horizontal=10),
                                border_radius=999,
                                bgcolor=ft.Colors.with_opacity(0.15, health_color),
                                content=ft.Text(health_label, size=12, color=health_color, weight=ft.FontWeight.BOLD),
                            ),
                            ft.FilledButton("Mở", on_click=lambda _e, pid=project_id: shell.open_project(pid)),
                        ],
                    ),
                ],
            ),
        )

    if projects:
        project_list: ft.Control = ft.Column(spacing=10, controls=[project_row(p) for p in projects])
    else:
        project_list = ft.Text("Chưa có dự án nào. Vào \"Danh sách dự án\" để tạo dự án đầu tiên.", color=ft.Colors.ON_SURFACE_VARIANT)

    return ft.Column(
        expand=True,
        spacing=20,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            service_banner,
            ft.Text("Tổng Quan", size=22, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Tổng hợp tình trạng toàn bộ dự án trong hệ thống.",
                size=13, color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            kpi_row,
            ft.Text("Tình trạng từng dự án", size=16, weight=ft.FontWeight.BOLD),
            project_list,
        ],
    )
