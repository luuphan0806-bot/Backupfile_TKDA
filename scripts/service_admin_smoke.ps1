param(
    [string]$ServiceExe = "",
    [string]$DataDir = "",
    [int]$WaitSeconds = 25,
    [switch]$KeepInstalled
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $ServiceExe) {
    $ServiceExe = Join-Path $RepoRoot "dist\ScanBackupService.exe"
}

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal] $identity
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-ServiceExe([string]$Arguments) {
    $process = Start-Process -FilePath $ServiceExe -ArgumentList $Arguments -WorkingDirectory $RepoRoot -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "ScanBackupService.exe $Arguments failed with exit code $($process.ExitCode)"
    }
}

function Get-ScanBackupService {
    $service = Get-Service -Name "ScanBackupService" -ErrorAction SilentlyContinue
    return $service
}

function Set-ServiceSmokeEnvironment([string]$ResolvedDataDir) {
    $serviceKey = "HKLM:\SYSTEM\CurrentControlSet\Services\ScanBackupService"
    if (-not (Test-Path $serviceKey)) {
        throw "Service registry key was not created: $serviceKey"
    }
    New-Item -ItemType Directory -Path $ResolvedDataDir -Force | Out-Null
    New-ItemProperty `
        -Path $serviceKey `
        -Name "Environment" `
        -PropertyType MultiString `
        -Value @("SCAN_BACKUP_DATA_DIR=$ResolvedDataDir") `
        -Force | Out-Null
}

function Wait-ServiceRuntimeEvidence([string]$ResolvedDataDir, [int]$TimeoutSeconds) {
    $dbPath = Join-Path $ResolvedDataDir "scan_backup_manager.sqlite3"
    $logPath = Join-Path $ResolvedDataDir "logs\app.log"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $dbExists = Test-Path $dbPath
        $logExists = Test-Path $logPath
        $logStarted = $false
        if ($logExists) {
            $logStarted = ((Get-Content -Path $logPath -Raw -ErrorAction SilentlyContinue) -like "*Backup service started*")
        }
        if ($dbExists -and $logStarted) {
            return @{
                db_path = $dbPath
                log_path = $logPath
            }
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)

    throw "Service did not create runtime DB/log evidence in $ResolvedDataDir within $TimeoutSeconds seconds."
}

function Get-ServiceDiagnostics([string]$ResolvedDataDir) {
    $serviceKey = "HKLM:\SYSTEM\CurrentControlSet\Services\ScanBackupService"
    $registry = $null
    if (Test-Path $serviceKey) {
        $props = Get-ItemProperty -Path $serviceKey
        $registry = [pscustomobject]@{
            image_path = [string]$props.ImagePath
            environment = @($props.Environment)
            object_name = [string]$props.ObjectName
        }
    }

    $systemEvents = @()
    try {
        $systemEvents = Get-WinEvent -FilterHashtable @{
            LogName = "System"
            ProviderName = "Service Control Manager"
            StartTime = (Get-Date).AddMinutes(-10)
        } -ErrorAction Stop |
            Where-Object { $_.Message -like "*ScanBackupService*" -or $_.Message -like "*Scan Backup Manager*" } |
            Select-Object -First 8 TimeCreated, Id, LevelDisplayName, Message
    } catch {
        $systemEvents = @([pscustomobject]@{ error = ($_.Exception.Message) })
    }

    $appEvents = @()
    try {
        $appEvents = Get-WinEvent -FilterHashtable @{
            LogName = "Application"
            StartTime = (Get-Date).AddMinutes(-10)
        } -ErrorAction Stop |
            Where-Object { $_.Message -like "*ScanBackup*" -or $_.Message -like "*scan_backup_manager*" -or $_.Message -like "*Python*" } |
            Select-Object -First 8 TimeCreated, ProviderName, Id, LevelDisplayName, Message
    } catch {
        $appEvents = @([pscustomobject]@{ error = ($_.Exception.Message) })
    }

    $logPath = Join-Path $ResolvedDataDir "logs\app.log"
    $logTail = ""
    if (Test-Path $logPath) {
        $logTail = ((Get-Content -Path $logPath -Tail 80 -ErrorAction SilentlyContinue) -join "`n")
    }

    [pscustomobject]@{
        service_registry = $registry
        system_events = @($systemEvents)
        application_events = @($appEvents)
        data_dir_exists = (Test-Path $ResolvedDataDir)
        db_exists = (Test-Path (Join-Path $ResolvedDataDir "scan_backup_manager.sqlite3"))
        log_path = $logPath
        log_tail = $logTail
    }
}

