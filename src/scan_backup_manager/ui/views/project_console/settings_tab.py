from __future__ import annotations

from pathlib import Path

import flet as ft

from ....config_excel import ConfigExcelService
from ....models import (
    Client,
    DirectoryLevel,
    JobType,
    PaperFormat,
    Personnel,
    Project,
    ProjectSettings,
)
from ... import kit
from ...theme import LEVEL_LABELS, TEXT_MUTED

LEVEL_TYPES = ["YEAR4", "ENUM", "INTEGER", "TEXT"]


def _workstation_root_name(project_code: str) -> str:
    clean = project_code.strip() or "Mã dự án"
    return clean if clean.upper().startswith("CSDL_SOHOA_") else f"CSDL_SOHOA_{clean}"


def _parse_unc_share(value: str) -> tuple[str, str]:
    clean = value.strip().replace("/", "\\")
    if not clean.startswith("\\\\"):
        return "", clean.strip("\\")
    parts = [part for part in clean.strip("\\").split("\\") if part]
    if len(parts) < 2:
        return (parts[0], "") if parts else ("", "")
    return parts[0], parts[1]


def _build_unc_share(ip_address: str, share_name: str) -> str:
    ip = ip_address.strip().strip("\\/")
    share = share_name.strip().strip("\\/")
    if not ip or not share:
        return ""
    return f"\\\\{ip}\\{share}"


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
    path_preview_text = ft.Text(
        "",
        size=13,
        color=TEXT_MUTED,
        selectable=True,
        style=ft.TextStyle(font_family="Consolas"),
    )
    path_tree = ft.Column(spacing=4)

    def project_structure_segments() -> list[str]:
        return [f"[{level.display_name}]" for level in levels] + ["Tên file pdf"]

    def build_path_text() -> str:
        root = _workstation_root_name(code_field.value or "")
        common = [root, "[Họ tên]", "[Ngày]", "[Nội dung công việc]"]
        return "/".join([*common, *project_structure_segments()])

    def refresh_path_preview() -> None:
        path_preview_text.value = build_path_text()
        tree_controls: list[ft.Control] = []
        tree_segments = [
            _workstation_root_name(code_field.value or ""),
            "[Họ tên]",
            "[Ngày]",
            "[Nội dung công việc]",
            *project_structure_segments(),
        ]
        for index, segment in enumerate(tree_segments):
            tree_controls.append(
                ft.Row(
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text("   " * index + ("└ " if index else ""), color=TEXT_MUTED),
                        ft.Icon(
                            ft.Icons.FOLDER_OUTLINED if index < len(tree_segments) - 1 else ft.Icons.PICTURE_AS_PDF_OUTLINED,
                            size=16,
                            color=ft.Colors.PRIMARY if index == 0 else TEXT_MUTED,
                        ),
                        ft.Text(segment, size=12),
                    ],
                )
            )
        path_tree.controls = tree_controls

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
        refresh_path_preview()
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

    code_field.on_change = lambda _event: (refresh_path_preview(), ctx.page.update())
    _rebuild_levels_table()

    return ft.Column(
        spacing=16,
        controls=[
            kit.section(
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
            kit.section(
                "Cấu trúc riêng từng dự án", "Phần thư mục nghiệp vụ riêng của dự án, nằm sau Họ tên / Ngày / Nội dung công việc.",
                ft.Row(
                    spacing=16,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Container(
                            expand=2,
                            content=ft.Column(
                                spacing=10,
                                controls=[
                                    ft.Row(controls=[level_name_field, level_type_dropdown, level_values_field, ft.FilledButton("Thêm tầng", on_click=add_level)], wrap=True),
                                    levels_error,
                                    kit.table_frame(levels_table),
                                    ft.FilledButton("Lưu cây thư mục", on_click=save_levels),
                                ],
                            ),
                        ),
                        ft.Container(
                            expand=1,
                            padding=12,
                            border_radius=8,
                            border=ft.Border.all(1, ft.Colors.with_opacity(0.35, ft.Colors.PRIMARY)),
                            bgcolor=ft.Colors.with_opacity(0.035, ft.Colors.PRIMARY),
                            content=ft.Column(
                                spacing=10,
                                controls=[
                                    ft.Text("Cây thư mục đầy đủ trên máy trạm", weight=ft.FontWeight.BOLD),
                                    ft.Text(
                                        "Cấu trúc chung: CSDL_SOHOA_<mã dự án>/[Họ tên]/[Ngày]/[Nội dung công việc]",
                                        size=11,
                                        color=TEXT_MUTED,
                                    ),
                                    path_preview_text,
                                    ft.Divider(height=1),
                                    path_tree,
                                ],
                            ),
                        ),
                    ],
                ),
            ),
        ],
    )


