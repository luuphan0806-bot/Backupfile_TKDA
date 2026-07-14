from __future__ import annotations

from datetime import datetime, timedelta

import flet as ft

from ... import kit
from ...date_format import DISPLAY_DATE_HINT, display_to_iso, iso_to_display
from ...theme import ACCENT_2, INFO, PRIMARY_DARK, SUCCESS, TEXT_MUTED, WARNING
from ...workers import run_worker


CHART_TOTAL = PRIMARY_DARK
CHART_CHECK = ACCENT_2


def _kind_label(kind: str) -> str:
    return "Check" if kind == "CHECK" else "Scan"


def _legend_swatch(color: str, label: str) -> ft.Control:
    return ft.Row(
        spacing=6,
        controls=[
            ft.Container(width=12, height=12, bgcolor=color, border_radius=3),
            ft.Text(label, size=12, color=TEXT_MUTED),
        ],
    )


def _time_label(value: str) -> str:
    if not value:
        return "--"
    try:
        return datetime.fromisoformat(value).strftime("%H:%M")
    except ValueError:
        return value[11:16] if len(value) >= 16 else value


def _daily_bar_view(days: list[str], daily_totals: dict[str, dict[str, int]], max_y: int) -> ft.Control:
    if not days:
        return ft.Container(
            height=160,
            alignment=ft.Alignment.CENTER,
            content=ft.Text("Không có công việc trong khoảng ngày đã chọn.", color=TEXT_MUTED),
        )
    rows: list[ft.Control] = []
    for day in days:
        total = daily_totals[day]["total"]
        check = daily_totals[day]["check"]
        total_width = max(8, int(360 * total / max_y))
        check_width = max(0, int(360 * check / max_y))
        rows.append(
            ft.Row(
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text(day[5:], width=48, size=11, color=TEXT_MUTED),
                    ft.Stack(
                        width=380,
                        height=24,
                        controls=[
                            ft.Container(
                                width=360,
                                height=10,
                                top=7,
                                bgcolor=ft.Colors.with_opacity(0.12, CHART_TOTAL),
                                border_radius=6,
                            ),
                            ft.Container(
                                width=total_width,
                                height=10,
                                top=7,
                                bgcolor=CHART_TOTAL,
                                border_radius=6,
                            ),
                            ft.Container(
                                width=check_width,
                                height=6,
                                top=9,
                                bgcolor=CHART_CHECK,
                                border_radius=6,
                            ),
                        ],
                    ),
                    ft.Text(f"{total} / {check}", size=11, color=TEXT_MUTED),
                ],
            )
        )
    return ft.Column(spacing=8, controls=rows)


