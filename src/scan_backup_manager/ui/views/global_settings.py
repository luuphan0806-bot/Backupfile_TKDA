from __future__ import annotations

import os

import flet as ft

from .. import kit
from ..theme import TEXT_MUTED
from ...i18n import SUPPORTED_LANGUAGES


def build(shell) -> ft.Control:
    db = shell.state.db

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

    language_section = kit.section(
        "Ngôn ngữ",
        "Ngôn ngữ hiển thị của bảng điều khiển.",
        ft.Row(controls=[language_dropdown, kit.primary_button("Lưu", on_click=save_language)]),
        icon=ft.Icons.TRANSLATE,
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
    max_jobs_field = ft.TextField(
        label="Số việc tối đa/nhân sự/ngày (0 = không giới hạn)",
        value=settings.get("max_jobs_per_person_per_day", "4"), width=320,
    )
    defaults_error = ft.Text("", color=ft.Colors.ERROR)

    def save_defaults(_event) -> None:
        try:
            poll = max(int(poll_field.value or "300"), 30)
            stability = max(int(stability_field.value or "20"), 0)
            max_jobs = max(int(max_jobs_field.value or "4"), 0)
        except ValueError:
            defaults_error.value = "Chu kỳ quét, thời gian chờ và số việc/ngày phải là số."
            shell.page.update()
            return
        db.set_setting("default_poll_interval_seconds", str(poll))
        db.set_setting("default_stability_wait_seconds", str(stability))
        db.set_setting("default_numeric_sequence_check", "1" if numeric_checkbox.value else "0")
        db.set_setting("max_jobs_per_person_per_day", str(max_jobs))
        defaults_error.value = "Đã lưu."
        defaults_error.color = ft.Colors.PRIMARY
        shell.page.update()

    defaults_section = kit.section(
        "Giá trị mặc định cho dự án mới",
        "Áp dụng khi tạo dự án mới; mỗi dự án vẫn có thể chỉnh riêng sau đó trong mục Cấu hình của dự án.",
        ft.Column(
            spacing=10,
            controls=[
                ft.Row(controls=[poll_field, stability_field]),
                numeric_checkbox,
                max_jobs_field,
                defaults_error,
                kit.primary_button("Lưu giá trị mặc định", on_click=save_defaults),
            ],
        ),
        icon=ft.Icons.TUNE_OUTLINED,
    )

    backup_status = ft.Text("", color=ft.Colors.PRIMARY)

    def backup_now(_event) -> None:
        dest_dir = shell.db.db_path.parent / "manual_backups"
        path = shell.db.export_backup(dest_dir)
        backup_status.value = f"Đã sao lưu vào: {path}"
        shell.page.update()

    def open_db_folder(_event) -> None:
        os.startfile(shell.db.db_path.parent)  # noqa: S606 - desktop admin console, local folder only

    backup_section = kit.section(
        "Sao lưu / khôi phục CSDL",
        "Tạo bản sao lưu thủ công của toàn bộ cơ sở dữ liệu (tất cả dự án).",
        ft.Column(
            spacing=10,
            controls=[
                ft.Row(
                    controls=[
                        kit.primary_button("Sao lưu ngay", icon=ft.Icons.SAVE, on_click=backup_now),
                        kit.ghost_button("Mở thư mục chứa CSDL", icon=ft.Icons.FOLDER_OPEN, on_click=open_db_folder),
                    ]
                ),
                backup_status,
            ],
        ),
        icon=ft.Icons.STORAGE_OUTLINED,
    )

    account_section = kit.section(
        "Tài khoản quản trị",
        "Đổi mật khẩu đăng nhập quản trị hệ thống.",
        kit.primary_button("Đổi mật khẩu", icon=ft.Icons.KEY, on_click=lambda _e: shell.show_change_password()),
        icon=ft.Icons.SHIELD_OUTLINED,
    )

    heartbeat = db.latest_heartbeat()
    scheduler_section = kit.section(
        "Dịch vụ sao lưu tự động",
        "Dịch vụ Windows hoạt động độc lập với giao diện và xử lý các dự án theo chu kỳ riêng.",
        ft.Text(
            f"Lần kết nối gần nhất: {heartbeat['last_seen_at']}" if heartbeat
            else "Chưa nhận được tín hiệu từ dịch vụ.",
            color=ft.Colors.PRIMARY if heartbeat else ft.Colors.ERROR,
        ),
        icon=ft.Icons.CLOUD_SYNC_OUTLINED,
    )

    about_section = kit.section(
        "Thông tin ứng dụng",
        "",
        ft.Text("Scan Backup Manager · phiên bản vận hành nội bộ", size=12, color=TEXT_MUTED),
        icon=ft.Icons.INFO_OUTLINE,
    )

    return ft.Column(
        expand=True,
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            kit.page_header(
                "Cấu hình / Cài đặt",
                "Cấu hình áp dụng cho toàn hệ thống, không riêng một dự án nào.",
                eyebrow_text="Hệ thống",
            ),
            account_section,
            scheduler_section,
            language_section,
            defaults_section,
            backup_section,
            about_section,
        ],
    )
