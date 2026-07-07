from __future__ import annotations

import flet as ft

from ....models import (
    Client,
    DirectoryLevel,
    MapfileProfile,
    Personnel,
    Project,
    ProjectSettings,
)
from ...theme import LEVEL_LABELS

LEVEL_TYPES = ["YEAR4", "ENUM", "INTEGER", "TEXT"]


def _section(title: str, subtitle: str, content: ft.Control) -> ft.Control:
    return ft.Container(
        padding=20,
        border_radius=14,
        bgcolor=ft.Colors.SURFACE,
        border=ft.Border.all(
            1.4, ft.Colors.with_opacity(0.42, ft.Colors.PRIMARY)
        ),
        shadow=ft.BoxShadow(
            blur_radius=14,
            spread_radius=0,
            color=ft.Colors.with_opacity(0.22, ft.Colors.BLACK),
            offset=ft.Offset(0, 4),
        ),
        content=ft.Column(
            spacing=14,
            controls=[
                ft.Row(
                    spacing=10,
                    controls=[
                        ft.Container(
                            width=4, height=38, border_radius=4,
                            bgcolor=ft.Colors.PRIMARY,
                        ),
                        ft.Column(
                            spacing=2,
                            controls=[
                                ft.Text(title, size=16, weight=ft.FontWeight.BOLD),
                                ft.Text(
                                    subtitle, size=12,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                ),
                            ],
                        ),
                    ],
                ),
                ft.Divider(height=1, color=ft.Colors.with_opacity(0.24, ft.Colors.PRIMARY)),
                content,
            ],
        ),
    )


def _build_project_section(ctx) -> ft.Control:
    db = ctx.db
    project = ctx.project
    code_field = ft.TextField(label="Mã dự án", value=project.project_code if project else "", width=220)
    name_field = ft.TextField(label="Tên hiển thị", value=project.display_name if project else "", width=260)
    backup_field = ft.TextField(label="Thư mục backup", value=project.backup_root if project else "", expand=True)
    staging_field = ft.TextField(label="Thư mục staging", value=project.staging_dir if project else "", expand=True)
    conflict_field = ft.TextField(label="Kho xung đột", value=project.conflict_archive_dir if project else "", expand=True)
    reports_field = ft.TextField(label="Thư mục báo cáo", value=project.reports_dir if project else "", expand=True)
    enabled_checkbox = ft.Checkbox(label="Kích hoạt", value=project.enabled if project else True)
    error_text = ft.Text("", color=ft.Colors.ERROR)

    def save_project(_event) -> None:
        try:
            db.save_project(
                Project(
                    ctx.project_id, code_field.value or "", name_field.value or "",
                    backup_field.value or "", staging_field.value or "",
                    conflict_field.value or "", reports_field.value or "",
                    enabled_checkbox.value,
                )
            )
        except ValueError as exc:
            error_text.value = str(exc)
            ctx.page.update()
            return
        ctx.refresh()

    levels = list(db.list_directory_levels(ctx.project_id))
    level_name_field = ft.TextField(label="Tên tầng", width=180)
    level_type_dropdown = ft.Dropdown(
        label="Kiểu kiểm tra", width=180, value="TEXT",
        options=[ft.dropdown.Option(key=t, text=LEVEL_LABELS[t]) for t in LEVEL_TYPES],
    )
    level_values_field = ft.TextField(label="Giá trị hợp lệ (cách nhau bằng dấu phẩy)", width=280)
    levels_error = ft.Text("", color=ft.Colors.ERROR)

    def add_level(_event) -> None:
        name = (level_name_field.value or "").strip()
        if not name:
            levels_error.value = "Cần nhập tên tầng thư mục."
            ctx.page.update()
            return
        values = [v.strip() for v in (level_values_field.value or "").split(",") if v.strip()]
        levels.append(DirectoryLevel(None, ctx.project_id, len(levels) + 1, name, level_type_dropdown.value or "TEXT", values))
        level_name_field.value = ""
        level_values_field.value = ""
        levels_error.value = ""
        _rebuild_levels_table()

    def remove_level(index: int) -> None:
        levels.pop(index)
        _rebuild_levels_table()

    def save_levels(_event) -> None:
        try:
            db.save_directory_levels(ctx.project_id, levels)
        except ValueError as exc:
            levels_error.value = str(exc)
            ctx.page.update()
            return
        ctx.refresh()

    levels_table = ft.DataTable(columns=[ft.DataColumn(ft.Text("Thứ tự")), ft.DataColumn(ft.Text("Tên")), ft.DataColumn(ft.Text("Kiểu")), ft.DataColumn(ft.Text("Giá trị hợp lệ")), ft.DataColumn(ft.Text(""))], rows=[])

    def _rebuild_levels_table() -> None:
        levels_table.rows = [
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(index + 1))),
                    ft.DataCell(ft.Text(level.display_name)),
                    ft.DataCell(ft.Text(LEVEL_LABELS.get(level.validation_type, level.validation_type))),
                    ft.DataCell(ft.Text(", ".join(level.allowed_values))),
                    ft.DataCell(ft.IconButton(icon=ft.Icons.DELETE, on_click=lambda _e, i=index: remove_level(i))),
                ]
            )
            for index, level in enumerate(levels)
        ]
        ctx.page.update()

    _rebuild_levels_table()

    return ft.Column(
        spacing=16,
        controls=[
            _section(
                "Thông tin dự án", "Mã dự án, tên hiển thị và các thư mục lưu trữ.",
                ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(controls=[code_field, name_field, enabled_checkbox]),
                        ft.Row(controls=[backup_field, staging_field]),
                        ft.Row(controls=[conflict_field, reports_field]),
                        error_text,
                        ft.FilledButton("Lưu dự án", on_click=save_project),
                    ],
                ),
            ),
            _section(
                "Cây thư mục chuẩn", "Thứ tự các tầng thư mục bắt buộc bên dưới mã dự án.",
                ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(controls=[level_name_field, level_type_dropdown, level_values_field, ft.FilledButton("Thêm tầng", on_click=add_level)], wrap=True),
                        levels_error,
                        levels_table,
                        ft.FilledButton("Lưu cây thư mục", on_click=save_levels),
                    ],
                ),
            ),
        ],
    )


