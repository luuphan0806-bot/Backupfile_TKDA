# Scan Backup Manager

Scan Backup Manager là ứng dụng desktop chạy trên Windows, dùng để sao lưu các
file PDF scan từ thư mục chia sẻ SMB của máy trạm về cây thư mục backup chuẩn
trên máy chủ. Ứng dụng hỗ trợ nhiều dự án cùng lúc, mỗi dự án có cấu hình máy
trạm, nhân sự, mapfile, cây thư mục, lịch quét và báo cáo riêng.

Giao diện được xây dựng bằng Flet, dữ liệu lưu bằng SQLite, báo cáo xuất ra Excel.

## Tính năng chính

- Quản lý nhiều dự án scan trong cùng một ứng dụng.
- Khai báo máy trạm SMB/share cần quét file PDF.
- Cấu hình cây thư mục bắt buộc theo từng dự án.
- Backup file scan về thư mục đích, kiểm tra hash và khóa file sau khi sao lưu.
- Phát hiện file sai cấu trúc, file trùng và xung đột backup.
- Import mapfile Excel để đối chiếu hồ sơ cần scan với file đã backup.
- Theo dõi nghiệp vụ Scan / Check, người thực hiện, ngày thực hiện và số trang.
- Xuất báo cáo Excel hằng ngày và thống kê năng suất.
- Có Windows Service để chạy pipeline backup độc lập với giao diện.

## Cấu trúc thư mục

```text
Backupfile_TKDA/
├── README.md
├── requirements.txt
├── pyproject.toml
├── main.py
├── service_main.py
├── src/
│   └── scan_backup_manager/
│       ├── __main__.py
│       ├── backup.py
│       ├── constants.py
│       ├── db.py
│       ├── filesystem.py
│       ├── mapfile.py
│       ├── reports.py
│       ├── service_core.py
│       ├── statistics.py
│       ├── windows_service.py
│       └── ui/
├── scripts/
│   └── seed_mock_data.py
├── tests/
├── packaging/
└── data/          # Tạo khi chạy app, không commit lên Git
```

## Yêu cầu cài đặt

- Windows 10/11.
- Git.
- Python 3.11 trở lên, khuyến nghị Python 3.12.
- Kết nối mạng để tải thư viện Python trong lần cài đầu tiên.

Nếu chưa có Python, cài bằng PowerShell:

```powershell
winget install --id Python.Python.3.12 -e
```

Sau khi cài Python, đóng PowerShell đang mở và mở lại cửa sổ mới.

Kiểm tra Python:

```powershell
python --version
pip --version
```

Nếu Windows vẫn báo `Python was not found` hoặc tự mở Microsoft Store, hãy tắt
alias Python tại:

```text
Settings > Apps > Advanced app settings > App execution aliases
```

Tắt hai mục:

```text
python.exe
python3.exe
```

Sau đó mở PowerShell mới và kiểm tra lại `python --version`.

## Cài đặt lần đầu

Vào thư mục project:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
```

Tạo môi trường ảo:

```powershell
python -m venv .venv
```

Kích hoạt môi trường ảo:

```powershell
.\.venv\Scripts\Activate.ps1
```

Nếu PowerShell chặn file `Activate.ps1`, chạy lệnh này một lần:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Sau đó kích hoạt lại:

```powershell
.\.venv\Scripts\Activate.ps1
```

Cài thư viện:

```powershell
python -m pip install -e ".[dev,build]"
```

## Chạy ứng dụng

Sau khi đã cài đặt xong, chạy:

```powershell
python -m scan_backup_manager
```

Hoặc chạy bằng file tiện ích:

```powershell
python main.py
```

Nếu không muốn kích hoạt môi trường ảo, có thể chạy trực tiếp bằng Python trong
`.venv`:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
.\.venv\Scripts\python.exe -m scan_backup_manager
```

## Lệnh chạy nhanh cho các lần sau

Mỗi lần mở máy hoặc mở PowerShell mới, chỉ cần:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
.\.venv\Scripts\python.exe -m scan_backup_manager
```

Hoặc:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
.\.venv\Scripts\Activate.ps1
python -m scan_backup_manager
```

## Tài khoản đăng nhập ban đầu

Khi mở ứng dụng lần đầu, chọn đăng nhập Admin.

