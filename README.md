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
- Cấu trúc riêng từng dự án: các cấp nghiệp vụ như `[Năm]`,
  `[Loại hồ sơ]`, `[Mã hồ sơ]`.
- Danh mục hồ sơ: danh sách giá trị hợp lệ cho từng cấp, thứ tự hiển thị trong
  Mapfile hệ thống và dấu tích đưa cột vào/ra khỏi phần cột động sau `STT`.
- Danh sách máy trạm: nhập `IP máy trạm` và `Thư mục share`, hệ thống tự ghép
  đường dẫn UNC dạng `\\192.168.1.71\csdl_sohoa_demo`.
- Nhân sự dự án: chỉ cần `Mã nhân viên`, `Họ và tên`, `Kích hoạt`.
- Lịch quét tự động.

Cấu trúc chung trên máy trạm của nhân sự:

```text
CSDL_SOHOA_<mã dự án>/[Họ tên]/[Ngày]/[Nội dung công việc]
```

Cấu trúc riêng từng dự án được nối phía sau cấu trúc chung:

```text
[Năm]/[Loại hồ sơ]/[Mã hồ sơ]/Tên file pdf
```

Vì vậy cây thư mục đầy đủ trên máy trạm là:

```text
CSDL_SOHOA_<mã dự án>/[Họ tên]/[Ngày]/[Nội dung công việc]/[Năm]/[Loại hồ sơ]/[Mã hồ sơ]/Tên file pdf
```

Ví dụ:

```text
\\192.168.1.71\csdl_sohoa_demo\CSDL_SOHOA_PROJECT_ALPHA\Nguyen Van A\09-07-2026\Scan A4\2024\DOC\A-001\scan.pdf
```

Khi bấm kiểm tra kết nối máy trạm, app kiểm tra cả việc truy cập share và quyền
ghi bằng cách tạo/xóa một thư mục test tạm. Tài khoản Windows chạy app/service
cần có quyền đọc và ghi trên share máy trạm.

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

## Pipeline dữ liệu hệ thống

Hệ thống có hai pipeline dữ liệu chính chạy song song và gặp nhau ở SQLite:

1. Pipeline nghiệp vụ hồ sơ: cấu hình dự án, mapfile, công việc Scan/Check,
   nhân sự, số trang, số file và ngày thực hiện.
2. Pipeline backup vật lý: quét file PDF từ máy trạm hoặc share SMB, copy về
   kho backup, kiểm tra hash, khóa file và ghi nhận trạng thái.

Luồng tổng quát:

```text
Cấu hình dự án
   ↓
Máy trạm / Share SMB / Mapfile Excel / Thao tác UI
   ↓
SQLite trung tâm
   ↓
Pipeline backup + Pipeline đối chiếu mapfile
   ↓
Mapfile hệ thống / Dashboard / Thống kê / Báo cáo Excel
```

### Pipeline mapfile và nghiệp vụ hồ sơ

Nguồn vào có thể là file Excel mapfile hoặc dòng hồ sơ được thêm thủ công trong
tab Mapfile hệ thống.

```text
Excel mapfile hoặc nhập tay
   ↓
MapfileService đọc và chuẩn hóa dữ liệu
   ↓
Sinh expected_relative_path
   ↓
Lưu vào mapfile_imports + mapfile_rows
   ↓
Đối chiếu với backup_files
   ↓
Cập nhật trạng thái MATCHED / MISSING
```

Ví dụ một dòng hồ sơ có thể sinh đường dẫn kỳ vọng:

```text
PROJECT_ALPHA/2024/DOC/A-001/1.pdf
```

Với luồng tạo công việc hiện tại, hệ thống chỉ tạo thư mục hồ sơ ở máy
trạm/share. Tên file mặc định chỉ là khóa kỹ thuật nội bộ cho dòng mapfile,
không tạo file vật lý trên ổ đĩa.

Trạng thái nghiệp vụ Scan/Check được lưu theo hồ sơ và theo từng khổ giấy:

```text
Hồ sơ
   ↓
Scan A4 / Scan A3
   ↓
Lưu người scan, số trang, số file, ngày scan
   ↓
Check Scan
   ↓
Lưu người check, số trang check, ngày check
   ↓
Cập nhật trạng thái hồ sơ
```

Dữ liệu chính:

- `record_workflows`: trạng thái tổng của hồ sơ.
- `record_paper_statuses`: trạng thái theo khổ giấy A4/A3/A0, gồm người scan,
  ngày scan, số trang và số file.
- `project_tasks`: công việc giao cho nhân sự.
- `mapfile_rows`: danh sách hồ sơ/file kỳ vọng cần đối chiếu.

Mapfile hệ thống có nhóm cột cố định:

```text
STT | ... | Scan A4 | Scan A3 | Check hồ sơ | Trạng thái hồ sơ | Tình trạng backup | Máy lưu | Thao tác
```

Phần `...` là các cột danh mục được cấu hình trong tab `Danh mục hồ sơ`. Admin
có thể tích/bỏ tích từng cấp danh mục để đưa vào Mapfile hệ thống và đổi thứ tự
hiển thị của các cột này.

### Pipeline backup vật lý

Pipeline backup đọc file PDF từ các máy trạm hoặc thư mục chia sẻ đã cấu hình.

```text
Máy trạm / Share SMB
   ↓
Tìm thư mục đúng mã dự án
   ↓
Quét toàn bộ file PDF
   ↓
Validate cấu trúc thư mục
   ↓
Ghi nhận DISCOVERED hoặc INVALID_STRUCTURE
   ↓
Chờ file ổn định
   ↓
Copy qua staging
   ↓
Move/copy vào backup_root
   ↓
Kiểm tra size
   ↓
Tính SHA256
   ↓
Khóa read-only
   ↓
Cập nhật backup_files
```

Các trạng thái quan trọng:

- `DISCOVERED`: phát hiện file hợp lệ trên máy trạm/share.
- `INVALID_STRUCTURE`: file sai cấu trúc thư mục hoặc không đúng PDF.
- `WAITING_STABLE`: file đang thay đổi, chưa copy.
- `COPYING`: đang copy file.
- `HASH_PENDING`: đã copy và ghi hash, chờ/đang xác thực.
- `LOCKED`: đã xác thực và khóa read-only.
- `ALREADY_EXISTS`: file đích đã có cùng nội dung.
- `CONFLICT`: file đích tồn tại nhưng khác nội dung.
- `ERROR`: lỗi xử lý.

Windows Service hoặc chế độ console dùng job queue trong bảng `backup_jobs`:

```text
Service chạy nền
   ↓
schedule_due_projects()
   ↓
enqueue backup_jobs
   ↓
claim_next_job()
   ↓
BackupManager.run_all_enabled()
   ↓
finish_job()
```

Các loại job chính:

- `SCAN_PROJECT`: quét và backup toàn bộ dự án.
- `VERIFY_INTEGRITY`: kiểm tra hash các file pending.
- `REPLACE_CONFLICT`: thay thế file conflict sau khi được xử lý.

## Cấu trúc thư mục dữ liệu

Trong môi trường demo, các thư mục runtime thường nằm dưới:

```text
D:\AI\Backupfile_TKDA\data\mock_env
```

Cấu trúc chính:

```text
data/mock_env/
├─ backup/             Kho lưu trữ chính sau khi backup thành công
├─ staging/            Vùng tạm khi đang copy file
├─ conflict_archive/   Kho lưu file cũ khi xử lý xung đột
└─ reports/            Nơi xuất báo cáo Excel
```

Luồng file điển hình:

```text
shares/máy trạm/
└─ CSDL_SOHOA_<mã dự án>/
   └─ [Họ tên]/
      └─ [Ngày]/
         └─ [Nội dung công việc]/
            └─ [Năm]/[Loại hồ sơ]/[Mã hồ sơ]/Tên file pdf
   ↓
staging
   ↓
backup
   ↓
reports / thống kê / mapfile hệ thống

Nếu conflict:
backup file cũ → conflict_archive
file mới → staging → backup
```

Trong đó `[Năm]/[Loại hồ sơ]/[Mã hồ sơ]/Tên file pdf` là **cấu trúc riêng từng
dự án**. Phần đứng trước nó là cấu trúc chung trên máy trạm của nhân sự:

```text
CSDL_SOHOA_<mã dự án>/[Họ tên]/[Ngày]/[Nội dung công việc]
```

### `backup`

Ví dụ:

```text
D:\AI\Backupfile_TKDA\data\mock_env\backup
```

Đây là kho lưu trữ chính của hệ thống. File PDF sau khi được quét từ máy
trạm/share, kiểm tra hợp lệ và copy thành công sẽ nằm ở đây.

Cấu trúc theo mã dự án và cây thư mục hồ sơ:

```text
backup/
└─ PROJECT_ALPHA/
   └─ 2024/
      ├─ DOC/
      │  ├─ A-001/
      │  ├─ A-002/
      │  └─ A-003/
      └─ INVOICE/
         └─ INV-1001/
```

Vai trò:

- Lưu file backup cuối cùng.
- Là nguồn đối chiếu với mapfile.
- File trong đây thường được set read-only sau khi copy và xác thực.
- Dữ liệu tương ứng được ghi vào bảng `backup_files`.
- Nếu file trong `backup` khớp với dòng mapfile, dòng mapfile chuyển sang
  `MATCHED`.

