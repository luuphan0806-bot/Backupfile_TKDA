# Builds standalone Windows executables.
# Run from the repository root after:
#   python -m pip install -e ".[dev,build]"

$ErrorActionPreference = "Stop"

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