def _build_paper_formats_section(ctx) -> ft.Control:
    db = ctx.db
    formats_by_code = {item.code: item for item in db.list_paper_formats(ctx.project_id)}
    formats = [formats_by_code[code] for code in ("A4", "A3", "A0") if code in formats_by_code]
    status_text = ft.Text("", color=ft.Colors.PRIMARY)

    def save_enabled(item, value: bool) -> None:
        db.save_paper_format(
            PaperFormat(
                item.id,
                item.project_id,
                item.code,
                item.display_name,
                item.requires_separate_scan,
                item.requires_check,
                value,
                item.sort_order,
            )
        )
        status_text.value = f"Đã {'bật' if value else 'tắt'} khổ {item.code}."
        ctx.refresh()

    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Áp dụng")),
            ft.DataColumn(ft.Text("Mã")),
            ft.DataColumn(ft.Text("Tên hiển thị")),
            ft.DataColumn(ft.Text("Phần Scan")),
            ft.DataColumn(ft.Text("Phần Check")),
        ],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(
                        ft.Checkbox(
                            value=item.enabled,
                            on_change=lambda event, current=item: save_enabled(
                                current, bool(event.control.value)
                            ),
                        )
                    ),
                    ft.DataCell(ft.Text(item.code, weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(item.display_name)),
                    ft.DataCell(ft.Text("Người Scan / Ngày Scan / Số Trang")),
                    ft.DataCell(ft.Text(f"Số trang {item.code}")),
                ]
            )
            for item in formats
        ],
    )

    return kit.section(
        "Danh mục khổ giấy",
        "Cố định ba khổ giấy A4, A3, A0. Tích chọn khổ xuất hiện trong dự án; Mapfile hệ thống chỉ hiển thị các khổ đang áp dụng.",
        ft.Column(
            spacing=10,
            controls=[
                status_text,
                kit.table_frame(table),
            ],
        ),
    )