if (-not (Test-Path $ServiceExe)) {
    throw "Missing service EXE: $ServiceExe. Run packaging\build.ps1 first."
}

if (-not (Test-IsAdmin)) {
    [pscustomobject]@{
        ok = $true
        skipped_admin_required = $true
        service_exe = $ServiceExe
        message = "Run this script from an elevated PowerShell session to test Windows Service install/start/stop/remove."
    } | ConvertTo-Json -Depth 4
    exit 0
}

$existing = Get-ScanBackupService
if ($existing) {
    [pscustomobject]@{
        ok = $true
        skipped_existing_service = $true
        service_name = "ScanBackupService"
        status = [string]$existing.Status
        message = "Existing service was left untouched. Stop/remove it explicitly before running this smoke."
    } | ConvertTo-Json -Depth 4
    exit 0
}

$CreatedTempDataDir = $false
if (-not $DataDir) {
    $DataDir = Join-Path $env:TEMP ("sbm-admin-service-" + [guid]::NewGuid().ToString("N"))
    $CreatedTempDataDir = $true
}
$ResolvedDataDir = [System.IO.Path]::GetFullPath($DataDir)

$installed = $false
$started = $false
$stopped = $false
$removed = $false
$runtimeEvidence = $null
$cleanupErrors = New-Object System.Collections.Generic.List[string]
$caughtError = $null
$caughtDetail = ""
$diagnostics = $null
try {
    Invoke-ServiceExe "--startup manual install"
    $installed = $true
    Set-ServiceSmokeEnvironment $ResolvedDataDir
    $service = Get-ScanBackupService
    if (-not $service) {
        throw "Service was not visible after install."
    }

    Start-Service -Name "ScanBackupService"
    $service.WaitForStatus("Running", [TimeSpan]::FromSeconds(20))
    $running = Get-Service -Name "ScanBackupService"
    if ($running.Status -ne "Running") {
        throw "Service did not reach Running state."
    }
    $started = $true
    $runtimeEvidence = Wait-ServiceRuntimeEvidence $ResolvedDataDir $WaitSeconds

    Stop-Service -Name "ScanBackupService"
    $running.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(20))
    $stopped = Get-Service -Name "ScanBackupService"
    if ($stopped.Status -ne "Stopped") {
        throw "Service did not stop cleanly."
    }
    $stopped = $true
} catch {
    $caughtError = $_.Exception.Message
    $caughtDetail = ($_ | Out-String).Trim()
    $diagnostics = Get-ServiceDiagnostics $ResolvedDataDir
} finally {
    if ($installed -and -not $KeepInstalled) {
        try {
            Invoke-ServiceExe "remove"
            $removed = $true
        } catch {
            $cleanupErrors.Add(($_ | Out-String).Trim()) | Out-Null
        }
    }
    if ($CreatedTempDataDir -and -not $KeepInstalled) {
        Remove-Item -LiteralPath $ResolvedDataDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not $caughtError -and $cleanupErrors.Count -gt 0) {
    $caughtError = "Service runtime passed, but cleanup failed."
    $caughtDetail = ($cleanupErrors -join "`n")
}

if ($caughtError) {
    [pscustomobject]@{
        ok = $false
        skipped_admin_required = $false
        installed = $installed
        started = $started
        stopped = $stopped
        removed = $removed
        service_exe = $ServiceExe
        data_dir = $ResolvedDataDir
        error = $caughtError
        detail = $caughtDetail
        diagnostics = $diagnostics
        cleanup_errors = @($cleanupErrors)
    } | ConvertTo-Json -Depth 8
    exit 1
}

[pscustomobject]@{
    ok = $true
    skipped_admin_required = $false
    installed = $installed
    started = $started
    stopped = $stopped
    removed = $removed
    service_exe = $ServiceExe
    data_dir = $ResolvedDataDir
    db_path = [string]$runtimeEvidence.db_path
    log_path = [string]$runtimeEvidence.log_path
    cleanup_errors = @($cleanupErrors)
} | ConvertTo-Json -Depth 4
