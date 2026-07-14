from __future__ import annotations

import os
from pathlib import Path

import flet as ft

from ... import __version__
from .. import kit
from ..theme import TEXT_MUTED
from ...i18n import SUPPORTED_LANGUAGES
from ...maintenance import create_database_snapshot, restore_database_snapshot


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

    backup_status = ft.Text("", color=ft.Colors.PRIMARY, selectable=True)
    restore_password_field = ft.TextField(
        label="Mật khẩu admin để restore",
        password=True,
        can_reveal_password=True,
        width=300,
    )
    snapshot_button = kit.primary_button("Sao lưu ngay", icon=ft.Icons.SAVE)
    restore_button = kit.ghost_button("Chọn file restore", icon=ft.Icons.RESTORE)
    db_path_text = ft.Text(str(shell.db.db_path), size=12, color=TEXT_MUTED, selectable=True)
    data_dir_text = ft.Text(str(shell.db.db_path.parent), size=12, color=TEXT_MUTED, selectable=True)
    log_path_text = ft.Text(
        str(shell.db.db_path.parent / "logs" / "app.log"),
        size=12,
        color=TEXT_MUTED,
        selectable=True,
    )

    def open_db_folder(_event) -> None:
        os.startfile(shell.db.db_path.parent)  # noqa: S606 - desktop admin console, local folder only

    def create_snapshot_now(_event) -> None:
        snapshot_button.disabled = True
        backup_status.color = ft.Colors.PRIMARY
        backup_status.value = "Đang tạo snapshot DB..."
        shell.page.update()
        try:
            path = create_database_snapshot(
                shell.db.db_path,
                backup_dir=shell.db.db_path.parent / "db_backups",
                label="ui",
            )
            shell.db.record_audit("DB_SNAPSHOT_CREATED", str(path))
            backup_status.value = f"Đã tạo snapshot: {path}"
        except Exception as exc:  # noqa: BLE001 - surface actionable UI error
            backup_status.color = ft.Colors.ERROR
            backup_status.value = f"Không thể tạo snapshot DB: {exc}"
        finally:
            snapshot_button.disabled = False
            shell.page.update()

    def open_backup_folder(_event) -> None:
        folder = shell.db.db_path.parent / "db_backups"
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)  # noqa: S606 - desktop admin console, local folder only

    def restore_from_file(path: Path) -> None:
        if not shell.db.verify_admin_password(restore_password_field.value or ""):
            backup_status.color = ft.Colors.ERROR
            backup_status.value = "Mật khẩu admin không đúng; không restore DB."
            shell.page.update()
            return
        restore_button.disabled = True
        backup_status.color = ft.Colors.PRIMARY
        backup_status.value = "Đang restore DB snapshot..."
        shell.page.update()
        try:
            pre_restore = restore_database_snapshot(
                path,
                shell.db.db_path,
                backup_dir=shell.db.db_path.parent / "db_backups",
            )
            shell.db.record_audit(
                "DB_SNAPSHOT_RESTORED",
                f"restored={path}; pre_restore={pre_restore or ''}",
            )
            backup_status.value = (
                "Đã restore DB. Đang xuất để đăng nhập lại với dữ liệu mới. "
                f"Pre-restore snapshot: {pre_restore}"
            )
            restore_password_field.value = ""
            shell.show_role_selection()
        except Exception as exc:  # noqa: BLE001 - surface actionable UI error
            backup_status.color = ft.Colors.ERROR
            backup_status.value = f"Không thể restore DB: {exc}"
        finally:
            restore_button.disabled = False
            shell.page.update()

    restore_picker = getattr(shell, "_db_restore_picker", None)
    if restore_picker is None:
        restore_picker = ft.FilePicker()
        shell._db_restore_picker = restore_picker
    if restore_picker not in shell.page.services:
        shell.page.services.append(restore_picker)

    async def browse_restore(_event=None) -> None:
        result = await restore_picker.pick_files(
            dialog_title="Chọn file CSDL để restore",
            allow_multiple=False,
            allowed_extensions=["sqlite3", "db"],
        )
        if result:
            restore_from_file(Path(result[0].path))

    snapshot_button.on_click = create_snapshot_now
    restore_button.on_click = browse_restore

    backup_section = kit.section(
        "Sao lưu / khôi phục CSDL",
        "Tạo bản sao lưu thủ công của toàn bộ cơ sở dữ liệu (tất cả dự án).",
        ft.Column(
            spacing=10,
            controls=[
                ft.Column(
                    spacing=4,
                    controls=[
                        ft.Text("Runtime data dir", size=11, color=TEXT_MUTED),
                        data_dir_text,
                        ft.Text("Central DB", size=11, color=TEXT_MUTED),
                        db_path_text,
                        ft.Text("Log file", size=11, color=TEXT_MUTED),
                        log_path_text,
                    ],
                ),
                ft.Row(
                    controls=[
                        snapshot_button,
                        kit.ghost_button("Mở thư mục chứa CSDL", icon=ft.Icons.FOLDER_OPEN, on_click=open_db_folder),
                    ]
                ),
                ft.Row(
                    wrap=True,
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        kit.ghost_button("Mở thư mục snapshot", icon=ft.Icons.FOLDER_COPY, on_click=open_backup_folder),
                        restore_password_field,
                        restore_button,
                    ],
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
        ft.Text(f"Scan Backup Manager · phiên bản {__version__}", size=12, color=TEXT_MUTED),
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