def _build_clients_section(ctx) -> ft.Control:
    db = ctx.db
    excel = ConfigExcelService(db)
    state = ctx.view_state.setdefault("settings_clients", {})
    code_field = ft.TextField(label="Mã máy trạm", width=160)
    ip_field = ft.TextField(label="IP máy trạm", width=180, hint_text="192.168.1.71")
    share_name_field = ft.TextField(label="Thư mục share", width=220, hint_text="csdl_sohoa_demo")
    share_preview = ft.Text("", color=TEXT_MUTED, selectable=True)
    notes_field = ft.TextField(label="Ghi chú", width=220)
    enabled_checkbox = ft.Checkbox(label="Kích hoạt", value=True)
    error_text = ft.Text("", color=ft.Colors.ERROR)
    template_path = state.get("template_path", "")
    picker = state.get("_picker")
    if picker is None:
        picker = ft.FilePicker()
        state["_picker"] = picker
    if picker not in ctx.page.services:
        ctx.page.services.append(picker)
    open_template_button = ft.OutlinedButton(
        "Mở file mẫu",
        icon=ft.Icons.OPEN_IN_NEW,
        visible=bool(template_path),
    )

    def open_path(path_text: str) -> None:
        try:
            path = Path(path_text)
            if not path.exists():
                raise FileNotFoundError(path)
            import os

            os.startfile(str(path))
        except OSError as exc:
            error_text.value = f"Không thể mở file: {exc}"
            error_text.color = ft.Colors.ERROR
            ctx.page.update()

    open_template_button.on_click = lambda _event: open_path(str(state.get("template_path", "")))

    def refresh_share_preview(_event=None) -> None:
        share_preview.value = _build_unc_share(ip_field.value or "", share_name_field.value or "")
        ctx.page.update()

    ip_field.on_change = refresh_share_preview
    share_name_field.on_change = refresh_share_preview

    def save_client(_event) -> None:
        code = (code_field.value or "").strip()
        ip_address = (ip_field.value or "").strip()
        share_name = (share_name_field.value or "").strip()
        share = _build_unc_share(ip_address, share_name)
        if not code or not ip_address or not share_name:
            error_text.value = "Cần nhập mã máy trạm, IP và thư mục share."
            ctx.page.update()
            return
        db.save_client(Client(None, ctx.project_id, code, "", share, enabled_checkbox.value, notes_field.value or ""))
        ctx.refresh()

    def edit_client(client: Client) -> None:
        ip_address, share_name = _parse_unc_share(client.share_path)
        code_field.value = client.client_code
        ip_field.value = ip_address
        share_name_field.value = share_name
        notes_field.value = client.notes
        enabled_checkbox.value = client.enabled
        refresh_share_preview()
        error_text.value = f"Đang sửa máy trạm {client.client_code}."
        error_text.color = ft.Colors.PRIMARY
        ctx.page.update()

    def delete_client(code: str) -> None:
        db.delete_client(ctx.project_id, code)
        ctx.refresh()

    def test_client_connection(client: Client) -> None:
        share_path = Path(client.share_path)
        if not share_path.exists():
            error_text.value = f"Không truy cập được: {client.share_path}"
            error_text.color = ft.Colors.ERROR
            ctx.page.update()
            return
        try:
            import uuid

            test_dir = share_path / f".scan_backup_write_test_{uuid.uuid4().hex[:8]}"
            test_dir.mkdir()
            test_dir.rmdir()
        except PermissionError:
            error_text.value = f"Kết nối được nhưng không có quyền ghi: {client.share_path}"
            error_text.color = ft.Colors.ERROR
        except OSError as exc:
            error_text.value = f"Kết nối được nhưng kiểm tra quyền ghi thất bại: {exc}"
            error_text.color = ft.Colors.ERROR
        else:
            error_text.value = f"Kết nối và quyền ghi OK: {client.share_path}"
            error_text.color = ft.Colors.PRIMARY
        ctx.page.update()

    async def import_excel(_event) -> None:
        result = await picker.pick_files(
            dialog_title="Chọn file Excel máy trạm",
            allowed_extensions=["xlsx", "xlsm"],
        )
        if not result:
            return
        try:
            count = excel.import_clients(ctx.project_id, Path(result[0].path))
        except Exception as exc:  # noqa: BLE001 - show import errors in UI
            error_text.value = f"Nhập Excel thất bại: {exc}"
            error_text.color = ft.Colors.ERROR
            ctx.page.update()
            return
        error_text.value = f"Đã nhập {count} máy trạm từ Excel."
        error_text.color = ft.Colors.PRIMARY
        ctx.refresh()

    def export_excel(_event) -> None:
        project = db.get_project(ctx.project_id)
        output_dir = Path(project.reports_dir if project else "data/reports")
        path = excel.export_clients(ctx.project_id, output_dir)
        error_text.value = f"Đã xuất Excel: {path}"
        error_text.color = ft.Colors.PRIMARY
        ctx.page.update()

    def export_template(_event) -> None:
        project = db.get_project(ctx.project_id)
        output_dir = Path(project.reports_dir if project else "data/reports")
        path = excel.export_client_template(output_dir)
        state["template_path"] = str(path)
        error_text.value = f"Đã tạo file mẫu: {path}"
        error_text.color = ft.Colors.PRIMARY
        open_template_button.visible = True
        ctx.page.update()

    clients = db.list_clients(ctx.project_id)
    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Mã")),
            ft.DataColumn(ft.Text("IP")),
            ft.DataColumn(ft.Text("Thư mục share")),
            ft.DataColumn(ft.Text("Đường dẫn UNC")),
            ft.DataColumn(ft.Text("Ghi chú")),
            ft.DataColumn(ft.Text("Kích hoạt")),
            ft.DataColumn(ft.Text("Kiểm tra")),
            ft.DataColumn(ft.Text("Sửa")),
            ft.DataColumn(ft.Text("")),
        ],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(c.client_code)),
                    ft.DataCell(ft.Text(_parse_unc_share(c.share_path)[0] or "—")),
                    ft.DataCell(ft.Text(_parse_unc_share(c.share_path)[1] or "—")),
                    ft.DataCell(ft.Text(c.share_path)),
                    ft.DataCell(ft.Text(c.notes)),
                    ft.DataCell(ft.Text("Có" if c.enabled else "Không")),
                    ft.DataCell(
                        ft.IconButton(
                            icon=ft.Icons.LAN_OUTLINED,
                            tooltip="Kiểm tra kết nối share",
                            on_click=lambda _e, current=c: test_client_connection(current),
                        )
                    ),
                    ft.DataCell(
                        ft.IconButton(
                            icon=ft.Icons.EDIT_OUTLINED,
                            tooltip="Sửa máy trạm",
                            on_click=lambda _e, current=c: edit_client(current),
                        )
                    ),
                    ft.DataCell(ft.IconButton(icon=ft.Icons.DELETE, on_click=lambda _e, code=c.client_code: delete_client(code))),
                ]
            )
            for c in clients
        ],
    )

    return kit.section(
        "Máy trạm", "Khai báo các thư mục chia sẻ trên máy trạm cần quét tệp.",
        ft.Column(
            spacing=10,
            controls=[
                ft.Row(controls=[code_field, ip_field, share_name_field, notes_field, enabled_checkbox], wrap=True),
                ft.Row(
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.LAN_OUTLINED, size=16, color=TEXT_MUTED),
                        ft.Text("Đường dẫn share:", color=TEXT_MUTED),
                        share_preview,
                    ],
                ),
                error_text,
                ft.Row(
                    wrap=True,
                    controls=[
                        ft.FilledButton("Thêm / cập nhật máy trạm", on_click=save_client),
                        ft.OutlinedButton("Tải file mẫu", icon=ft.Icons.DESCRIPTION_OUTLINED, on_click=export_template),
                        open_template_button,
                        ft.OutlinedButton("Nhập Excel", icon=ft.Icons.UPLOAD_FILE, on_click=import_excel),
                        ft.OutlinedButton("Xuất Excel", icon=ft.Icons.DOWNLOAD, on_click=export_excel),
                    ],
                ),
                kit.table_frame(table),
            ],
        ),
    )


