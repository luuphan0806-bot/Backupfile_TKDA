from __future__ import annotations

import os

import flet as ft

from ...i18n import SUPPORTED_LANGUAGES


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
                            width=4,
                            height=38 if subtitle else 24,
                            border_radius=4,
                            bgcolor=ft.Colors.PRIMARY,
                        ),
                        ft.Column(
                            spacing=2,
                            controls=[
                                ft.Text(title, size=16, weight=ft.FontWeight.BOLD),
                                ft.Text(
                                    subtitle,
                                    size=12,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                    visible=bool(subtitle),
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


def build(shell) -> ft.Control:
    db = shell.state.db

    theme_section = _section(
        "Giao diện",
        "Chuyển đổi giao diện sáng/tối cho toàn bộ ứng dụng.",
        ft.FilledButton(
            "Đổi sang giao diện " + ("sáng" if shell.state.theme_mode == "dark" else "tối"),
            icon=ft.Icons.DARK_MODE if shell.state.theme_mode == "light" else ft.Icons.LIGHT_MODE,
            on_click=lambda _e: (shell.toggle_theme(), shell.refresh_content()),
        ),
    )

    language_dropdown = ft.Dropdown(
        label="Ngôn ngữ",
        width=260,
        value=shell.state.language,
        options=[ft.dropdown.Option(key=code, text=name) for code, name in SUPPORTED_LANGUAGES.items()],
    )

    def save_language(_event) -> None:
        code = language_dropdown.value or shell.state.language
        shell.state.language = code
        db.set_setting("language", code)
        shell.page.update()

    language_section = _section(
        "Ngôn ngữ",
        "Ngôn ngữ hiển thị của bảng điều khiển.",
        ft.Row(controls=[language_dropdown, ft.FilledButton("Lưu", on_click=save_language)]),
    )

    settings = db.list_settings()
    poll_field = ft.TextField(
        label="Chu kỳ quét mặc định (giây)", value=settings.get("default_poll_interval_seconds", "300"), width=280,
    )
    stability_field = ft.TextField(
        label="Thời gian chờ file ổn định mặc định (giây)",
        value=settings.get("default_stability_wait_seconds", "20"), width=280,
    )
    numeric_checkbox = ft.Checkbox(
        label="Mặc định yêu cầu tên file PDF là số",
        value=settings.get("default_numeric_sequence_check", "0") == "1",
    )
    defaults_error = ft.Text("", color=ft.Colors.ERROR)

    def save_defaults(_event) -> None:
        try:
            poll = max(int(poll_field.value or "300"), 30)
            stability = max(int(stability_field.value or "20"), 0)
        except ValueError:
            defaults_error.value = "Chu kỳ quét và thời gian chờ phải là số."
            shell.page.update()
            return
        db.set_setting("default_poll_interval_seconds", str(poll))
        db.set_setting("default_stability_wait_seconds", str(stability))
        db.set_setting("default_numeric_sequence_check", "1" if numeric_checkbox.value else "0")
        defaults_error.value = "Đã lưu."
        defaults_error.color = ft.Colors.PRIMARY
        shell.page.update()

    defaults_section = _section(
        "Giá trị mặc định cho dự án mới",
        "Áp dụng khi tạo dự án mới; mỗi dự án vẫn có thể chỉnh riêng sau đó trong mục Cấu hình của dự án.",
        ft.Column(
            spacing=10,
            controls=[
                ft.Row(controls=[poll_field, stability_field]),
                numeric_checkbox,
                defaults_error,
                ft.FilledButton("Lưu giá trị mặc định", on_click=save_defaults),
            ],
        ),
    )

    backup_status = ft.Text("", color=ft.Colors.PRIMARY)

    def backup_now(_event) -> None:
        dest_dir = shell.db.db_path.parent / "manual_backups"
        path = shell.db.export_backup(dest_dir)
        backup_status.value = f"Đã sao lưu vào: {path}"
        shell.page.update()

    def open_db_folder(_event) -> None:
        os.startfile(shell.db.db_path.parent)  # noqa: S606 - desktop admin console, local folder only

    backup_section = _section(
        "Sao lưu / khôi phục CSDL",
        "Tạo bản sao lưu thủ công của toàn bộ cơ sở dữ liệu (tất cả dự án).",
        ft.Column(
            spacing=10,
            controls=[
                ft.Row(
                    controls=[
                        ft.FilledButton("Sao lưu ngay", icon=ft.Icons.SAVE, on_click=backup_now),
                        ft.OutlinedButton("Mở thư mục chứa CSDL", icon=ft.Icons.FOLDER_OPEN, on_click=open_db_folder),
                    ]
                ),
                backup_status,
            ],
        ),
    )

    account_section = _section(
        "Tài khoản quản trị",
        "Đổi mật khẩu đăng nhập quản trị hệ thống.",
        ft.FilledButton("Đổi mật khẩu", on_click=lambda _e: shell.show_change_password()),
    )

    heartbeat = db.latest_heartbeat()
    scheduler_section = _section(
        "Dịch vụ sao lưu tự động",
        "Dịch vụ Windows hoạt động độc lập với giao diện và xử lý các dự án theo chu kỳ riêng.",
        ft.Text(
            f"Lần kết nối gần nhất: {heartbeat['last_seen_at']}" if heartbeat
            else "Chưa nhận được tín hiệu từ dịch vụ.",
            color=ft.Colors.PRIMARY if heartbeat else ft.Colors.ERROR,
        ),
    )

    about_section = _section(
        "Thông tin ứng dụng",
        "",
        ft.Text("Scan Backup Manager - phiên bản vận hành nội bộ", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
    )

    return ft.Column(
        expand=True,
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text("Cấu hình / Cài đặt", size=22, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Cấu hình áp dụng cho toàn hệ thống, không riêng một dự án nào.",
                size=13, color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            account_section,
            scheduler_section,
            theme_section,
            language_section,
            defaults_section,
            backup_section,
            about_section,
        ],
    )