def _build_mapfile_section(ctx) -> ft.Control:
    db = ctx.db
    try:
        profile = db.get_mapfile_profile(ctx.project_id)
    except ValueError:
        profile = MapfileProfile(None, ctx.project_id, "Default", "", "project", "year", "case_type", "case_number", "file_name")

    sheet_field = ft.TextField(label="Tên trang tính", value=profile.sheet_name, width=160)
    project_col = ft.TextField(label="Cột dự án", value=profile.project_column, width=120)
    year_col = ft.TextField(label="Cột năm", value=profile.year_column, width=120)
    type_col = ft.TextField(label="Cột nhóm hồ sơ", value=profile.case_type_column, width=120)
    number_col = ft.TextField(label="Cột mã hồ sơ", value=profile.case_number_column, width=120)
    file_col = ft.TextField(label="Cột tên tệp", value=profile.file_name_column, width=120)
    status_text = ft.Text("", color=ft.Colors.PRIMARY)

    def save_profile(_event) -> None:
        db.save_mapfile_profile(
            MapfileProfile(
                profile.id, ctx.project_id, "Default", sheet_field.value or "",
                project_col.value or "", year_col.value or "", type_col.value or "",
                number_col.value or "", file_col.value or "",
            )
        )
        status_text.value = "Đã lưu ánh xạ mapfile."
        ctx.page.update()

    return _section(
        "Ánh xạ danh mục hồ sơ", "Khai báo trang tính và tên cột Excel tương ứng.",
        ft.Column(
            spacing=10,
            controls=[
                ft.Row(controls=[sheet_field, project_col, year_col, type_col, number_col, file_col], wrap=True),
                ft.Row(controls=[ft.FilledButton("Lưu ánh xạ", on_click=save_profile), status_text]),
            ],
        ),
    )


def _build_paper_formats_section(ctx) -> ft.Control:
    db = ctx.db
    formats_by_code = {item.code: item for item in db.list_paper_formats(ctx.project_id)}
    formats = [formats_by_code[code] for code in ("A4", "A3", "A0") if code in formats_by_code]

    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Mã")),
            ft.DataColumn(ft.Text("Tên hiển thị")),
            ft.DataColumn(ft.Text("Phần Scan")),
            ft.DataColumn(ft.Text("Phần Check")),
        ],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(item.code, weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(item.display_name)),
                    ft.DataCell(ft.Text("Người Scan / Ngày Scan / Số Trang")),
                    ft.DataCell(ft.Text(f"Số trang {item.code}")),
                ]
            )
            for item in formats
        ],
    )

    return _section(
        "Danh mục khổ giấy",
        "Cố định ba khổ giấy A4, A3, A0. Scan theo dõi riêng từng khổ; Check dùng chung người check và nhập số trang theo từng khổ.",
        ft.Column(
            spacing=10,
            controls=[
                table,
            ],
        ),
    )


