# Scan Backup Manager

Ứng dụng desktop Windows để quản lý dự án số hóa, sao lưu file PDF scan từ các máy trạm/SMB share về kho tập trung, theo dõi công việc Scan/Check và xuất báo cáo Excel.

Ứng dụng dùng Flet cho giao diện, SQLite cho dữ liệu, openpyxl cho import/export Excel và có Windows Service để chạy pipeline backup độc lập với UI.

## Tính năng chính

- Quản lý nhiều dự án trong cùng một ứng dụng.
- Tạo CSDL phụ theo từng dự án tại `project_databases/<MA_DU_AN>.sqlite3`.
- Xóa dự án có xác nhận mật khẩu admin; dữ liệu quản lý và SQLite phụ bị xóa, thư mục backup vật lý được giữ nguyên.
- Cấu hình cây thư mục hồ sơ theo từng cấp: năm, loại hồ sơ, mã hồ sơ hoặc cấu trúc tùy chọn.
- Khai báo máy trạm/share SMB nguồn, nhân sự, loại công việc Scan/Check và khổ giấy.
- Tạo công việc Scan nhiều dòng hồ sơ trong một lần giao.
- Tạo công việc Check chỉ từ danh sách hồ sơ đã scan xong, đã backup và đang chờ check.
- Sao lưu file scan, kiểm tra ổn định file, đối chiếu cấu trúc, phát hiện trùng/xung đột.
- Kiểm tra hash backup hằng ngày qua job `VERIFY_INTEGRITY`.
- Import mapfile Excel và đối chiếu danh mục hồ sơ với dữ liệu backup thực tế.
- Chấm công có bước Leader duyệt (Leader Workbench): thống kê/báo cáo chỉ tính công đã APPROVED.
- Thống kê theo ngày, công việc, nhân sự, sản lượng, thời gian bắt đầu.
- Xuất báo cáo Excel hằng ngày, thống kê và dữ liệu chấm công.

## Luồng tổng quan

```mermaid
flowchart LR
    A[Máy trạm / SMB share] --> B[Windows Service]
    B --> C[Quét file PDF]
    C --> D[Kiểm tra cấu trúc thư mục]
    D --> E[Sao lưu vào backup root]
    E --> F[Kiểm tra size/hash]
    F --> G[Mapfile hệ thống]
    G --> H[Tạo việc Check]
    H --> I[Thống kê và báo cáo Excel]
```

## Cấu trúc thư mục

```text
Backupfile_TKDA/
├─ README.md
├─ HUONG_DAN_BAT_DAU_DU_AN_MOI.md
├─ pyproject.toml
├─ main.py
├─ service_main.py
├─ packaging/
│  ├─ build.ps1
│  └─ installer.iss
├─ scripts/
│  └─ seed_mock_data.py
├─ src/
│  └─ scan_backup_manager/
│     ├─ backup.py
│     ├─ config_excel.py
│     ├─ db.py
│     ├─ mapfile.py
│     ├─ reports.py
│     ├─ service_core.py
│     ├─ statistics.py
│     ├─ windows_service.py
│     └─ ui/
├─ tests/
├─ data/
└─ dist/
```

`data/`, `dist/`, `build/`, `.venv/`, log runtime và file CSDL local thường không nên commit trừ khi cần phát hành mẫu/test.

## Yêu cầu môi trường

- Windows 10/11.
- Python 3.11 trở lên, khuyến nghị Python 3.12.
- Git.
- Quyền truy cập các SMB share/máy trạm scan.
- Nếu build EXE: cài dependency build trong `pyproject.toml`; Inno Setup là tùy chọn nếu muốn tạo installer.