def _build_personnel_section(ctx) -> ft.Control:
    db = ctx.db
    excel = ConfigExcelService(db)
    state = ctx.view_state.setdefault("settings_personnel", {})
    code_field = ft.TextField(label="Mã nhân viên", width=160)
    name_field = ft.TextField(label="Họ và tên", width=260)
    enabled_checkbox = ft.Checkbox(label="Kích hoạt", value=True)
    error_text = ft.Text("", color=ft.Colors.ERROR)
    template_path = state.get("template_path", "")
    picker = state.get("_picker")
    if picker is None:
        picker = ft.FilePicker()
        state["_picker"] = picker
    if picker not in ctx.page.services:
        ctx.page.services.append(picker)
    open_template_button = ft.OutlinedButton(
        "Mở file mẫu",
        icon=ft.Icons.OPEN_IN_NEW,
        visible=bool(template_path),
    )

    def open_path(path_text: str) -> None:
        try:
            path = Path(path_text)
            if not path.exists():
                raise FileNotFoundError(path)
            import os

            os.startfile(str(path))
        except OSError as exc:
            error_text.value = f"Không thể mở file: {exc}"
            error_text.color = ft.Colors.ERROR
            ctx.page.update()

    open_template_button.on_click = lambda _event: open_path(str(state.get("template_path", "")))

    def save_personnel(_event) -> None:
        code = (code_field.value or "").strip()
        name = (name_field.value or "").strip()
        if not code or not name:
            error_text.value = "Cần nhập mã nhân viên và họ tên."
            ctx.page.update()
            return
        db.save_personnel(Personnel(None, ctx.project_id, code, name, "", enabled_checkbox.value))
        ctx.refresh()

    def delete_personnel(personnel_id: int) -> None:
        db.delete_personnel(personnel_id)
        ctx.refresh()

    async def import_excel(_event) -> None:
        result = await picker.pick_files(
            dialog_title="Chọn file Excel nhân sự",
            allowed_extensions=["xlsx", "xlsm"],
        )
        if not result:
            return
        try:
            count = excel.import_personnel(ctx.project_id, Path(result[0].path))
        except Exception as exc:  # noqa: BLE001 - show import errors in UI
            error_text.value = f"Nhập Excel thất bại: {exc}"
            error_text.color = ft.Colors.ERROR
            ctx.page.update()
            return
        error_text.value = f"Đã nhập {count} nhân sự từ Excel."
        error_text.color = ft.Colors.PRIMARY
        ctx.refresh()

    def export_excel(_event) -> None:
        project = db.get_project(ctx.project_id)
        output_dir = Path(project.reports_dir if project else "data/reports")
        path = excel.export_personnel(ctx.project_id, output_dir)
        error_text.value = f"Đã xuất Excel: {path}"
        error_text.color = ft.Colors.PRIMARY
        ctx.page.update()

    def export_template(_event) -> None:
        project = db.get_project(ctx.project_id)
        output_dir = Path(project.reports_dir if project else "data/reports")
        path = excel.export_personnel_template(output_dir)
        state["template_path"] = str(path)
        error_text.value = f"Đã tạo file mẫu: {path}"
        error_text.color = ft.Colors.PRIMARY
        open_template_button.visible = True
        ctx.page.update()

    personnel = db.list_personnel(ctx.project_id)
    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Mã nhân viên")),
            ft.DataColumn(ft.Text("Họ và tên")),
            ft.DataColumn(ft.Text("Kích hoạt")),
            ft.DataColumn(ft.Text("")),
        ],
        rows=[
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(p.personnel_code)),
                    ft.DataCell(ft.Text(p.full_name)),
                    ft.DataCell(ft.Text("Có" if p.enabled else "Không")),
                    ft.DataCell(ft.IconButton(icon=ft.Icons.DELETE, on_click=lambda _e, pid=p.id: delete_personnel(pid))),
                ]
            )
            for p in personnel
        ],
    )

    return kit.section(
        "Nhân sự", "Quản lý danh sách nhân sự có thể được giao công việc dự án.",
        ft.Column(
            spacing=10,
            controls=[
                ft.Row(controls=[code_field, name_field, enabled_checkbox], wrap=True),
                error_text,
                ft.Row(
                    wrap=True,
                    controls=[
                        ft.FilledButton("Thêm / cập nhật nhân sự", on_click=save_personnel),
                        ft.OutlinedButton("Tải file mẫu", icon=ft.Icons.DESCRIPTION_OUTLINED, on_click=export_template),
                        open_template_button,
                        ft.OutlinedButton("Nhập Excel", icon=ft.Icons.UPLOAD_FILE, on_click=import_excel),
                        ft.OutlinedButton("Xuất Excel", icon=ft.Icons.DOWNLOAD, on_click=export_excel),
                    ],
                ),
                kit.table_frame(table),
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

    return kit.section(
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


def _build_job_types_section(ctx) -> ft.Control:
    db = ctx.db
    job_types = db.list_job_types(ctx.project_id)
    status_text = ft.Text("", color=ft.Colors.PRIMARY)
    rows: list[ft.DataRow] = []

    def save_job(
        item: JobType,
        name_field: ft.TextField,
        enabled_field: ft.Checkbox,
        kind_field: ft.Dropdown,
        off_app_field: ft.Checkbox,
    ) -> None:
        try:
            db.save_job_type(
                JobType(
                    item.id,
                    item.project_id,
                    item.job_code,
                    name_field.value or "",
                    bool(enabled_field.value),
                    item.sort_order,
                    kind_field.value or "SCAN",
                    bool(off_app_field.value),
                )
            )
        except ValueError as exc:
            status_text.value = str(exc)
            status_text.color = ft.Colors.ERROR
            ctx.page.update()
            return
        status_text.value = "Đã lưu cấu hình công việc."
        status_text.color = ft.Colors.PRIMARY
        ctx.refresh()

    for item in job_types:
        name_field = ft.TextField(value=item.display_name, dense=True, width=260)
        enabled_field = ft.Checkbox(value=item.enabled)
        kind_field = ft.Dropdown(
            value=item.job_kind or "SCAN",
            dense=True,
            width=150,
            options=[
                ft.dropdown.Option(key="SCAN", text="Giao scan"),
                ft.dropdown.Option(key="CHECK", text="Giao check"),
            ],
        )
        off_app_field = ft.Checkbox(
            value=item.off_app,
            tooltip="Việc không thực hiện qua app: không đo năng suất, sản lượng nhập tay",
        )
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(item.job_code, weight=ft.FontWeight.BOLD)),
                    ft.DataCell(name_field),
                    ft.DataCell(kind_field),
                    ft.DataCell(enabled_field),
                    ft.DataCell(off_app_field),
                    ft.DataCell(
                        ft.IconButton(
                            icon=ft.Icons.SAVE_OUTLINED,
                            tooltip="Lưu công việc",
                            on_click=lambda _e, current=item, field=name_field, enabled=enabled_field, kind=kind_field, off_app=off_app_field: save_job(
                                current, field, enabled, kind, off_app
                            ),
                        )
                    ),
                ]
            )
        )

    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Mã công việc")),
            ft.DataColumn(ft.Text("Tên hiển thị")),
            ft.DataColumn(ft.Text("Phân loại")),
            ft.DataColumn(ft.Text("Áp dụng")),
            ft.DataColumn(ft.Text("Ngoài app")),
            ft.DataColumn(ft.Text("")),
        ],
        rows=rows,
    )

    return kit.section(
        "Cấu hình công việc",
        "Admin đặt tên, phân loại (scan/check) và đánh dấu việc ngoài app (không năng suất) dùng khi giao việc.",
        ft.Column(
            spacing=10,
            controls=[
                status_text,
                kit.table_frame(table),
            ],
        ),
    )