Mật khẩu Admin mặc định:

```text
Admin@123
```

Ứng dụng sẽ yêu cầu đổi mật khẩu Admin trong lần đăng nhập đầu tiên.

## Dữ liệu runtime

Khi chạy, ứng dụng tự tạo dữ liệu tại thư mục `data/`, ví dụ:

```text
data/scan_backup_manager.sqlite3
data/mock_env/
```

Các thư mục báo cáo, staging và conflict archive sẽ được tạo theo cấu hình từng
dự án.

## Tạo dữ liệu demo

Nếu muốn thử nhanh giao diện và luồng backup với dữ liệu mẫu:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
.\.venv\Scripts\python.exe scripts\seed_mock_data.py
.\.venv\Scripts\python.exe -m scan_backup_manager
```

Script demo sẽ tạo:

- Hai dự án mẫu: `PROJECT_ALPHA` và `PROJECT_BETA`.
- Thư mục share giả lập cho máy trạm scan.
- File PDF hợp lệ và một số file sai cấu trúc.
- Một trường hợp xung đột backup.
- Mapfile Excel mẫu.
- Báo cáo Excel mẫu.

Nếu đã có database cũ, script sẽ đổi tên database cũ thành file `.bak-*` trước
khi tạo dữ liệu demo mới.

## Cấu hình dự án

Trong tab cấu hình của từng dự án, cần khai báo:

- Mã dự án và tên hiển thị.
- Thư mục backup.
- Thư mục staging.
- Thư mục lưu file xung đột.
- Thư mục xuất báo cáo.
- Danh mục khổ giấy, ví dụ A4/A3.
- Cây thư mục bắt buộc.
- Danh sách máy trạm/share cần quét.
- Nhân sự và mã PIN đăng nhập của nhân sự.
- Lịch quét tự động theo dự án.

Ví dụ cây thư mục file scan hợp lệ:

```text
PROJECT_ALPHA/2024/DOC/A-001/scan.pdf
```

Tên thư mục dự án trên máy trạm phải khớp chính xác với mã dự án đã cấu hình.

## Chạy Windows Service

Pipeline backup production có thể chạy độc lập với giao diện bằng Windows Service.

Sau khi cài project, mở PowerShell bằng quyền Administrator và chạy:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
.\.venv\Scripts\Activate.ps1
scan-backup-service install --startup delayed
scan-backup-service start
```

Để chạy service ở chế độ console khi phát triển hoặc kiểm tra lỗi:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
.\.venv\Scripts\Activate.ps1
scan-backup-service-console
```

Khi triển khai thật, nên cấu hình service chạy bằng tài khoản Windows/domain có
quyền đọc thư mục share của máy trạm và quyền ghi vào thư mục backup trên máy chủ.

## Build file EXE

Cài đủ dependency build rồi chạy:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
.\packaging\build.ps1
```

Kết quả build nằm trong thư mục `dist/`.

Nếu có Inno Setup, có thể tạo bộ cài:

```powershell
iscc .\packaging\installer.iss
```

## Lệnh kiểm tra dành cho lập trình viên

Chạy test:

```powershell
cd D:\CODE\Backup\Backupfile_TKDA
.\.venv\Scripts\python.exe -m pytest
```

Kiểm tra package có chạy được không:

```powershell
.\.venv\Scripts\python.exe -m scan_backup_manager
```

## Lỗi thường gặp

### PowerShell báo không thấy `python`

Cài Python:

```powershell
winget install --id Python.Python.3.12 -e
```

Đóng PowerShell, mở lại và kiểm tra:

```powershell
python --version
```

Nếu vẫn lỗi, tắt alias `python.exe` và `python3.exe` trong App execution aliases
của Windows.

### Không chạy được `Activate.ps1`

Chạy:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Sau đó chạy lại:

```powershell
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

### Không clone/push được GitHub

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

- Không commit thư mục `.venv/`, `data/`, `logs/`, `dist/`.
- Database mặc định nằm trong `data/scan_backup_manager.sqlite3` khi chạy local.
- Có thể đặt biến môi trường `SCAN_BACKUP_DATA_DIR` để đổi thư mục lưu dữ liệu
  runtime.
- Khi chạy production bằng service, nên dùng tài khoản service riêng thay vì tài
  khoản cá nhân.
