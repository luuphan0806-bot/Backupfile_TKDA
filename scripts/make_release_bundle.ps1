param(
    [string]$OutputDir = "dist\release"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ResolvedOutputDir = Join-Path $RepoRoot $OutputDir
New-Item -ItemType Directory -Path $ResolvedOutputDir -Force | Out-Null

$manifestPath = Join-Path $RepoRoot "dist\release-manifest.json"
$smokeReportPath = Join-Path $RepoRoot "dist\release-smoke-report.json"
if (-not (Test-Path $manifestPath)) {
    throw "Missing dist\release-manifest.json. Run scripts\write_release_manifest.ps1 first."
}
if (-not (Test-Path $smokeReportPath)) {
    throw "Missing dist\release-smoke-report.json. Run scripts\release_smoke.ps1 first."
}

$smokeReport = Get-Content -Path $smokeReportPath -Raw | ConvertFrom-Json
if (-not [bool]$smokeReport.ok) {
    throw "release-smoke-report.json has ok=false. Do not bundle this release."
}
$releaseManifest = Get-Content -Path $manifestPath -Raw | ConvertFrom-Json

$requiredFiles = @(
    "dist\ScanBackupManager.exe",
    "dist\ScanBackupService.exe",
    "packaging\Output\ScanBackupManager-Setup.exe",
    "dist\release-manifest.json",
    "dist\release-smoke-report.json",
    "dist\product-readiness-report.json",
    "scripts\product_hardening_check.py",
    "scripts\product_readiness_audit.ps1",
    "scripts\release_smoke.ps1",
    "scripts\service_admin_smoke.ps1",
    "scripts\sign_release_artifacts.ps1",
    "scripts\write_release_manifest.ps1",
    "scripts\make_release_bundle.ps1",
    "scripts\verify_release_bundle.ps1",
    "README.md",
    "VAN_HANH_PRODUCT.md",
    "HUONG_DAN_BAT_DAU_DU_AN_MOI.md",
    "HUONG_DAN_CHAM_CONG_LEADER.md"
)

foreach ($relative in $requiredFiles) {
    $path = Join-Path $RepoRoot $relative
    if (-not (Test-Path $path)) {
        throw "Missing release bundle file: $relative"
    }
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$zipPath = Join-Path $ResolvedOutputDir "ScanBackupManager-release-$timestamp.zip"
$stagingDir = Join-Path $env:TEMP ("sbm-release-bundle-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stagingDir | Out-Null

try {
    foreach ($relative in $requiredFiles) {
        $source = Join-Path $RepoRoot $relative
        $target = Join-Path $stagingDir $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
    Compress-Archive -Path (Join-Path $stagingDir "*") -DestinationPath $zipPath -Force
    $hash = Get-FileHash -Algorithm SHA256 -Path $zipPath
    $bundleManifest = [pscustomobject]@{
        generated_at = (Get-Date).ToString("s")
        bundle = (Split-Path -Leaf $zipPath)
        version = [string]$releaseManifest.version
        git_commit = [string]$releaseManifest.git_commit
        bytes = (Get-Item $zipPath).Length
        sha256 = $hash.Hash.ToLowerInvariant()
        included_files = $requiredFiles
    }
    $bundleManifestPath = [System.IO.Path]::ChangeExtension($zipPath, ".json")
    $bundleManifest | ConvertTo-Json -Depth 5 | Set-Content -Path $bundleManifestPath -Encoding UTF8
    [pscustomobject]@{
        ok = $true
        zip = $zipPath
        manifest = $bundleManifestPath
        bytes = (Get-Item $zipPath).Length
        sha256 = $hash.Hash.ToLowerInvariant()
    } | ConvertTo-Json -Depth 4
} finally {
    Remove-Item -LiteralPath $stagingDir -Recurse -Force -ErrorAction SilentlyContinue
}