def build(ctx) -> ft.Control:
    state = ctx.view_state.setdefault("settings", {"tab": 0})
    tab_items = [
        ("Dự án & cây thư mục", ft.Icons.ACCOUNT_TREE_OUTLINED, _build_project_section),
        ("Khổ giấy", ft.Icons.DESCRIPTION_OUTLINED, _build_paper_formats_section),
        ("Máy trạm", ft.Icons.COMPUTER_OUTLINED, _build_clients_section),
        ("Nhân sự", ft.Icons.GROUP_OUTLINED, _build_personnel_section),
        ("Công việc", ft.Icons.ASSIGNMENT_OUTLINED, _build_job_types_section),
        ("Vận hành", ft.Icons.TUNE_OUTLINED, _build_operations_section),
    ]

    def switch_tab(index: int) -> None:
        state["tab"] = index
        ctx.refresh()

    selected_index = min(int(state["tab"]), len(tab_items) - 1)
    state["tab"] = selected_index
    selected_builder = tab_items[selected_index][2]
    tab_bar = kit.tab_bar(
        [(label, icon) for label, icon, _b in tab_items],
        selected_index,
        switch_tab,
    )

    return ft.Column(
        expand=True,
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text(
                "Chọn từng nhóm bên dưới để cấu hình dự án.",
                size=13, color=TEXT_MUTED,
            ),
            tab_bar,
            selected_builder(ctx),
        ],
    )
