# Scan Backup Manager

Scan Backup Manager is a Windows desktop app that backs up PDF scan files from
workstation SMB shares into a canonical server backup tree. The console
manages **multiple projects at once** -- each with its own workstations,
personnel, mapfile mapping, directory tree, and polling schedule. The UI is
built with [Flet](https://flet.dev) (Python + Flutter rendering).

## Project Structure

```text
scan-backup-manager/
├── README.md
├── requirements.txt
├── pyproject.toml
├── .env.example
├── .gitignore
├── main.py
├── src/
│   └── scan_backup_manager/
│       ├── __main__.py
│       ├── constants.py
│       ├── models.py
│       ├── db.py
│       ├── filesystem.py
│       ├── backup.py
│       ├── mapfile.py
│       ├── reports.py
│       ├── statistics.py
│       ├── i18n.py
│       ├── logging_config.py
│       └── ui/
│           ├── app.py
│           ├── state.py
│           ├── theme.py
│           ├── workers.py
│           ├── project_scheduler.py
│           └── views/
│               ├── overview.py
│               ├── project_list.py
│               ├── project_console/   (5 tabs: dashboard, mapfile, tasks, statistics, settings)
│               ├── global_settings.py
│               └── audit.py
├── tests/
├── scripts/
│   └── seed_mock_data.py
├── packaging/
├── data/    (created at runtime, git-ignored)
└── logs/    (created at runtime, git-ignored)
```

| Path | Purpose |
| --- | --- |
| `README.md` | Project overview, setup, architecture, usage. |
| `requirements.txt` | Plain pip dependency list, mirrors `pyproject.toml`. |
| `pyproject.toml` | Authoritative package metadata, dependencies, console script, pytest config. |
| `.env.example` | Placeholder -- the app has no required environment variables today (see file). |
| `.gitignore` | Files/folders Git should not track. |
| `main.py` | Convenience launcher (`python main.py`), same as `python -m scan_backup_manager`. |
| `src/scan_backup_manager/db.py` | SQLite schema, migrations, and all CRUD/query methods. |
| `src/scan_backup_manager/backup.py` | Core backup logic: share scanning, copy/verify/lock, conflict handling, on-demand single-file backup. |
| `src/scan_backup_manager/mapfile.py` | Excel mapfile import and reconciliation against backed-up files. |
| `src/scan_backup_manager/reports.py` | Daily and statistics Excel report export. |
| `src/scan_backup_manager/statistics.py` | Productivity/completion/latency queries used by the Thống kê tab. |
| `src/scan_backup_manager/filesystem.py` | Low-level file discovery, validation, hashing, and copy helpers. |
| `src/scan_backup_manager/i18n.py` | Vietnamese/English translation strings (auth screens). |
| `src/scan_backup_manager/logging_config.py` | Rotating file logger under `logs/app.log`. |
| `src/scan_backup_manager/ui/` | Flet desktop UI: app shell, navigation, per-screen views. |
| `tests/` | Pytest unit/integration tests for the backend modules. |
| `scripts/seed_mock_data.py` | Builds a local demo environment with sample projects/data. |
| `packaging/build.ps1` | Wraps `flet pack` to produce a standalone `.exe` (see Build below). |
| `data/` | Runtime SQLite database and per-project files (created automatically). |
| `logs/` | Rotating application log file (created automatically). |

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,build]"
python -m scan_backup_manager
```

The app creates local runtime data under `data/` by default:

- `data/scan_backup_manager.sqlite3`
- per-project `reports/`, `conflict_archive/`, and `staging/` directories, as
  configured in each project's own settings

At startup, choose **Admin** or **Project personnel**. Personnel sign in with
project code, personnel code, and a six-digit PIN created by Admin. The
initial Admin password is:

```text
Admin@123
```

The app requires this password to be changed on the first Admin login.

## Navigation

The top-level menu has exactly four sections:

- **Tổng Quan** -- aggregated KPIs and health across every project.
- **Danh sách dự án** -- the project list; click a project to open its own
  console. Includes creating new projects.
- **Cấu hình / Cài đặt** -- system-wide settings: admin password, theme,
  language, default values for new projects, and manual database backup.
- **Nhật ký hệ thống** -- a filterable view over the `audit_logs` table
  (by project, action, workstation, date range).

Opening a project from the list leads to its own console with 5 tabs:

- **Bảng điều khiển** -- KPIs, workstation health, recent activity, open
  conflicts, and the manual "Chạy backup ngay" / "Kiểm tra hash" actions.
- **Danh mục hồ sơ** -- the imported Excel list and the **Đã quét xong**
  progress marker. The Windows service remains responsible for automatic
  backup; personnel cannot trigger file operations.
- **Công việc** -- tasks assigned to project personnel.
- **Thống kê** -- productivity by day/personnel, completion ratio, and
  Done-to-backup latency, with an Excel export.
- **Cấu hình** -- project info and directory tree, mapfile column mapping,
  workstations, personnel, and per-project polling settings.

## Project Setup

In a project's **Cấu hình** tab, configure:

- Project code and display name
- Backup, staging, conflict archive, and reports directories
- A required ordered directory tree

Each directory level supports one validation type:

- `YEAR4`: a four-digit year
- `ENUM`: one of the configured values
- `INTEGER`: digits only
- `TEXT`: any non-empty directory name

The project folder on each workstation must match the configured project code
exactly. For project code `PROJECT_ALPHA` and levels Year, Category, Record ID:

```text
PROJECT_ALPHA/2024/DOC/A-001/scan.pdf
```

## Windows Service

The production pipeline runs independently from the UI:

```powershell
scan-backup-service install --startup delayed
scan-backup-service start
```

Configure the service to use a dedicated Windows/domain account that can read
workstation shares and write the backup destination. For development:

```powershell
scan-backup-service-console
```

Runtime data and logs default to
`%PROGRAMDATA%\ScanBackupManager`. Set `SCAN_BACKUP_DATA_DIR` to override this
location. On first production startup, an existing local `data/` database is
copied; the original is retained.

## Database Upgrade

Schema v4 adds durable backup jobs, operation leases, service heartbeat, and
personnel PIN credentials. Databases created by earlier releases
`projects` row) are migrated **in place** the first time they're opened by
this version: the `projects`/`mapfile_profiles` tables are rebuilt without the
old single-project constraint, per-project polling settings are seeded from
the previous global values, and a `.bak-<version>-<timestamp>` copy is made
before any change -- no data is deleted. Only truly unreadable/pre-versioned
databases still fall back to the old backup-and-reset behavior.

## Interface Language & Theme

**Cấu hình / Cài đặt** includes a language selector (Tiếng Việt / English) and
a light/dark theme toggle. Both are saved in SQLite under the `language` and
`theme_mode` settings.

## Mock Demo Data

Create a full local demo environment for testing the workflow and UI:

```powershell
python scripts/seed_mock_data.py
python -m scan_backup_manager
```

The script builds `data/mock_env` with two demo projects (`PROJECT_ALPHA`,
`PROJECT_BETA`), including:

- demo workstation shares,
- valid PDF files,
- invalid folder structures,
- one backup conflict,
- an Excel mapfile with matched, missing, and one Done-but-not-yet-backed-up row,
- a generated daily report.

It seeds the default SQLite database used by the app. If an existing database is
present, the script renames it to a timestamped `.bak-*` file before creating
the demo database.

## Build

```powershell
.\packaging\build.ps1
iscc .\packaging\installer.iss
```

This creates separate UI and Windows Service executables. Inno Setup bundles
them and prompts for the dedicated service account. For a Flutter-native build instead, use
`flet build windows` -- this requires Visual Studio (Desktop development with
C++ workload) and the Flutter SDK on the build machine.