def _build_clients_section(ctx) -> ft.Control:
    db = ctx.db
    code_field = ft.TextField(label="Mã máy trạm", width=160)
    share_field = ft.TextField(label="Thư mục chia sẻ máy trạm", width=320)
    notes_field = ft.TextField(label="Ghi chú", width=220)
    enabled_checkbox = ft.Checkbox(label="Kích hoạt", value=True)
    error_text = ft.Text("", color=ft.Colors.ERROR)

    def save_client(_event) -> None:
        code = (code_field.value or "").strip()
        share = (share_field.value or "").strip()
        if not code or not share:
            error_text.value = "Cần nhập mã máy trạm và thư mục chia sẻ."
            ctx.page.update()
            return
        db.save_client(Client(None, ctx.project_id, code, "", share, enabled_checkbox.value, notes_field.value or ""))
        ctx.refresh()

    def delete_client(code: str) -> None:
        db.delete_client(ctx.project_id, code)
        ctx.refresh()

    clients = db.list_clients(ctx.project_id)
    table = ft.DataTable(
        columns=[ft.DataColumn(ft.Text("Mã")), ft.DataColumn(ft.Text("Share")), ft.DataColumn(ft.Text("Ghi chú")), ft.DataColumn(ft.Text("Kích hoạt")), ft.DataColumn(ft.Text(""))],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(c.client_code)),
                    ft.DataCell(ft.Text(c.share_path)),
                    ft.DataCell(ft.Text(c.notes)),
                    ft.DataCell(ft.Text("Có" if c.enabled else "Không")),
                    ft.DataCell(ft.IconButton(icon=ft.Icons.DELETE, on_click=lambda _e, code=c.client_code: delete_client(code))),
                ]
            )
            for c in clients
        ],
    )

    return _section(
        "Máy trạm", "Khai báo các thư mục chia sẻ trên máy trạm cần quét tệp.",
        ft.Column(
            spacing=10,
            controls=[
                ft.Row(controls=[code_field, share_field, notes_field, enabled_checkbox], wrap=True),
                error_text,
                ft.FilledButton("Thêm / cập nhật máy trạm", on_click=save_client),
                table,
            ],
        ),
    )


def _build_personnel_section(ctx) -> ft.Control:
    db = ctx.db
    code_field = ft.TextField(label="Mã nhân sự", width=140)
    name_field = ft.TextField(label="Họ tên", width=220)
    role_field = ft.TextField(label="Vai trò/chức danh", width=200)
    pin_field = ft.TextField(label="PIN khởi tạo/đặt lại (6 số)", width=200, password=True)
    enabled_checkbox = ft.Checkbox(label="Kích hoạt", value=True)
    error_text = ft.Text("", color=ft.Colors.ERROR)

    def save_personnel(_event) -> None:
        code = (code_field.value or "").strip()
        name = (name_field.value or "").strip()
        if not code or not name:
            error_text.value = "Cần nhập mã nhân sự và họ tên."
            ctx.page.update()
            return
        personnel_id = db.save_personnel(Personnel(None, ctx.project_id, code, name, role_field.value or "", enabled_checkbox.value))
        if pin_field.value:
            try:
                db.set_personnel_pin(personnel_id, pin_field.value, must_change=True)
            except ValueError as exc:
                error_text.value = str(exc)
                ctx.page.update()
                return
        ctx.refresh()

    def delete_personnel(personnel_id: int) -> None:
        db.delete_personnel(personnel_id)
        ctx.refresh()

    personnel = db.list_personnel(ctx.project_id)
    table = ft.DataTable(
        columns=[ft.DataColumn(ft.Text("Mã")), ft.DataColumn(ft.Text("Họ tên")), ft.DataColumn(ft.Text("Vai trò")), ft.DataColumn(ft.Text("Kích hoạt")), ft.DataColumn(ft.Text(""))],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(p.personnel_code)),
                    ft.DataCell(ft.Text(p.full_name)),
                    ft.DataCell(ft.Text(p.role_name)),
                    ft.DataCell(ft.Text("Có" if p.enabled else "Không")),
                    ft.DataCell(ft.IconButton(icon=ft.Icons.DELETE, on_click=lambda _e, pid=p.id: delete_personnel(pid))),
                ]
            )
            for p in personnel
        ],
    )

    return _section(
        "Nhân sự", "Quản lý danh sách nhân sự có thể được giao công việc dự án.",
        ft.Column(
            spacing=10,
            controls=[
                ft.Row(controls=[code_field, name_field, role_field, pin_field, enabled_checkbox], wrap=True),
                error_text,
                ft.FilledButton("Thêm / cập nhật nhân sự", on_click=save_personnel),
                table,
            ],
        ),
    )


