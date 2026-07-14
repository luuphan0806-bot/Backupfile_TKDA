param(
    [int]$AppWaitSeconds = 12,
    [int]$ServiceWaitSeconds = 8,
    [switch]$SkipExe,
    [switch]$IncludeAdminService,
    [string]$OutputPath = "dist\release-smoke-report.json",
    [switch]$KeepTemp
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PreviousLocation = Get-Location
$TempRoots = New-Object System.Collections.Generic.List[string]
$BaselineRuntimeProcessIds = @(
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessName -like "ScanBackup*" -or $_.ProcessName -eq "flet" } |
        Select-Object -ExpandProperty Id
)

function New-SmokeDataDir([string]$Name) {
    $dir = Join-Path $env:TEMP ("sbm-$Name-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $dir | Out-Null
    $TempRoots.Add($dir) | Out-Null
    return $dir
}

function Stop-SmokeChildren {
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.ProcessName -like "ScanBackup*" -or $_.ProcessName -eq "flet") -and
            $_.Id -notin $BaselineRuntimeProcessIds
        } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-HealthSmoke {
    $dir = New-SmokeDataDir "health"
    $output = python "scripts\product_hardening_check.py" health --data-dir $dir
    $payload = $output | ConvertFrom-Json
    Assert-True ([bool]$payload.ok) "Health check returned ok=false"
    Assert-True ([bool]$payload.checks.db_exists) "Health check did not create DB"
    Assert-True ([bool]$payload.checks.admin_default_password_valid) "Clean DB does not accept default admin password"
    Assert-True ([bool]$payload.checks.admin_must_change_password) "Clean DB does not require first-login password change"
    return @{
        name = "health"
        data_dir = $dir
        db_path = [string]$payload.checks.db_path
        log_file = [string]$payload.checks.log_file
    }
}

function Invoke-RecoverySmoke {
    $dir = New-SmokeDataDir "recovery"
    python "scripts\product_hardening_check.py" health --data-dir $dir | Out-Null
    $snapshot = (python "scripts\product_hardening_check.py" snapshot --data-dir $dir --label smoke).Trim()
    Assert-True (Test-Path $snapshot) "Snapshot file was not created: $snapshot"
    $restoreOutput = python "scripts\product_hardening_check.py" restore --data-dir $dir $snapshot
    $restore = $restoreOutput | ConvertFrom-Json
    Assert-True (Test-Path ([string]$restore.pre_restore)) "Pre-restore snapshot was not created"
    return @{
        name = "recovery"
        data_dir = $dir
        snapshot = $snapshot
        pre_restore = [string]$restore.pre_restore
    }
}

function Invoke-PipelineSmoke {
    $dir = New-SmokeDataDir "pipeline"
    $output = python "scripts\product_hardening_check.py" pipeline --data-dir $dir
    $payload = $output | ConvertFrom-Json
    Assert-True ([bool]$payload.ok) "Pipeline smoke returned ok=false"
    Assert-True (Test-Path ([string]$payload.backup_pdf)) "Pipeline smoke did not create backup PDF"
    Assert-True (($payload.check_ready | Select-Object -First 1) -eq $payload.record_key) "Pipeline smoke record is not check-ready"
    return @{
        name = "pipeline"
        data_dir = $dir
        record_key = [string]$payload.record_key
        backup_pdf = [string]$payload.backup_pdf
        processed = [int]$payload.counters.processed
    }
}

function Invoke-UiCompositionSmoke {
    $dir = New-SmokeDataDir "ui-compose"
    $output = python "scripts\product_hardening_check.py" ui-compose --data-dir $dir
    $payload = $output | ConvertFrom-Json
    Assert-True ([bool]$payload.ok) "UI composition smoke returned ok=false"
    Assert-True ([bool]$payload.first_run_requires_password_change) "UI smoke did not verify first-run password-change requirement"
    Assert-True ([bool]$payload.settings_snapshot_created) "UI smoke did not create a DB snapshot through the settings action"
    Assert-True (@($payload.screens).Count -ge 14) "UI smoke did not compose all required screens and project tabs"
    $settings = $payload.screens | Where-Object { $_.name -eq "settings-recovery" } | Select-Object -First 1
    Assert-True ($null -ne $settings) "UI smoke did not compose settings/recovery screen"
    Assert-True ([int]$settings.services -ge 1) "UI smoke did not attach DB restore FilePicker service"
    return @{
        name = "ui-compose"
        data_dir = $dir
        db_path = [string]$payload.db_path
        screens = @($payload.screens).Count
        first_run_requires_password_change = [bool]$payload.first_run_requires_password_change
        settings_snapshot_created = [bool]$payload.settings_snapshot_created
    }
}

function Invoke-ManifestSmoke {
    $manifestPath = Join-Path $RepoRoot "dist\release-manifest.json"
    if (-not (Test-Path $manifestPath)) {
        throw "Missing release manifest: $manifestPath. Run scripts\write_release_manifest.ps1 after build."
    }
    $manifest = Get-Content -Path $manifestPath -Raw | ConvertFrom-Json
    foreach ($artifact in $manifest.artifacts) {
        $path = Join-Path $RepoRoot ([string]$artifact.path)
        Assert-True (Test-Path $path) "Manifest artifact missing: $($artifact.path)"
        $item = Get-Item $path
        Assert-True ($item.Length -eq [int64]$artifact.bytes) "Manifest size mismatch: $($artifact.path)"
        $hash = (Get-FileHash -Algorithm SHA256 -Path $path).Hash.ToLowerInvariant()
        Assert-True ($hash -eq [string]$artifact.sha256) "Manifest hash mismatch: $($artifact.path)"
    }
    return @{
        name = "release-manifest"
        path = $manifestPath
        artifacts = @($manifest.artifacts).Count
    }
}

