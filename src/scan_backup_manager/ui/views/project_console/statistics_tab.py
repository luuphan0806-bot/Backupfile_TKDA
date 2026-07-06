from __future__ import annotations

from datetime import datetime, timedelta

import flet as ft
import flet_charts as fc

from ...theme import DANGER, INFO, SUCCESS, WARNING
from ...workers import run_worker


def _stat_tile(title: str, value: str, color: str) -> ft.Control:
    return ft.Container(
        expand=True,
        padding=16,
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.12, color),
        content=ft.Column(
            spacing=4,
            controls=[
                ft.Text(title, size=12, weight=ft.FontWeight.BOLD, color=color),
                ft.Text(value, size=22, weight=ft.FontWeight.BOLD, color=color),
            ],
        ),
    )


def build(ctx) -> ft.Control:
    stats = ctx.stats
    project_id = ctx.project_id
    today = datetime.now().date()
    default_from = (today - timedelta(days=30)).isoformat()
    default_to = today.isoformat()

    date_from_field = ft.TextField(label="Từ ngày", width=160, value=default_from, hint_text="YYYY-MM-DD")
    date_to_field = ft.TextField(label="Đến ngày", width=160, value=default_to, hint_text="YYYY-MM-DD")
    status_text = ft.Text("", color=ft.Colors.PRIMARY)
    results_container = ft.Container(expand=True)

    def render_results(date_from: str, date_to: str) -> None:
        ratio = stats.completion_ratio(project_id)
        latency = stats.done_to_backup_latency(project_id, date_from, date_to)
        daily = stats.productivity_by_day(project_id, date_from, date_to)
        by_personnel = stats.productivity_by_personnel(project_id, date_from, date_to)

        kpi_row = ft.Row(
            spacing=12,
            controls=[
                _stat_tile("Tổng dòng mapfile", str(ratio.total_rows), INFO),
                _stat_tile("Đã quét xong", f"{ratio.done_count} ({ratio.done_pct:.1f}%)", WARNING),
                _stat_tile("Đã khớp (Matched)", f"{ratio.matched_count} ({ratio.matched_pct:.1f}%)", SUCCESS),
                _stat_tile(
                    "TB từ quét xong đến sao lưu",
                    f"{latency.average_hours:.1f} giờ" if latency.average_hours is not None else "-",
                    DANGER,
                ),
            ],
        )

        max_value = max([1] + [max(day.done_count, day.backed_up_count) for day in daily])
        groups = [
            fc.BarChartGroup(
                x=index,
                rods=[
                    fc.BarChartRod(from_y=0, to_y=day.done_count, color=WARNING, width=8),
                    fc.BarChartRod(from_y=0, to_y=day.backed_up_count, color=SUCCESS, width=8),
                ],
            )
            for index, day in enumerate(daily)
        ]
        chart = fc.BarChart(
            groups=groups,
            max_y=max_value * 1.2,
            bottom_axis=fc.ChartAxis(
                labels=[fc.ChartAxisLabel(value=index, label=day.day[5:]) for index, day in enumerate(daily)],
                label_size=32,
            ),
            height=260,
        ) if daily else ft.Text("Không có dữ liệu trong khoảng ngày đã chọn.", color=ft.Colors.ON_SURFACE_VARIANT)

        chart_legend = ft.Row(
            spacing=16,
            controls=[
                ft.Row(spacing=6, controls=[ft.Container(width=12, height=12, bgcolor=WARNING, border_radius=3), ft.Text("Đã quét xong", size=12)]),
                ft.Row(spacing=6, controls=[ft.Container(width=12, height=12, bgcolor=SUCCESS, border_radius=3), ft.Text("Đã sao lưu", size=12)]),
            ],
        )

        personnel_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Nhân sự")),
                ft.DataColumn(ft.Text("Họ tên")),
                ft.DataColumn(ft.Text("Số hồ sơ đã quét xong")),
            ],
            rows=[
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(row.personnel_code)),
                        ft.DataCell(ft.Text(row.full_name)),
                        ft.DataCell(ft.Text(str(row.done_count))),
                    ]
                )
                for row in by_personnel
            ],
        )

        def do_export(_event) -> None:
            status_text.value = "Đang xuất báo cáo thống kê..."
            ctx.page.update()
            run_worker(
                ctx.page,
                lambda: ctx.reports.export_statistics_report(project_id, date_from, date_to),
                on_success=lambda path: _set_status(f"Đã xuất: {path}"),
                on_error=lambda err: _set_status(f"Xuất báo cáo thất bại:\n{err}", failed=True),
            )

        def _set_status(message: str, *, failed: bool = False) -> None:
            status_text.value = message
            status_text.color = ft.Colors.ERROR if failed else ft.Colors.PRIMARY
            ctx.page.update()

        results_container.content = ft.Column(
            spacing=16,
            controls=[
                kpi_row,
                ft.Text("Năng suất theo ngày", size=15, weight=ft.FontWeight.BOLD),
                chart_legend,
                chart,
                ft.Text("Năng suất theo nhân sự", size=15, weight=ft.FontWeight.BOLD),
                personnel_table if by_personnel else ft.Text("Chưa có dữ liệu nhân sự trong khoảng ngày này.", color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Row(controls=[ft.FilledButton("Xuất báo cáo thống kê", icon=ft.Icons.DOWNLOAD, on_click=do_export), status_text]),
            ],
        )
        ctx.page.update()

    def apply_range(_event=None) -> None:
        render_results(date_from_field.value or default_from, date_to_field.value or default_to)

    filter_bar = ft.Row(
        spacing=10,
        controls=[date_from_field, date_to_field, ft.FilledButton("Xem thống kê", icon=ft.Icons.QUERY_STATS, on_click=apply_range)],
    )

    render_results(default_from, default_to)

    return ft.Column(
        expand=True,
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text(
                "Thống kê năng suất theo khoảng ngày: số hồ sơ đã quét xong, đã sao lưu và thời gian xử lý.",
                size=13, color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            filter_bar,
            results_container,
        ],
    )