def build(ctx) -> ft.Control:
    stats = ctx.stats
    project_id = ctx.project_id
    today = datetime.now().date()
    default_from = (today - timedelta(days=30)).isoformat()
    default_to = today.isoformat()

    date_from_field = ft.TextField(
        label="Từ ngày",
        width=160,
        value=iso_to_display(default_from),
        hint_text=DISPLAY_DATE_HINT,
        dense=True,
    )
    date_to_field = ft.TextField(
        label="Đến ngày",
        width=160,
        value=iso_to_display(default_to),
        hint_text=DISPLAY_DATE_HINT,
        dense=True,
    )
    status_text = ft.Text("", color=ft.Colors.PRIMARY)
    results_container = ft.Container(expand=True)

    def render_results(date_from: str, date_to: str) -> None:
        rows = stats.job_quantity_by_day(project_id, date_from, date_to)
        personnel_details = stats.personnel_daily_job_details(project_id, date_from, date_to)
        total_quantity = sum(row.quantity for row in rows)
        total_completed = sum(row.completed_count for row in rows)
        job_count = len({(row.task_kind, row.job_title) for row in rows})
        active_days = len({row.day for row in rows})
        active_personnel = len({row.personnel_code for row in personnel_details})

        daily_totals: dict[str, dict[str, int]] = {}
        job_totals: dict[tuple[str, str], int] = {}
        for row in rows:
            bucket = daily_totals.setdefault(row.day, {"total": 0, "check": 0})
            bucket["total"] += row.quantity
            if row.task_kind == "CHECK":
                bucket["check"] += row.quantity
            key = (row.task_kind, row.job_title)
            job_totals[key] = job_totals.get(key, 0) + row.quantity

        days = sorted(daily_totals)
        max_y = max([1] + [daily_totals[day]["total"] for day in days])
        chart = _daily_bar_view(days, daily_totals, max_y)

        detail_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Ngày")),
                ft.DataColumn(ft.Text("Công việc")),
                ft.DataColumn(ft.Text("Loại")),
                ft.DataColumn(ft.Text("Số lượng")),
                ft.DataColumn(ft.Text("Đã chốt")),
                ft.DataColumn(ft.Text("Nhân sự")),
            ],
            rows=[
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(iso_to_display(row.day))),
                        ft.DataCell(ft.Text(row.job_title)),
                        ft.DataCell(ft.Text(_kind_label(row.task_kind))),
                        ft.DataCell(ft.Text(str(row.quantity))),
                        ft.DataCell(ft.Text(str(row.completed_count))),
                        ft.DataCell(ft.Text(str(row.personnel_count))),
                    ]
                )
                for row in rows
            ],
        )

        personnel_detail_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Ngày")),
                ft.DataColumn(ft.Text("Nhân sự")),
                ft.DataColumn(ft.Text("Thứ tự")),
                ft.DataColumn(ft.Text("Công việc")),
                ft.DataColumn(ft.Text("Loại")),
                ft.DataColumn(ft.Text("Sản lượng")),
                ft.DataColumn(ft.Text("Đã chốt")),
                ft.DataColumn(ft.Text("Từ giờ")),
                ft.DataColumn(ft.Text("Cập nhật")),
            ],
            rows=[
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(iso_to_display(row.day))),
                        ft.DataCell(ft.Text(row.full_name)),
                        ft.DataCell(ft.Text(f"#{row.sequence_number}")),
                        ft.DataCell(ft.Text(row.job_title)),
                        ft.DataCell(ft.Text(_kind_label(row.task_kind))),
                        ft.DataCell(ft.Text(str(row.quantity))),
                        ft.DataCell(ft.Text(str(row.completed_count))),
                        ft.DataCell(ft.Text(_time_label(row.started_at))),
                        ft.DataCell(ft.Text(_time_label(row.last_updated_at))),
                    ]
                )
                for row in personnel_details
            ],
        )

        job_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Công việc")),
                ft.DataColumn(ft.Text("Loại")),
                ft.DataColumn(ft.Text("Tổng số lượng")),
            ],
            rows=[
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(job_title)),
                        ft.DataCell(ft.Text(_kind_label(kind))),
                        ft.DataCell(ft.Text(str(quantity))),
                    ]
                )
                for (kind, job_title), quantity in sorted(
                    job_totals.items(),
                    key=lambda item: (-item[1], item[0][0], item[0][1]),
                )
            ],
        )

        results_container.content = ft.Column(
            spacing=16,
            controls=[
                ft.Row(
                    spacing=12,
                    controls=[
                        kit.stat_tile("Tổng số lượng", total_quantity, INFO, icon=ft.Icons.FORMAT_LIST_NUMBERED),
                        kit.stat_tile("Đã chốt", total_completed, SUCCESS, icon=ft.Icons.CHECK_CIRCLE_OUTLINE),
                        kit.stat_tile("Loại công việc", job_count, WARNING, icon=ft.Icons.WORK_OUTLINE),
                        kit.stat_tile("Nhân sự", active_personnel, PRIMARY_DARK, icon=ft.Icons.GROUP_OUTLINED),
                    ],
                ),
                kit.section(
                    "Nhân sự trong ngày",
                    "Xem từng nhân sự làm công việc gì, sản lượng bao nhiêu và bắt đầu từ mấy giờ.",
                    kit.table_frame(personnel_detail_table)
                    if personnel_details
                    else ft.Text("Chưa có dữ liệu nhân sự trong khoảng ngày này.", color=TEXT_MUTED),
                    icon=ft.Icons.BADGE_OUTLINED,
                ),
                kit.section(
                    "Theo ngày",
                    "Số lượng công việc được tạo trong từng ngày.",
                    ft.Column(
                        spacing=10,
                        controls=[
                            ft.Row(
                                spacing=16,
                                controls=[
                                    _legend_swatch(CHART_TOTAL, "Tổng số lượng"),
                                    _legend_swatch(CHART_CHECK, "Trong đó Check"),
                                ],
                            ),
                            chart,
                        ],
                    ),
                    icon=ft.Icons.BAR_CHART,
                ),
                kit.section(
                    "Theo công việc",
                    "Tổng số lượng từng công việc trong khoảng ngày.",
                    kit.table_frame(job_table)
                    if job_totals
                    else ft.Text("Chưa có công việc trong khoảng ngày này.", color=TEXT_MUTED),
                    icon=ft.Icons.WORK_HISTORY,
                ),
                kit.section(
                    "Chi tiết ngày / công việc",
                    "Mỗi dòng là một ngày và một công việc.",
                    kit.table_frame(detail_table)
                    if rows
                    else ft.Text("Không có dữ liệu chi tiết.", color=TEXT_MUTED),
                    icon=ft.Icons.TABLE_ROWS,
                ),
            ],
        )
        ctx.page.update()

    def apply_range(_event=None) -> None:
        try:
            date_from = display_to_iso(date_from_field.value or iso_to_display(default_from))
            date_to = display_to_iso(date_to_field.value or iso_to_display(default_to))
        except ValueError as exc:
            status_text.value = str(exc)
            status_text.color = ft.Colors.ERROR
            ctx.page.update()
            return
        if date_from > date_to:
            status_text.value = "Từ ngày không được lớn hơn Đến ngày."
            status_text.color = ft.Colors.ERROR
            ctx.page.update()
            return
        status_text.value = ""
        render_results(date_from, date_to)

    def export_attendance(_event=None) -> None:
        try:
            date_from = display_to_iso(date_from_field.value or iso_to_display(default_from))
            date_to = display_to_iso(date_to_field.value or iso_to_display(default_to))
        except ValueError as exc:
            status_text.value = str(exc)
            status_text.color = ft.Colors.ERROR
            ctx.page.update()
            return
        if date_from > date_to:
            status_text.value = "Từ ngày không được lớn hơn Đến ngày."
            status_text.color = ft.Colors.ERROR
            ctx.page.update()
            return
        status_text.value = "Đang xuất dữ liệu chấm công..."
        status_text.color = ft.Colors.PRIMARY
        ctx.page.update()

        def on_success(path) -> None:
            status_text.value = f"Đã xuất chấm công: {path}"
            status_text.color = SUCCESS
            ctx.page.update()

        def on_error(message: str) -> None:
            status_text.value = message.splitlines()[-1] if message else "Không thể xuất chấm công."
            status_text.color = ft.Colors.ERROR
            ctx.page.update()

        run_worker(
            ctx.page,
            lambda: ctx.reports.export_mausham_cong(project_id, date_from, date_to),
            on_success=on_success,
            on_error=on_error,
        )

    date_from_field.on_submit = apply_range
    date_to_field.on_submit = apply_range

    filter_bar = kit.card(
        ft.Row(
            spacing=10,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                date_from_field,
                date_to_field,
                kit.primary_button("Xem thống kê", icon=ft.Icons.QUERY_STATS, on_click=apply_range),
                kit.ghost_button("Xuất chấm công", icon=ft.Icons.FILE_DOWNLOAD, on_click=export_attendance),
                status_text,
            ],
        ),
        padding=14,
        radius=8,
    )

    render_results(default_from, default_to)

    return ft.Column(
        expand=True,
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text(
                "Thống kê số lượng công việc theo ngày và theo loại công việc.",
                size=13,
                color=TEXT_MUTED,
            ),
            filter_bar,
            results_container,
        ],
    )
