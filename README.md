# Scan Backup Manager

Ứng dụng desktop chạy trên Windows để quản lý và sao lưu file PDF scan từ các
máy trạm hoặc thư mục chia sẻ SMB về kho lưu trữ tập trung trên máy chủ. Mỗi dự
án có cấu hình riêng cho máy trạm, cây thư mục, mapfile, nhân sự, lịch quét,
báo cáo và thống kê.

Giao diện được xây dựng bằng Flet, dữ liệu lưu trong SQLite, báo cáo và dữ liệu
import/export dùng định dạng Excel.

## Tính năng chính

- Quản lý nhiều dự án scan trong cùng một ứng dụng.
- Khai báo máy trạm hoặc share SMB cần quét file PDF.
- Cấu hình cây thư mục bắt buộc theo từng dự án.
- Sao lưu file scan về thư mục đích, kiểm tra hash và khóa file sau khi sao lưu.
- Phát hiện file sai cấu trúc, file trùng và xung đột backup.
- Import mapfile Excel để đối chiếu hồ sơ cần scan với file đã backup.
- Theo dõi nghiệp vụ Scan/Check, người thực hiện, ngày thực hiện và số trang.
- Xuất báo cáo Excel hằng ngày và thống kê năng suất.
- Có Windows Service để chạy pipeline backup độc lập với giao diện.

## Cấu trúc dự án

```text
Backupfile_TKDA/
├── README.md
├── pyproject.toml
├── requirements.txt
├── main.py
├── service_main.py
├── src/
│   └── scan_backup_manager/
│       ├── backup.py
│       ├── config_excel.py
│       ├── db.py
│       ├── filesystem.py
│       ├── mapfile.py
│       ├── reports.py
│       ├── service_core.py
│       ├── statistics.py
│       ├── windows_service.py
│       └── ui/
├── tests/
├── scripts/
│   └── seed_mock_data.py
└── packaging/
```

Thư mục `data/`, `logs/`, `.venv/`, `dist/` và các file build/runtime không nên
commit lên Git.

## Yêu cầu

- Windows 10/11.
- Git.
- Python 3.11 trở lên, khuyến nghị Python 3.12.
- Kết nối mạng trong lần cài dependency đầu tiên.

Cài Python bằng PowerShell nếu máy chưa có:

```powershell
winget install --id Python.Python.3.12 -e
```

Sau khi cài, đóng PowerShell đang mở và mở cửa sổ mới rồi kiểm tra:

```powershell
python --version
pip --version
```

Nếu Windows mở Microsoft Store hoặc báo không thấy Python, tắt alias tại:

```text
Settings > Apps > Advanced app settings > App execution aliases
```

Tắt `python.exe` và `python3.exe`, sau đó mở PowerShell mới và kiểm tra lại.

## Cài đặt lần đầu

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,build]"
```

Nếu PowerShell chặn `Activate.ps1`, chạy một lần:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Sau đó kích hoạt lại môi trường ảo.

## Chạy ứng dụng

Chạy bằng package:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
.\.venv\Scripts\python.exe -m scan_backup_manager
```

Hoặc chạy file tiện ích:

```powershell
.\.venv\Scripts\python.exe main.py
```

Nếu môi trường ảo đang được kích hoạt, có thể dùng:

```powershell
python -m scan_backup_manager
```

## Đăng nhập ban đầu

Khi mở ứng dụng lần đầu, chọn khu vực quản trị viên.

Mật khẩu Admin mặc định:

```text
Admin@123
```

Ứng dụng sẽ yêu cầu đổi mật khẩu Admin trong lần đăng nhập đầu tiên.

## Tạo dữ liệu demo

Dùng script seed để tạo nhanh dữ liệu mẫu phục vụ kiểm thử giao diện và luồng
backup:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
.\.venv\Scripts\python.exe scripts\seed_mock_data.py
.\.venv\Scripts\python.exe -m scan_backup_manager
```

Script sẽ tạo dự án mẫu, thư mục share giả lập, file PDF hợp lệ, một số file sai
cấu trúc, mapfile Excel và báo cáo mẫu. Nếu database cũ đã tồn tại, script sẽ
đổi tên database cũ thành file `.bak-*` trước khi tạo dữ liệu mới.

## Cấu hình dự án

Trong bảng điều khiển của từng dự án, cần khai báo:

- Mã dự án và tên hiển thị.
- Thư mục backup, staging, conflict archive và thư mục báo cáo.
- Danh mục khổ giấy.
- Cây thư mục bắt buộc.
- Danh sách máy trạm hoặc share cần quét.
- Nhân sự dự án và mã PIN đăng nhập.
- Lịch quét tự động.

Ví dụ đường dẫn file scan hợp lệ:

```text
PROJECT_ALPHA/2024/DOC/A-001/scan.pdf
```

Tên thư mục dự án trên máy trạm phải khớp chính xác với mã dự án đã cấu hình.

## Windows Service

Pipeline backup production có thể chạy độc lập với giao diện bằng Windows
Service. Mở PowerShell bằng quyền Administrator:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
.\.venv\Scripts\Activate.ps1
scan-backup-service install --startup delayed
scan-backup-service start
```

Chạy service ở chế độ console khi phát triển hoặc kiểm tra lỗi:

```powershell
scan-backup-service-console
```

Khi triển khai thật, nên cấu hình service chạy bằng tài khoản Windows/domain có
quyền đọc share của máy trạm và quyền ghi vào thư mục backup trên máy chủ.

## Build EXE

Cài đủ dependency build rồi chạy:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
.\packaging\build.ps1
```

Kết quả build nằm trong `dist/`.

Nếu có Inno Setup, tạo bộ cài bằng:

```powershell
iscc .\packaging\installer.iss
```

## Kiểm tra dành cho lập trình viên

Chạy test:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
.\.venv\Scripts\python.exe -m pytest
```

Kiểm tra cú pháp/import cơ bản:

```powershell
.\.venv\Scripts\python.exe -m compileall src tests
```

## Dữ liệu runtime

Mặc định ứng dụng tạo dữ liệu trong thư mục `data/`, ví dụ:

```text
data/scan_backup_manager.sqlite3
data/mock_env/
```

Có thể đổi thư mục dữ liệu bằng biến môi trường:

```powershell
$env:SCAN_BACKUP_DATA_DIR = "D:\ScanBackupData"
```

Các thư mục báo cáo, staging và conflict archive được tạo theo cấu hình từng dự
án.

## Lỗi thường gặp

### Không thấy lệnh `python`

Cài Python, tắt alias `python.exe` và `python3.exe` trong App execution aliases,
sau đó mở PowerShell mới.

### Không chạy được `Activate.ps1`

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

### Không thấy lệnh `scan-backup-manager`

Dùng lệnh trực tiếp:

```powershell
.\.venv\Scripts\python.exe -m scan_backup_manager
```

Hoặc cài lại package:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
```

### Không clone hoặc push được GitHub

Kiểm tra Git và GitHub CLI:

```powershell
git --version
gh --version
gh auth status
```

Nếu chưa đăng nhập GitHub CLI:

```powershell
gh auth login
```

## Ghi chú triển khai

- Không commit `.venv/`, `data/`, `logs/`, `dist/`.
- Database local mặc định là `data/scan_backup_manager.sqlite3`.
- Nên dùng tài khoản service riêng khi chạy production.
- Sao lưu database trước khi nâng cấp bản production hoặc thay đổi cấu hình lớn.
