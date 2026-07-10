from __future__ import annotations

from datetime import datetime, timedelta

import flet as ft
import flet_charts as fc

from ... import kit
from ...date_format import DISPLAY_DATE_HINT, display_to_iso, iso_to_display
from ...theme import ACCENT_2, DANGER, INFO, PRIMARY_DARK, SUCCESS, WARNING, TEXT_MUTED
from ...workers import run_worker

# Two-series categorical pair for the productivity chart. Cyan vs magenta is a
# CVD-robust duo (they separate on both lightness and the red axis that stays
# intact under protan/deutan); status hues (green/amber) are deliberately kept
# out of the series role. Series identity is reinforced by paired position per
# day + the legend, so it never rests on colour alone.
CHART_DONE = PRIMARY_DARK
CHART_BACKED = ACCENT_2


def _legend_swatch(color: str, label: str) -> ft.Control:
    return ft.Row(
        spacing=6,
        controls=[
            ft.Container(width=12, height=12, bgcolor=color, border_radius=3),
            ft.Text(label, size=12, color=TEXT_MUTED),
        ],
    )


def build(ctx) -> ft.Control:
    stats = ctx.stats
    project_id = ctx.project_id
    today = datetime.now().date()
    default_from = (today - timedelta(days=30)).isoformat()
    default_to = today.isoformat()

    date_from_field = ft.TextField(label="Từ ngày", width=160, value=iso_to_display(default_from), hint_text=DISPLAY_DATE_HINT)
    date_to_field = ft.TextField(label="Đến ngày", width=160, value=iso_to_display(default_to), hint_text=DISPLAY_DATE_HINT)
    status_text = ft.Text("", color=ft.Colors.PRIMARY)
    results_container = ft.Container(expand=True)

    def render_results(date_from: str, date_to: str) -> None:
        ratio = stats.completion_ratio(project_id)
        latency = stats.done_to_backup_latency(project_id, date_from, date_to)
        daily = stats.productivity_by_day(project_id, date_from, date_to)
        by_personnel = stats.productivity_by_personnel(project_id, date_from, date_to)
        paper_sizes = stats.paper_size_summary(project_id, date_from, date_to)

        kpi_row = ft.Row(
            spacing=12,
            controls=[
                kit.stat_tile("Tổng dòng mapfile", str(ratio.total_rows), INFO, icon=ft.Icons.LIST_ALT),
                kit.stat_tile("Đã quét xong", f"{ratio.done_count} ({ratio.done_pct:.1f}%)", WARNING, icon=ft.Icons.DOCUMENT_SCANNER),
                kit.stat_tile("Đã khớp (Matched)", f"{ratio.matched_count} ({ratio.matched_pct:.1f}%)", SUCCESS, icon=ft.Icons.VERIFIED),
                kit.stat_tile(
                    "TB từ quét xong đến sao lưu",
                    f"{latency.average_hours:.1f} giờ" if latency.average_hours is not None else "-",
                    DANGER, icon=ft.Icons.TIMER_OUTLINED,
                ),
            ],
        )

        max_value = max([1] + [max(day.done_count, day.backed_up_count) for day in daily])
        groups = [
            fc.BarChartGroup(
                x=index,
                rods=[
                    fc.BarChartRod(
                        from_y=0, to_y=day.done_count, color=CHART_DONE, width=9, border_radius=4,
                        tooltip=f"{day.day[5:]} · Đã quét xong: {day.done_count}",
                    ),
                    fc.BarChartRod(
                        from_y=0, to_y=day.backed_up_count, color=CHART_BACKED, width=9, border_radius=4,
                        tooltip=f"{day.day[5:]} · Đã sao lưu: {day.backed_up_count}",
                    ),
                ],
            )
            for index, day in enumerate(daily)
        ]
        chart = fc.BarChart(
            groups=groups,
            interactive=True,
            max_y=max_value * 1.2,
            bgcolor=ft.Colors.TRANSPARENT,
            bottom_axis=fc.ChartAxis(
                labels=[
                    fc.ChartAxisLabel(value=index, label=ft.Text(day.day[5:], size=10, color=TEXT_MUTED))
                    for index, day in enumerate(daily)
                ],
                label_size=32,
            ),
            height=260,
        ) if daily else ft.Text("Không có dữ liệu trong khoảng ngày đã chọn.", color=TEXT_MUTED)

        chart_legend = ft.Row(
            spacing=16,
            controls=[
                _legend_swatch(CHART_DONE, "Đã quét xong"),
                _legend_swatch(CHART_BACKED, "Đã sao lưu"),
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

        paper_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Khổ giấy")),
                ft.DataColumn(ft.Text("Số trang")),
                ft.DataColumn(ft.Text("Số file")),
            ],
            rows=[
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(row.paper_code)),
                        ft.DataCell(ft.Text(str(row.page_count))),
                        ft.DataCell(ft.Text(str(row.file_count))),
                    ]
                )
                for row in paper_sizes
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
                kit.eyebrow("Năng suất theo ngày"),
                chart_legend,
                kit.card(chart, padding=16) if daily else chart,
                kit.eyebrow("Năng suất theo nhân sự"),
                kit.table_frame(personnel_table) if by_personnel else ft.Text("Chưa có dữ liệu nhân sự trong khoảng ngày này.", color=TEXT_MUTED),
                kit.eyebrow("Thống kê khổ giấy thực tế"),
                kit.table_frame(paper_table) if paper_sizes else ft.Text("Chưa có dữ liệu khổ giấy thực tế trong khoảng ngày này.", color=TEXT_MUTED),
                ft.Row(controls=[kit.primary_button("Xuất báo cáo thống kê", icon=ft.Icons.DOWNLOAD, on_click=do_export), status_text]),
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
        render_results(date_from, date_to)

    filter_bar = kit.card(
        ft.Row(
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[date_from_field, date_to_field, kit.primary_button("Xem thống kê", icon=ft.Icons.QUERY_STATS, on_click=apply_range)],
        ),
        padding=14,
    )

    render_results(default_from, default_to)

    return ft.Column(
        expand=True,
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text(
                "Thống kê năng suất theo khoảng ngày: số hồ sơ đã quét xong, đã sao lưu và thời gian xử lý.",
                size=13, color=TEXT_MUTED,
            ),
            filter_bar,
            results_container,
        ],
    )
