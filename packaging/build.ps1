# Builds standalone Windows executables.
# Run from the repository root after:
#   python -m pip install -e ".[dev,build]"

$ErrorActionPreference = "Stop"

# Guard the interpreter used for packaging. flet pack + PyInstaller are
# validated here on Python 3.11-3.13; 3.12 is the recommended target.
$pyVersion = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
$supported = @("3.11", "3.12", "3.13")
if ($supported -notcontains $pyVersion) {
    throw "Python $pyVersion is outside the supported build range (3.11-3.13; 3.12 recommended). Activate a supported interpreter before building."
}
if ($pyVersion -ne "3.12") {
    Write-Warning "Building with Python $pyVersion. The recommended/tested packaging target is 3.12."
}
Write-Host "Building with Python $pyVersion"

$appVersion = & python -c "import pathlib, tomllib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])"
if ($LASTEXITCODE -ne 0 -or -not $appVersion) {
    throw "Could not read project.version from pyproject.toml"
}
$versionParts = @($appVersion.Split("."))
if ($versionParts.Count -gt 4 -or @($versionParts | Where-Object { $_ -notmatch '^\d+$' }).Count -gt 0) {
    throw "Project version must contain one to four numeric components: $appVersion"
}
while ($versionParts.Count -lt 4) {
    $versionParts += "0"
}
$fileVersion = $versionParts -join "."
$versionTuple = "(" + ($versionParts -join ", ") + ")"
Write-Host "Embedding product version $appVersion (file version $fileVersion)"

flet pack main.py -n ScanBackupManager --distpath dist `
    --product-name "Scan Backup Manager" `
    --file-description "Scan Backup Manager desktop application" `
    --product-version $appVersion `
    --file-version $fileVersion `
    --company-name "Scan Backup Manager" `
    --add-data "MauChamCong.xlsx:." `
    -y
if ($LASTEXITCODE -ne 0) {
    throw "ScanBackupManager build failed with exit code $LASTEXITCODE"
}

$serviceVersionFile = Join-Path $env:TEMP ("sbm-version-" + [guid]::NewGuid().ToString("N") + ".txt")
try {
    pyi-grab_version "dist\ScanBackupManager.exe" $serviceVersionFile
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $serviceVersionFile)) {
        throw "Could not extract Windows version metadata for the service EXE"
    }
    $serviceVersionInfo = Get-Content -Path $serviceVersionFile -Raw
    $serviceVersionInfo = $serviceVersionInfo `
        -replace '(?m)^\s*prodvers=\([^\r\n]+\),', "    prodvers=$versionTuple," `
        -replace "StringStruct\('FileDescription', '[^']*'\)", "StringStruct('FileDescription', 'Scan Backup Manager Windows Service')" `
        -replace "StringStruct\('InternalName', '[^']*'\)", "StringStruct('InternalName', 'ScanBackupService')" `
        -replace "StringStruct\('OriginalFilename', '[^']*'\)", "StringStruct('OriginalFilename', 'ScanBackupService.exe')"
    $serviceVersionInfo | Set-Content -Path $serviceVersionFile -Encoding UTF8
    pyinstaller --noconfirm --onefile --name ScanBackupService service_main.py `
        --distpath dist `
        --hidden-import win32timezone `
        --version-file $serviceVersionFile
    if ($LASTEXITCODE -ne 0) {
        throw "ScanBackupService build failed with exit code $LASTEXITCODE"
    }
} finally {
    Remove-Item -LiteralPath $serviceVersionFile -Force -ErrorAction SilentlyContinue
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
    if ($LASTEXITCODE -ne 0) {
        throw "Installer build failed with exit code $LASTEXITCODE"
    }
    $installerPath = ".\packaging\Output\ScanBackupManager-Setup.exe"
    if (-not (Test-Path $installerPath)) {
        throw "Installer build completed without producing $installerPath"
    }
} else {
    Write-Warning "Inno Setup is not installed. EXE files were created in dist\, but installer was not created."
    Write-Host "Download Inno Setup 6: https://jrsoftware.org/isdl.php"
}