def _build_operations_section(ctx) -> ft.Control:
    db = ctx.db
    settings = db.get_project_settings(ctx.project_id)
    poll_field = ft.TextField(label="Chu kỳ quét tự động (giây)", value=str(settings.poll_interval_seconds), width=220)
    stability_field = ft.TextField(label="Thời gian chờ tệp ổn định (giây)", value=str(settings.stability_wait_seconds), width=260)
    numeric_checkbox = ft.Checkbox(label="Yêu cầu tên file PDF là số", value=settings.numeric_sequence_check)
    error_text = ft.Text("", color=ft.Colors.ERROR)

    def save_settings(_event) -> None:
        try:
            poll = max(int(poll_field.value or "300"), 30)
            stability = max(int(stability_field.value or "20"), 0)
        except ValueError:
            error_text.value = "Chu kỳ quét và thời gian chờ phải là số."
            ctx.page.update()
            return
        db.save_project_settings(ProjectSettings(ctx.project_id, poll, stability, numeric_checkbox.value))
        error_text.value = "Đã lưu cấu hình vận hành."
        error_text.color = ft.Colors.PRIMARY
        ctx.page.update()

    return _section(
        "Vận hành tự động", "Chu kỳ quét tự động và quy tắc kiểm tra tệp áp dụng riêng cho dự án.",
        ft.Column(
            spacing=10,
            controls=[
                ft.Row(controls=[poll_field, stability_field]),
                numeric_checkbox,
                error_text,
                ft.FilledButton("Lưu cấu hình vận hành", on_click=save_settings),
            ],
        ),
    )


def build(ctx) -> ft.Control:
    state = ctx.view_state.setdefault("settings", {"tab": 0})
    tab_items = [
        ("Dự án & cây thư mục", ft.Icons.ACCOUNT_TREE_OUTLINED, _build_project_section),
        ("Danh mục Excel", ft.Icons.TABLE_VIEW_OUTLINED, _build_mapfile_section),
        ("Khổ giấy", ft.Icons.DESCRIPTION_OUTLINED, _build_paper_formats_section),
        ("Máy trạm", ft.Icons.COMPUTER_OUTLINED, _build_clients_section),
        ("Nhân sự", ft.Icons.GROUP_OUTLINED, _build_personnel_section),
        ("Vận hành", ft.Icons.TUNE_OUTLINED, _build_operations_section),
    ]

    def switch_tab(index: int) -> None:
        state["tab"] = index
        ctx.refresh()

    tab_buttons: list[ft.Control] = []
    for index, (label, icon, _builder) in enumerate(tab_items):
        button_type = ft.FilledButton if index == state["tab"] else ft.OutlinedButton
        tab_buttons.append(
            button_type(
                label,
                icon=icon,
                on_click=lambda _event, selected=index: switch_tab(selected),
            )
        )

    selected_builder = tab_items[int(state["tab"])][2]
    tab_bar = ft.Container(
        padding=10,
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
        border=ft.Border.all(
            1, ft.Colors.with_opacity(0.25, ft.Colors.PRIMARY)
        ),
        content=ft.Row(spacing=8, wrap=True, controls=tab_buttons),
    )

    return ft.Column(
        expand=True,
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text(
                "Chọn từng nhóm bên dưới để cấu hình dự án.",
                size=13, color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            tab_bar,
            selected_builder(ctx),
        ],
    )