## Cài đặt để chạy từ source

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,build]"
```

Chạy giao diện:

```powershell
python -m scan_backup_manager
```

Hoặc:

```powershell
python main.py
```

Tài khoản quản trị mặc định khi tạo DB mới:

```text
Admin@123
```

Nên đổi mật khẩu ngay sau khi đăng nhập lần đầu.

## Chạy dữ liệu demo

Tạo bộ dữ liệu mock:

```powershell
python scripts\seed_mock_data.py
```

Script tạo môi trường demo trong `data/mock_env`, gồm CSDL mẫu, mapfile Excel, nhân sự, máy trạm, hồ sơ và báo cáo mẫu.

## Build EXE

Cài dependency build trước:

```powershell
python -m pip install -e ".[dev,build]"
```

Build:

```powershell
.\packaging\build.ps1
```

Kết quả chính:

```text
dist/ScanBackupManager.exe
dist/ScanBackupService.exe
```

Nếu máy có Inno Setup, script sẽ tạo thêm installer theo `packaging/installer.iss`.

## Windows Service

Ứng dụng có service để tự quét backup ngay cả khi UI không mở.

Chạy console để kiểm thử:

```powershell
scan-backup-service-console
```

Hoặc chạy trực tiếp:

```powershell
python service_main.py console
```

Service định kỳ:

- enqueue `SCAN_PROJECT` theo khoảng quét của dự án.
- enqueue `VERIFY_INTEGRITY` mỗi ngày cho dự án đang bật.
- xử lý xung đột và ghi audit/log.

## CSDL và dữ liệu runtime

DB trung tâm mặc định nằm trong thư mục runtime data:

```text
%PROGRAMDATA%\ScanBackupManager\scan_backup_manager.sqlite3
```

Nếu không có `PROGRAMDATA`, app dùng `data/`.

Mỗi dự án khi tạo sẽ có SQLite phụ:

```text
project_databases/<MA_DU_AN>.sqlite3
```

SQLite phụ hiện lưu metadata dự án để phục vụ tách dữ liệu/đồng bộ về sau; dữ liệu vận hành chính vẫn nằm trong DB trung tâm.

## Báo cáo Excel

Ứng dụng xuất các nhóm file:

- `scan_backup_report_YYYYMMDD_HHMMSS.xlsx`: báo cáo backup hằng ngày.
- `statistics_report_<date_from>_<date_to>_YYYYMMDD_HHMMSS.xlsx`: báo cáo thống kê.
- `attendance_report_<date_from>_<date_to>_YYYYMMDD_HHMMSS.xlsx`: dữ liệu chấm công.
- `MauChamCong_<date_from>_<date_to>_YYYYMMDD_HHMMSS.xlsx`: bảng công theo đúng mẫu MauChamCong (1 sheet/ngày, khối 4 dòng/nhân sự). Cần nhập Loại chấm công + giờ công qua nút "Chi tiết chấm công" trong Leader Workbench trước khi xuất.
- `mau_nhap_may_tram.xlsx`, `mau_nhap_nhan_su.xlsx`: mẫu import cấu hình.

File chấm công có 5 sheet:

- `Cham cong`: chi tiết công đã duyệt theo ngày, nhân sự, thứ tự công việc, loại công việc, sản lượng, giờ bắt đầu.
- `Tong hop`: tổng hợp theo ngày và nhân sự.
- `San luong tho`: toàn bộ dòng công (mọi trạng thái) để đối chiếu.
- `Ngoai le`: dòng cần chú ý (chưa duyệt, override, SCAN thiếu backup, CHECK chưa xong).
- `Audit chinh sua`: nhật ký duyệt/loại/xuất báo cáo trong kỳ.

> **Quan trọng:** từ schema DB v7, Thống kê và báo cáo chấm công **chỉ tính các dòng công đã được Leader duyệt (APPROVED)** trong tab Leader Workbench. Sau khi nâng cấp, báo cáo sẽ trống cho tới khi Leader duyệt — đây không phải mất dữ liệu. Xem chi tiết trong [HUONG_DAN_CHAM_CONG_LEADER.md](HUONG_DAN_CHAM_CONG_LEADER.md).

## Kiểm thử

Chạy toàn bộ test:

```powershell
python -m pytest -q
```

Chạy nhóm test quan trọng:

```powershell
python -m pytest tests\test_project_management.py tests\test_service_core.py tests\test_statistics.py tests\test_system_mapfile.py tests\test_backup.py tests\test_product_pipeline.py -q
```

Chạy smoke gate trước khi bàn giao release:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\write_release_manifest.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\release_smoke.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\product_readiness_audit.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\make_release_bundle.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_release_bundle.ps1 -BundlePath dist\release\ScanBackupManager-release-YYYYMMDD-HHMMSS.zip
```