function Invoke-ProcessSmoke(
    [string]$Name,
    [string]$FilePath,
    [string]$Arguments,
    [int]$WaitSeconds,
    [bool]$ExpectServiceLog
) {
    $dir = New-SmokeDataDir $Name
    $env:SCAN_BACKUP_DATA_DIR = $dir
    $startInfo = @{
        FilePath = $FilePath
        WorkingDirectory = $RepoRoot
        PassThru = $true
        WindowStyle = "Hidden"
    }
    if ($Arguments) {
        $startInfo.ArgumentList = $Arguments
    }
    $process = Start-Process @startInfo
    Start-Sleep -Seconds $WaitSeconds
    $alive = -not $process.HasExited
    $exitCode = if ($process.HasExited) { $process.ExitCode } else { $null }
    if ($alive) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    Stop-SmokeChildren
    $dbPath = Join-Path $dir "scan_backup_manager.sqlite3"
    $logPath = Join-Path $dir "logs\app.log"
    Assert-True $alive "$Name exited before $WaitSeconds seconds (exit=$exitCode)"
    Assert-True (Test-Path $dbPath) "$Name did not create runtime DB"
    Assert-True (Test-Path $logPath) "$Name did not create app log"
    if ($ExpectServiceLog) {
        $logText = Get-Content -Path $logPath -Raw
        Assert-True ($logText -like "*Backup service started*") "$Name log does not show service start"
    }
    return @{
        name = $Name
        data_dir = $dir
        db_created = $true
        log_created = $true
        alive_after_seconds = $WaitSeconds
    }
}

try {
    Set-Location $RepoRoot
    $results = New-Object System.Collections.Generic.List[object]
    $results.Add((Invoke-HealthSmoke)) | Out-Null
    $results.Add((Invoke-RecoverySmoke)) | Out-Null
    $results.Add((Invoke-PipelineSmoke)) | Out-Null
    $results.Add((Invoke-UiCompositionSmoke)) | Out-Null
    $results.Add((Invoke-ProcessSmoke "source-app" "python" "main.py" $AppWaitSeconds $false)) | Out-Null
    $results.Add((Invoke-ProcessSmoke "source-service" "python" "service_main.py console" $ServiceWaitSeconds $true)) | Out-Null

    if (-not $SkipExe) {
        $managerExe = Join-Path $RepoRoot "dist\ScanBackupManager.exe"
        $serviceExe = Join-Path $RepoRoot "dist\ScanBackupService.exe"
        $installerExe = Join-Path $RepoRoot "packaging\Output\ScanBackupManager-Setup.exe"
        Assert-True (Test-Path $managerExe) "Missing $managerExe. Run packaging\build.ps1 first."
        Assert-True (Test-Path $serviceExe) "Missing $serviceExe. Run packaging\build.ps1 first."
        Assert-True (Test-Path $installerExe) "Missing $installerExe. Run packaging\build.ps1 first."
        $results.Add((Invoke-ProcessSmoke "exe-app" $managerExe "" $AppWaitSeconds $false)) | Out-Null
        $results.Add((Invoke-ProcessSmoke "exe-service" $serviceExe "console" $ServiceWaitSeconds $true)) | Out-Null
        $results.Add(@{
            name = "installer-artifact"
            path = $installerExe
            bytes = (Get-Item $installerExe).Length
        }) | Out-Null
        $results.Add((Invoke-ManifestSmoke)) | Out-Null
        if ($IncludeAdminService) {
            $adminOutput = powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\service_admin_smoke.ps1" -ServiceExe $serviceExe 2>&1
            try {
                $adminResult = $adminOutput | ConvertFrom-Json
            } catch {
                throw "Admin service smoke did not return JSON: $adminOutput"
            }
            if ([bool]$adminResult.skipped_admin_required) {
                throw "Admin service smoke was requested but this PowerShell session is not elevated."
            }
            if (-not [bool]$adminResult.ok) {
                throw "Admin service smoke failed: $($adminResult.error) $($adminResult.detail)"
            }
            $results.Add(($adminResult | Add-Member -NotePropertyName name -NotePropertyValue "admin-service" -PassThru)) | Out-Null
        }
    }

    $report = [pscustomobject]@{
        ok = $true
        generated_at = (Get-Date).ToString("s")
        results = $results
    }
    $json = $report | ConvertTo-Json -Depth 6
    if ($OutputPath) {
        $resolvedOutput = Join-Path $RepoRoot $OutputPath
        New-Item -ItemType Directory -Path (Split-Path -Parent $resolvedOutput) -Force | Out-Null
        $json | Set-Content -Path $resolvedOutput -Encoding UTF8
    }
    $json
} finally {
    Remove-Item Env:\SCAN_BACKUP_DATA_DIR -ErrorAction SilentlyContinue
    Stop-SmokeChildren
    Set-Location $PreviousLocation
    if (-not $KeepTemp) {
        Start-Sleep -Seconds 2
        foreach ($dir in $TempRoots) {
            Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