Logic đường dẫn đích:

```text
backup_root / project_code / relative_project_path
```

Ví dụ:

```text
backup/PROJECT_ALPHA/2024/DOC/A-001/scan.pdf
```

### `staging`

Ví dụ:

```text
D:\AI\Backupfile_TKDA\data\mock_env\staging
```

Đây là vùng tạm trong lúc copy file. Hệ thống không ghi trực tiếp file đang copy
vào kho backup cuối cùng, mà copy qua staging trước rồi mới chuyển sang thư mục
đích.

Cấu trúc runtime thường có dạng:

```text
staging/
└─ <project_id>/
   └─ <job_id hoặc manual>/
      └─ <ten_file>.tmp
```

Ví dụ:

```text
staging/1/25/scan.pdf.tmp
staging/1/manual/scan.pdf.tmp
```

Vai trò:

- Tránh file backup đích bị dở dang nếu copy lỗi.
- Chứa file `.tmp` trong quá trình copy.
- Hỗ trợ copy an toàn bằng `robocopy` hoặc `shutil`.
- Sau khi copy thành công, file tạm được chuyển/replace vào `backup`.
- Nếu copy lỗi, file tạm có thể bị xóa hoặc để lại để debug.

Luồng:

```text
source PDF
   ↓
staging/<project_id>/<job_id>/<file>.tmp
   ↓
backup/PROJECT/...
```

### `conflict_archive`

Ví dụ:

```text
D:\AI\Backupfile_TKDA\data\mock_env\conflict_archive
```

Đây là kho lưu file cũ khi xử lý xung đột. Conflict xảy ra khi file nguồn mới
có cùng đường dẫn đích với file đã tồn tại trong `backup`, nhưng nội dung khác
nhau.

Cấu trúc thường có dạng:

```text
conflict_archive/
└─ <client_code>/
   └─ <ten_file>.conflict-<conflict_id>.pdf
```

Ví dụ:

```text
conflict_archive/SCAN01/scan-03.conflict-7.pdf
```

Vai trò:

- Lưu bản cũ trước khi thay thế.
- Cho phép truy vết và phục hồi nếu cần.
- Tránh mất dữ liệu khi xử lý conflict.
- Gắn với bảng `conflicts` trong SQLite.

Luồng xử lý conflict:

```text
backup/file_cũ.pdf
   ↓
conflict_archive/SCAN01/file_cũ.conflict-<id>.pdf

source/file_mới.pdf
   ↓
staging
   ↓
backup/file_mới.pdf
```

Nếu chưa phát sinh hoặc chưa xử lý conflict thì thư mục này có thể chưa có nội
dung.

### `reports`

Ví dụ:

```text
D:\AI\Backupfile_TKDA\data\mock_env\reports
```

Đây là thư mục xuất báo cáo Excel và file mẫu import/export cấu hình.

Các file thường gặp:

```text
reports/
├─ mau_nhap_nhan_su.xlsx
├─ scan_backup_report_YYYYMMDD_HHMMSS.xlsx
└─ statistics_report_<date_from>_<date_to>_YYYYMMDD_HHMMSS.xlsx
```

Vai trò:

- Lưu báo cáo backup tổng hợp.
- Lưu báo cáo thống kê năng suất.
- Lưu file mẫu import/export cấu hình như nhân sự, máy trạm, danh mục.
- Là đầu ra để admin kiểm tra, lưu trữ hoặc gửi cho bên liên quan.

Báo cáo backup thường gồm:

- `Summary`
- `Backup Files`
- `Conflicts`
- `Mapfile`
- `Personnel`
- `Tasks`

Báo cáo thống kê thường gồm:

- `Daily`
- `Personnel`
- `Summary`
- Tỷ lệ hoàn thành.
- Độ trễ từ lúc Done đến lúc Backup.

### Tóm tắt nhiệm vụ thư mục

| Thư mục | Vai trò | Có nên sửa tay? |
| --- | --- | --- |
| `backup` | Kho lưu chính sau khi backup thành công | Không nên sửa/xóa thủ công |
| `staging` | Vùng tạm khi copy file | Có thể dọn khi chắc chắn service đã dừng |
| `conflict_archive` | Lưu file cũ khi xử lý xung đột | Không nên xóa nếu cần truy vết |
| `reports` | Chứa báo cáo Excel và file mẫu export | Có thể copy/gửi/lưu trữ theo nhu cầu |

Nói ngắn gọn: `staging` là đường trung chuyển, `backup` là kho chính,
`conflict_archive` là kho an toàn khi thay thế file, còn `reports` là đầu ra
kiểm tra và báo cáo.

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
