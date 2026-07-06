# Builds a standalone Windows executable via `flet pack` (PyInstaller-based).
# Run from the repository root after `pip install -e ".[dev,build]"`.
#
# For a Flutter-native build instead, use `flet build windows` (requires
# Visual Studio "Desktop development with C++" workload + the Flutter SDK).

flet pack src/scan_backup_manager/ui/app.py -n ScanBackupManager --distpath dist
pyinstaller --noconfirm --onefile --name ScanBackupService service_main.py --distpath dist --hidden-import win32timezone

$isccCandidates = @(
    (Get-Command iscc -ErrorAction SilentlyContinue).Source,
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if ($isccCandidates) {
    & $isccCandidates[0] ".\packaging\installer.iss"
} else {
    Write-Warning "Chưa cài Inno Setup. Hai file EXE đã được tạo trong dist\, nhưng chưa tạo bộ cài."
    Write-Host "Tải Inno Setup 6 tại: https://jrsoftware.org/isdl.php"
}
