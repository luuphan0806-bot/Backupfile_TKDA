from __future__ import annotations

import flet as ft

from ... import kit
from ...theme import DANGER, SUCCESS, WARNING, TEXT_MUTED, status_color, status_label
from ....service_core import JOB_REPLACE_CONFLICT, JOB_SCAN, JOB_VERIFY
from ....constants import (
    STATUS_ERROR,
    STATUS_HASH_PENDING,
    STATUS_INVALID_STRUCTURE,
    STATUS_LOCKED,
    STATUS_WAITING_STABLE,
)


def build(ctx) -> ft.Control:
    db = ctx.db
    project_id = ctx.project_id
    counts = db.dashboard_counts(project_id)

    status_banner = ft.Text("", color=ft.Colors.PRIMARY)

    def set_busy(message: str) -> None:
        status_banner.value = message
        status_banner.color = ft.Colors.PRIMARY
        ctx.page.update()

    def set_done(message: str, *, failed: bool = False) -> None:
        status_banner.value = message
        status_banner.color = ft.Colors.ERROR if failed else ft.Colors.PRIMARY
        ctx.refresh()

    def run_backup(_event) -> None:
        job_id = db.enqueue_job(project_id, JOB_SCAN, requested_by_type="ADMIN")
        set_done(f"Đã gửi yêu cầu sao lưu #{job_id}.")

    def run_verify(_event) -> None:
        job_id = db.enqueue_job(project_id, JOB_VERIFY, requested_by_type="ADMIN")
        set_done(f"Đã gửi yêu cầu kiểm tra toàn vẹn #{job_id}.")

    toolbar = kit.card(
        ft.Row(
            spacing=10,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                kit.primary_button("Sao lưu ngay", icon=ft.Icons.PLAY_ARROW, on_click=run_backup),
                kit.ghost_button("Kiểm tra toàn vẹn", icon=ft.Icons.FACT_CHECK, on_click=run_verify),
                kit.ghost_button("Làm mới", icon=ft.Icons.REFRESH, on_click=lambda _e: ctx.refresh()),
                status_banner,
            ],
        ),
        padding=14,
    )

    kpi_row = ft.Row(
        spacing=12,
        controls=[
            kit.stat_tile("Chờ kiểm tra toàn vẹn", counts.get(STATUS_HASH_PENDING, 0), WARNING, icon=ft.Icons.FACT_CHECK),
            kit.stat_tile("File đã khóa", counts.get(STATUS_LOCKED, 0), SUCCESS, icon=ft.Icons.LOCK),
            kit.stat_tile("Lỗi cần xử lý", counts.get(STATUS_ERROR, 0) + counts.get(STATUS_INVALID_STRUCTURE, 0), DANGER, icon=ft.Icons.ERROR_OUTLINE),
            kit.stat_tile("Xung đột mở", counts.get("OPEN_CONFLICTS", 0), WARNING, icon=ft.Icons.WARNING_AMBER),
        ],
    )

    clients = db.list_clients(project_id)
    all_files = db.list_backup_files(project_id, limit=2000)
    pending_statuses = {STATUS_WAITING_STABLE, STATUS_HASH_PENDING}
    error_statuses = {STATUS_ERROR, STATUS_INVALID_STRUCTURE}

    client_rows = []
    for client in clients:
        pending = sum(1 for row in all_files if row["client_code"] == client.client_code and row["status"] in pending_statuses)
        errors = sum(1 for row in all_files if row["client_code"] == client.client_code and row["status"] in error_statuses)
        client_rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(client.client_code)),
                    ft.DataCell(ft.Text(client.share_path)),
                    ft.DataCell(kit.badge("Bật", SUCCESS) if client.enabled else kit.badge("Tắt", TEXT_MUTED)),
                    ft.DataCell(ft.Text(str(pending), color=WARNING if pending else None)),
                    ft.DataCell(ft.Text(str(errors), color=DANGER if errors else None)),
                ]
            )
        )
    clients_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Máy trạm")),
            ft.DataColumn(ft.Text("Thư mục chia sẻ")),
            ft.DataColumn(ft.Text("Trạng thái")),
            ft.DataColumn(ft.Text("Đang chờ")),
            ft.DataColumn(ft.Text("Lỗi")),
        ],
        rows=client_rows,
    )

    activity_rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(row["client_code"])),
                ft.DataCell(ft.Text(row["relative_project_path"])),
                ft.DataCell(kit.badge(status_label(row["status"]), status_color(row["status"]))),
                ft.DataCell(ft.Text(row["error_message"] or "", max_lines=1)),
            ]
        )
        for row in all_files[:100]
    ]
    activity_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Máy trạm")),
            ft.DataColumn(ft.Text("Đường dẫn trong dự án")),
            ft.DataColumn(ft.Text("Trạng thái")),
            ft.DataColumn(ft.Text("Thông báo")),
        ],
        rows=activity_rows,
    )

    conflicts = db.list_conflicts(project_id)

    def replace_conflict(conflict_id: int) -> None:
        job_id = db.enqueue_job(
            project_id, JOB_REPLACE_CONFLICT, requested_by_type="ADMIN",
            payload={"conflict_id": conflict_id}, deduplicate=False,
        )
        set_done(f"Đã gửi yêu cầu xử lý tệp khác nội dung #{job_id}.")

    conflict_rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(row["client_code"])),
                ft.DataCell(ft.Text(row["source_path"], max_lines=1)),
                ft.DataCell(ft.Text(row["dest_path"], max_lines=1)),
                ft.DataCell(
                    kit.ghost_button(
                        "Thay thế", icon=ft.Icons.SWAP_HORIZ, accent=WARNING,
                        on_click=lambda _e, cid=row["id"]: replace_conflict(cid),
                    )
                ),
            ]
        )
        for row in conflicts
    ]
    conflicts_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Máy trạm")),
            ft.DataColumn(ft.Text("Nguồn")),
            ft.DataColumn(ft.Text("Đích")),
            ft.DataColumn(ft.Text("")),
        ],
        rows=conflict_rows,
    )

    return ft.Column(
        expand=True,
        spacing=18,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            toolbar,
            kpi_row,
            kit.eyebrow("Tình trạng máy trạm"),
            kit.table_frame(clients_table),
            kit.eyebrow("Hoạt động backup gần đây"),
            kit.table_frame(activity_table),
            kit.eyebrow(f"Xung đột đang mở ({len(conflicts)})"),
            kit.table_frame(conflicts_table) if conflicts else ft.Text("Không có xung đột nào.", color=TEXT_MUTED),
        ],
    )
