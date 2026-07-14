param(
    [Parameter(Mandatory = $true)]
    [string]$BundlePath,
    [switch]$RequireSigned
)

$ErrorActionPreference = "Stop"
$Bundle = Resolve-Path $BundlePath
$BundleManifest = [System.IO.Path]::ChangeExtension($Bundle, ".json")
if (-not (Test-Path $BundleManifest)) {
    throw "Missing bundle manifest next to ZIP: $BundleManifest"
}

$manifest = Get-Content -Path $BundleManifest -Raw | ConvertFrom-Json
$bundleItem = Get-Item $Bundle
if ($bundleItem.Length -ne [int64]$manifest.bytes) {
    throw "Bundle size mismatch. Expected $($manifest.bytes), got $($bundleItem.Length)."
}
$hash = (Get-FileHash -Algorithm SHA256 -Path $Bundle).Hash.ToLowerInvariant()
if ($hash -ne [string]$manifest.sha256) {
    throw "Bundle SHA256 mismatch. Expected $($manifest.sha256), got $hash."
}

$extractDir = Join-Path $env:TEMP ("sbm-verify-bundle-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $extractDir | Out-Null

try {
    Expand-Archive -Path $Bundle -DestinationPath $extractDir -Force
    foreach ($relative in $manifest.included_files) {
        $path = Join-Path $extractDir ([string]$relative)
        if (-not (Test-Path $path)) {
            throw "Bundle is missing required file: $relative"
        }
    }

    $smokeReportPath = Join-Path $extractDir "dist\release-smoke-report.json"
    $smokeReport = Get-Content -Path $smokeReportPath -Raw | ConvertFrom-Json
    if (-not [bool]$smokeReport.ok) {
        throw "Bundled release-smoke-report.json has ok=false."
    }

    $artifactManifestPath = Join-Path $extractDir "dist\release-manifest.json"
    $artifactManifest = Get-Content -Path $artifactManifestPath -Raw | ConvertFrom-Json
    foreach ($artifact in $artifactManifest.artifacts) {
        $artifactPath = Join-Path $extractDir ([string]$artifact.path)
        if (-not (Test-Path $artifactPath)) {
            throw "Bundle is missing manifest artifact: $($artifact.path)"
        }
        $artifactItem = Get-Item $artifactPath
        if ($artifactItem.Length -ne [int64]$artifact.bytes) {
            throw "Bundled artifact size mismatch: $($artifact.path)"
        }
        $artifactHash = (Get-FileHash -Algorithm SHA256 -Path $artifactPath).Hash.ToLowerInvariant()
        if ($artifactHash -ne [string]$artifact.sha256) {
            throw "Bundled artifact hash mismatch: $($artifact.path)"
        }
        if ($RequireSigned -and [string]$artifact.authenticode_status -ne "Valid") {
            throw "Bundled artifact is not Authenticode-signed and valid: $($artifact.path) status=$($artifact.authenticode_status)"
        }
    }

    [pscustomobject]@{
        ok = $true
        bundle = [string]$Bundle
        bytes = $bundleItem.Length
        sha256 = $hash
        require_signed = [bool]$RequireSigned
        verified_files = @($manifest.included_files).Count
        verified_artifacts = @($artifactManifest.artifacts).Count
    } | ConvertTo-Json -Depth 4
} finally {
    Remove-Item -LiteralPath $extractDir -Recurse -Force -ErrorAction SilentlyContinue
}
