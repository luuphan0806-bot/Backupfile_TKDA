# Builds standalone Windows executables.
# Run from the repository root after:
#   python -m pip install -e ".[dev,build]"

$ErrorActionPreference = "Stop"

# Guard the interpreter used for packaging. flet pack + PyInstaller are only
# validated on the versions declared in pyproject.toml (>=3.11,<3.14); 3.12 is
# the recommended target. Building on an untested interpreter can produce an
# EXE that behaves differently from the tested source.
$pyVersion = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
$supported = @("3.11", "3.12", "3.13")
if ($supported -notcontains $pyVersion) {
    throw "Python $pyVersion is outside the supported build range (3.11-3.13; 3.12 recommended). Activate a supported interpreter before building."
}
if ($pyVersion -ne "3.12") {
    Write-Warning "Building with Python $pyVersion. The recommended/tested packaging target is 3.12."
}
Write-Host "Building with Python $pyVersion"

flet pack main.py -n ScanBackupManager --distpath dist -y
if ($LASTEXITCODE -ne 0) {
    throw "ScanBackupManager build failed with exit code $LASTEXITCODE"
}
pyinstaller --noconfirm --onefile --name ScanBackupService service_main.py --distpath dist --hidden-import win32timezone
if ($LASTEXITCODE -ne 0) {
    throw "ScanBackupService build failed with exit code $LASTEXITCODE"
}

$isccCandidates = @()
$isccCommand = Get-Command iscc -ErrorAction SilentlyContinue
if ($isccCommand) {
    $isccCandidates += $isccCommand.Source
}
$isccCandidates += @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)

$isccPath = $isccCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($isccPath) {
    & $isccPath ".\packaging\installer.iss"
} else {
    Write-Warning "Inno Setup is not installed. EXE files were created in dist\, but installer was not created."
    Write-Host "Download Inno Setup 6: https://jrsoftware.org/isdl.php"
}
