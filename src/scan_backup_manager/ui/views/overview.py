from __future__ import annotations

from datetime import datetime, timezone

import flet as ft

from .. import kit
from ..theme import DANGER, INFO, SUCCESS, WARNING, TEXT_MUTED


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

    banner_color = SUCCESS if heartbeat_ok else DANGER
    service_banner = kit.card(
        ft.Row(
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(
                    ft.Icons.CLOUD_DONE if heartbeat_ok else ft.Icons.CLOUD_OFF,
                    color=banner_color,
                ),
                ft.Text(
                    "Dịch vụ sao lưu đang hoạt động"
                    if heartbeat_ok else "Mất kết nối dịch vụ sao lưu",
                    weight=ft.FontWeight.BOLD, color=banner_color,
                ),
                ft.Container(expand=True),
                ft.Text(
                    f"Đang xử lý: {job_counts.get('RUNNING', 0)}  ·  "
                    f"Đang chờ: {job_counts.get('PENDING', 0)}",
                    color=TEXT_MUTED,
                ),
            ],
        ),
        glow_color=banner_color,
        bgcolor=ft.Colors.with_opacity(0.10, banner_color),
        border_color=ft.Colors.with_opacity(0.35, banner_color),
        padding=14,
        radius=8,
    )

    kpi_row = ft.Row(
        spacing=14,
        controls=[
            kit.stat_tile("Dự án", counts.get("PROJECTS", 0), INFO, icon=ft.Icons.FOLDER),
            kit.stat_tile("Chờ kiểm tra toàn vẹn", counts.get("HASH_PENDING", 0), WARNING, icon=ft.Icons.FACT_CHECK),
            kit.stat_tile("File đã khóa", counts.get("LOCKED", 0), SUCCESS, icon=ft.Icons.LOCK),
            kit.stat_tile("Lỗi cần xử lý", counts.get("ERROR", 0), DANGER, icon=ft.Icons.ERROR_OUTLINE),
            kit.stat_tile("Xung đột mở", counts.get("OPEN_CONFLICTS", 0), WARNING, icon=ft.Icons.WARNING_AMBER),
        ],
    )

    def project_row(project) -> ft.Control:
        project_id = project.id or 0
        project_counts = db.dashboard_counts(project_id)
        errors = project_counts.get("ERROR", 0) + project_counts.get("INVALID_STRUCTURE", 0)
        conflicts = project_counts.get("OPEN_CONFLICTS", 0)
        health_color = DANGER if errors or conflicts else SUCCESS
        health_label = "Cần chú ý" if errors or conflicts else "Ổn định"

        return kit.card(
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Column(
                        spacing=2,
                        controls=[
                            ft.Text(project.display_name, size=15, weight=ft.FontWeight.BOLD),
                            ft.Text(project.project_code, size=12, color=TEXT_MUTED),
                        ],
                    ),
                    ft.Row(
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            kit.badge(health_label, health_color),
                            kit.primary_button("Mở", icon=ft.Icons.ARROW_FORWARD, on_click=lambda _e, pid=project_id: shell.open_project(pid)),
                        ],
                    ),
                ],
            ),
            padding=14, radius=8,
        )

    if projects:
        project_list: ft.Control = ft.Column(spacing=10, controls=[project_row(p) for p in projects])
    else:
        project_list = ft.Text("Chưa có dự án nào. Vào \"Danh sách dự án\" để tạo dự án đầu tiên.", color=TEXT_MUTED)

    return ft.Column(
        expand=True,
        spacing=20,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            kit.page_header(
                "Tổng Quan",
                "Tổng hợp tình trạng toàn bộ dự án trong hệ thống.",
                eyebrow_text="Trung tâm điều hành",
            ),
            service_banner,
            kpi_row,
            kit.eyebrow("Tình trạng từng dự án"),
            project_list,
        ],
    )
