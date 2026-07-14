param(
    [string]$OutputPath = "dist\product-readiness-report.json",
    [switch]$RequireSigned,
    [switch]$RequireAdminService
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

function Add-Check(
    [System.Collections.Generic.List[object]]$Checks,
    [string]$Name,
    [bool]$Ok,
    [string]$Status,
    [string]$Detail = ""
) {
    $Checks.Add([pscustomobject]@{
        name = $Name
        ok = $Ok
        status = $Status
        detail = $Detail
    }) | Out-Null
}

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal] $identity
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$checks = New-Object System.Collections.Generic.List[object]
$warnings = New-Object System.Collections.Generic.List[string]

$manifestPath = Join-Path $RepoRoot "dist\release-manifest.json"
$smokePath = Join-Path $RepoRoot "dist\release-smoke-report.json"

if (Test-Path $manifestPath) {
    $manifest = Get-Content -Path $manifestPath -Raw | ConvertFrom-Json
    Add-Check $checks "release-manifest-present" $true "pass" $manifestPath
    foreach ($artifact in $manifest.artifacts) {
        $artifactPath = Join-Path $RepoRoot ([string]$artifact.path)
        $exists = Test-Path $artifactPath
        Add-Check $checks "artifact-present:$($artifact.path)" $exists ($(if ($exists) { "pass" } else { "fail" })) $artifactPath
        if ($exists) {
            $item = Get-Item $artifactPath
            $sizeOk = $item.Length -eq [int64]$artifact.bytes
            Add-Check $checks "artifact-size:$($artifact.path)" $sizeOk ($(if ($sizeOk) { "pass" } else { "fail" })) "expected=$($artifact.bytes); actual=$($item.Length)"
            $hash = (Get-FileHash -Algorithm SHA256 -Path $artifactPath).Hash.ToLowerInvariant()
            $hashOk = $hash -eq [string]$artifact.sha256
            Add-Check $checks "artifact-sha256:$($artifact.path)" $hashOk ($(if ($hashOk) { "pass" } else { "fail" })) "expected=$($artifact.sha256); actual=$hash"
            $signed = [string]$artifact.authenticode_status -eq "Valid"
            if ($signed) {
                Add-Check $checks "artifact-signed:$($artifact.path)" $true "pass" ([string]$artifact.signer_subject)
            } elseif ($RequireSigned) {
                Add-Check $checks "artifact-signed:$($artifact.path)" $false "fail" ([string]$artifact.authenticode_status)
            } else {
                Add-Check $checks "artifact-signed:$($artifact.path)" $true "warn" ([string]$artifact.authenticode_status)
                $warnings.Add("Artifact is not signed: $($artifact.path) status=$($artifact.authenticode_status)") | Out-Null
            }
        }
    }
} else {
    Add-Check $checks "release-manifest-present" $false "fail" $manifestPath
}

if (Test-Path $smokePath) {
    $smoke = Get-Content -Path $smokePath -Raw | ConvertFrom-Json
    Add-Check $checks "release-smoke-present" $true "pass" $smokePath
    Add-Check $checks "release-smoke-ok" ([bool]$smoke.ok) ($(if ([bool]$smoke.ok) { "pass" } else { "fail" })) ""
    $resultNames = @($smoke.results | ForEach-Object { [string]$_.name })
    foreach ($required in @("health", "recovery", "pipeline", "ui-compose", "source-app", "source-service", "exe-app", "exe-service", "installer-artifact", "release-manifest")) {
        $hasResult = $resultNames -contains $required
        Add-Check $checks "release-smoke-result:$required" $hasResult ($(if ($hasResult) { "pass" } else { "fail" })) ""
    }
    $ui = $smoke.results | Where-Object { $_.name -eq "ui-compose" } | Select-Object -First 1
    $uiOk = $null -ne $ui -and [bool]$ui.first_run_requires_password_change -and [bool]$ui.settings_snapshot_created -and [int]$ui.screens -ge 14
    Add-Check $checks "ui-first-run-and-recovery-smoke" $uiOk ($(if ($uiOk) { "pass" } else { "fail" })) ""

    $admin = $smoke.results | Where-Object { $_.name -eq "admin-service" } | Select-Object -First 1
    if ($RequireAdminService) {
        $adminOk = $null -ne $admin -and [bool]$admin.ok -and -not [bool]$admin.skipped_admin_required -and -not [bool]$admin.skipped_existing_service
        Add-Check $checks "admin-service-elevated-smoke" $adminOk ($(if ($adminOk) { "pass" } else { "fail" })) ""
    } else {
        $adminDetail = if ($admin) { ($admin | ConvertTo-Json -Compress -Depth 4) } else { "not requested" }
        Add-Check $checks "admin-service-elevated-smoke" $true "warn" $adminDetail
        $warnings.Add("Admin Windows Service install/start/stop/remove was not required for this audit.") | Out-Null
    }
} else {
    Add-Check $checks "release-smoke-present" $false "fail" $smokePath
}

$activeProcesses = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like "ScanBackup*" })
Add-Check $checks "no-leftover-runtime-processes" ($activeProcesses.Count -eq 0) ($(if ($activeProcesses.Count -eq 0) { "pass" } else { "fail" })) (($activeProcesses | Select-Object Id, ProcessName | ConvertTo-Json -Compress))

$isAdmin = Test-IsAdmin
if ($RequireAdminService) {
    Add-Check $checks "current-shell-is-admin" $isAdmin ($(if ($isAdmin) { "pass" } else { "fail" })) ""
} else {
    Add-Check $checks "current-shell-is-admin" $true "warn" ([string]$isAdmin)
}

$failed = @($checks | Where-Object { -not [bool]$_.ok })
$report = [pscustomobject]@{
    ok = ($failed.Count -eq 0)
    generated_at = (Get-Date).ToString("s")
    require_signed = [bool]$RequireSigned
    require_admin_service = [bool]$RequireAdminService
    failed = @($failed | ForEach-Object { $_.name })
    warnings = $warnings
    checks = $checks
}

$resolvedOutput = Join-Path $RepoRoot $OutputPath
New-Item -ItemType Directory -Path (Split-Path -Parent $resolvedOutput) -Force | Out-Null
$json = $report | ConvertTo-Json -Depth 8
$json | Set-Content -Path $resolvedOutput -Encoding UTF8
$json

if (-not $report.ok) {
    exit 1
}