Smoke gate này kiểm tra health/recovery, UI composition first-run và toàn bộ 6 tab project console, action snapshot trong Settings/recovery, app/service source, app/service EXE, installer artifact, manifest SHA256 và một pipeline local tạo PDF thật rồi xác nhận hồ sơ đủ điều kiện Check. Kết quả được lưu tại `dist\release-smoke-report.json`. Manifest ghi thêm version, commit Git, trạng thái worktree và metadata Windows của từng artifact để truy ngược bản build. Readiness audit gom các bằng chứng này vào `dist\product-readiness-report.json`.
Lệnh bundle tạo ZIP bàn giao trong `dist\release\` kèm manifest SHA256 của chính file ZIP và các script hardening/release cần để audit lại. Lệnh verify mở ZIP trong thư mục tạm, kiểm đủ file bắt buộc, kiểm `release-smoke-report.json`, `release-manifest.json`, size và SHA256 của từng artifact trước khi bàn giao. `release-manifest.json` cũng ghi trạng thái Authenticode của EXE/installer để audit chữ ký số.
Với rollout rộng cho người dùng cuối, bật gate chữ ký số sau khi ký EXE/installer:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sign_release_artifacts.ps1 -CertificateThumbprint "THUMBPRINT_CHUNG_THU_SO"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\write_release_manifest.ps1 -RequireSigned
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\product_readiness_audit.ps1 -RequireSigned -RequireAdminService
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_release_bundle.ps1 -BundlePath dist\release\ScanBackupManager-release-YYYYMMDD-HHMMSS.zip -RequireSigned
```

Nếu dùng file PFX thay vì certificate đã cài trong store:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sign_release_artifacts.ps1 -PfxPath C:\path\codesign.pfx
```
Trên máy triển khai, mở PowerShell bằng quyền Administrator và thêm `-IncludeAdminService` để kiểm tra install/start/stop/remove Windows Service thật:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\release_smoke.ps1 -IncludeAdminService
```

Nhánh admin-service sẽ cài service tạm với `SCAN_BACKUP_DATA_DIR` riêng, start service qua Windows Service Control Manager, kiểm service tạo DB/log thật, rồi stop/remove service nếu không yêu cầu giữ lại.

## Hardening và recovery

Chạy health check trên data dir sạch trước khi bàn giao:

```powershell
$env:SCAN_BACKUP_DATA_DIR="$PWD\data\release-smoke"
python scripts\product_hardening_check.py health
```

Tạo snapshot DB nhất quán bằng SQLite backup API:

```powershell
python scripts\product_hardening_check.py snapshot --label before-release
```

Restore snapshot khi cần rollback:

```powershell
python scripts\product_hardening_check.py restore "duong_dan_snapshot.sqlite3"
```

Xem checklist release, smoke app/service/EXE và quy tắc go/no-go trong [VAN_HANH_PRODUCT.md](VAN_HANH_PRODUCT.md).
Trong UI, vào `Cấu hình / Cài đặt` -> `Sao lưu / khôi phục CSDL` để xem runtime data dir, DB, log, tạo snapshot và restore snapshot có xác thực mật khẩu admin.

## Ghi chú vận hành

- Không xóa thư mục backup vật lý khi xóa dự án trong UI; cần dọn file thật thì thực hiện thủ công ngoài app.
- Với công việc Check, danh sách chọn chỉ lấy hồ sơ đã hoàn thành scan/backup và chưa check.
- Nên để mỗi dự án có `backup_root`, `staging_dir`, `conflict_archive_dir`, `reports_dir` riêng.
- Với SMB share, tài khoản Windows chạy service phải có quyền đọc nguồn và ghi backup.
- Luôn kiểm tra báo cáo/audit sau khi thay đổi cấu hình cây thư mục hoặc máy trạm.

## Hướng dẫn chi tiết

Xem file [HUONG_DAN_BAT_DAU_DU_AN_MOI.md](HUONG_DAN_BAT_DAU_DU_AN_MOI.md) để setup một dự án mới từ đầu đến bước xuất công ngày.
