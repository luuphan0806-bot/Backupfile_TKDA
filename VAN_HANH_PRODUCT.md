# Van hanh product Scan Backup Manager

Tai lieu nay la checklist dua ung dung tu moi truong dev sang van hanh noi bo. Moi lan release nen di tu tren xuong duoi va luu lai output lenh trong thu muc ban giao.

## 1. First-run va health check

Chay tren data dir sach:

```powershell
$env:SCAN_BACKUP_DATA_DIR="$PWD\data\release-smoke"
python scripts\product_hardening_check.py health
```

Dieu kien dat:

- JSON tra ve `"ok": true`.
- `db_exists` la `true`.
- `admin_default_password_valid` va `admin_must_change_password` la `true` voi DB moi.
- File log trong `logs\app.log` duoc tao.

Sau khi nguoi quan tri dang nhap lan dau, phai doi mat khau mac dinh `Admin@123`.

## 2. Smoke test app that

Chay tu source:

```powershell
$env:SCAN_BACKUP_DATA_DIR="$PWD\data\release-smoke"
python main.py
```

Kiem tra bang UI that:

- Cua so Flet mo o che do desktop, khong mo browser.
- Man chon vai tro hien thi ro, nut sang/toi hoat dong.
- Dang nhap admin bang `Admin@123` voi DB moi va app yeu cau doi mat khau.
- Tao du an moi, khai bao thu muc backup/staging/conflict/report rieng.
- Tao may tram test tro vao mot thu muc local co quyen doc/ghi.
- Tao nhan su, loai cong viec Scan/Check, cau truc thu muc ho so.
- Tao cong viec Scan, backup thu mot PDF that, sau do tao cong viec Check tu danh sach ho so du dieu kien.
- Resize cua so ve kich thuoc nho nhat va dam bao bang/dia log khong de chu de len nhau.

## 3. Smoke test service

Chay service o console truoc khi cai Windows Service:

```powershell
$env:SCAN_BACKUP_DATA_DIR="$PWD\data\release-smoke"
python service_main.py console
```

Dung `Ctrl+C` sau khi thay log heartbeat hoac job duoc xu ly. Neu chay bang command installed:

```powershell
scan-backup-service-console
```

Dieu kien dat:

- Khong crash khi khong co du an.
- Co heartbeat tren Dashboard khi service dang chay.
- Voi du an enabled, service enqueue `SCAN_PROJECT` va `VERIFY_INTEGRITY`.
- Share offline duoc ghi audit/log, khong lam service dung vong lap.

## 4. Build va smoke EXE

Build tren Python 3.12 la muc tieu khuyen nghi:

```powershell
python -m pip install -e ".[dev,build]"
.\packaging\build.ps1
```

Dieu kien dat:

- Co `dist\ScanBackupManager.exe`.
- Co `dist\ScanBackupService.exe`.
- `dist\ScanBackupManager.exe` mo duoc app that voi data dir test.
- `dist\ScanBackupService.exe` nhan lenh service cua pywin32 tren may co quyen admin.

Neu Inno Setup khong co, EXE van duoc coi la dat smoke; installer la artifact bo sung.

## 5. Snapshot va recovery DB

Tạo snapshot trước mọi thay đổi lớn:

```powershell
python scripts\product_hardening_check.py snapshot --label before-release
```

Co the tao snapshot trong UI tai `Cau hinh / Cai dat` -> `Sao luu / khoi phuc CSDL`.

Restore khi can rollback:

```powershell
python scripts\product_hardening_check.py restore "duong_dan_snapshot.sqlite3"
```

Restore trong UI yeu cau nhap mat khau admin, tu tao snapshot `pre_restore`, sau do dua nguoi dung ve man dang nhap de nap lai du lieu moi.

Quy tac an toan:

- Dung app va service truoc khi restore.
- Lenh restore tu tao snapshot `pre_restore` cua DB hien tai.
- Khong copy rieng file `.sqlite3` khi app dang dung WAL; dung script snapshot de co ban sao nhat quan.

## 6. Go / No-go

Duoc release khi tat ca muc sau dat:

- `python -m compileall src main.py service_main.py` pass.
- `python -m pytest` pass.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\write_release_manifest.ps1` tao `dist\release-manifest.json`.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\release_smoke.ps1` pass va tao `dist\release-smoke-report.json`.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\product_readiness_audit.ps1` pass va tao `dist\product-readiness-report.json`.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\make_release_bundle.ps1` tao ZIP ban giao trong `dist\release\`.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_release_bundle.ps1 -BundlePath dist\release\ScanBackupManager-release-YYYYMMDD-HHMMSS.zip` pass voi `ok=true`.
- Tren may trien khai co quyen admin: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\release_smoke.ps1 -IncludeAdminService` pass hoac bao `skipped_existing_service` neu service production da ton tai va duoc giu nguyen. Neu script tu cai service tam, phai co `db_path` va `log_path` do service that tao ra trong data dir smoke.
- Health check first-run pass tren data dir sach.
- UI composition smoke pass tren data dir sach: role selection, admin login, first-run change password, main shell, toan bo 6 tab project console, Projects, Settings/recovery, Audit va Personnel login deu build duoc; action `Sao luu ngay` trong Settings/recovery tao duoc snapshot that va khong bi ket disabled.
- Pipeline smoke tao PDF that trong thu muc may tram local, backup ra kho va dua ho so vao danh sach check-ready.
- App source smoke pass bang UI that.
- Service console smoke pass.
- Neu giao EXE: build pass va EXE mo/chay duoc.
- Manifest SHA256 khop voi `dist\ScanBackupManager.exe`, `dist\ScanBackupService.exe` va installer.
- Manifest ghi ro `authenticode_status` cua tung EXE/installer; neu trien khai rong ngoai noi bo thi phai ky so de tranh SmartScreen/AV canh bao.
- Neu trien khai rong cho nguoi dung cuoi: `scripts\write_release_manifest.ps1 -RequireSigned` va `scripts\verify_release_bundle.ps1 ... -RequireSigned` phai pass.
- Ban giao kem `dist\release-manifest.json` va `dist\release-smoke-report.json`.
- Ban giao kem `dist\product-readiness-report.json` de biet check nao pass/warn/fail.
- Ban giao ZIP release va file `.json` cung ten de doi chieu SHA256 cua ZIP.
- ZIP release phai verify duoc bang `scripts\verify_release_bundle.ps1`; khong ban giao ZIP chi moi tao nhung chua verify.
- ZIP release phai kem cac script hardening/release de audit lai: `product_hardening_check.py`, `product_readiness_audit.ps1`, `release_smoke.ps1`, `service_admin_smoke.ps1`, `sign_release_artifacts.ps1`, `write_release_manifest.ps1`, `make_release_bundle.ps1`, `verify_release_bundle.ps1`.
- Neu rollout rong: ky artifact bang `scripts\sign_release_artifacts.ps1`, tao lai manifest voi `-RequireSigned`, tao lai ZIP, roi verify ZIP voi `-RequireSigned`.
- Co snapshot DB truoc release va tai lieu duong dan snapshot.

No-go neu co mot trong cac loi:

- Check co the tao tu ho so chua co file backup that.
- Backup ghi thanh cong trong DB nhung file vat ly khong ton tai.
- Service crash khi gap share offline hoac file loi.
- Restore DB khong tao pre-restore snapshot.
- UI co dialog/bang bi tran chu o kich thuoc toi thieu.
- Trien khai rong cho nguoi dung cuoi bang EXE/installer chua ky so.
