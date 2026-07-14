param(
    [string]$OutputPath = "dist\release-manifest.json",
    [switch]$RequireSigned
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Output = Join-Path $RepoRoot $OutputPath
$OutputDir = Split-Path -Parent $Output
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$appVersion = (& python -c "import pathlib, tomllib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])").Trim()
if ($LASTEXITCODE -ne 0 -or -not $appVersion) {
    throw "Could not read project.version from pyproject.toml"
}
$gitCommit = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $gitCommit) {
    throw "Could not resolve the Git commit for this release"
}
$gitBranch = (& git branch --show-current).Trim()
$gitDirty = @(& git status --porcelain --untracked-files=no).Count -gt 0

$artifactPaths = @(
    "dist\ScanBackupManager.exe",
    "dist\ScanBackupService.exe",
    "packaging\Output\ScanBackupManager-Setup.exe"
)

$artifacts = foreach ($relative in $artifactPaths) {
    $path = Join-Path $RepoRoot $relative
    if (-not (Test-Path $path)) {
        throw "Missing release artifact: $relative"
    }
    $item = Get-Item $path
    $hash = Get-FileHash -Algorithm SHA256 -Path $path
    $signature = Get-AuthenticodeSignature -FilePath $path
    [pscustomobject]@{
        path = $relative
        bytes = $item.Length
        sha256 = $hash.Hash.ToLowerInvariant()
        last_write_time = $item.LastWriteTime.ToString("s")
        file_version = [string]$item.VersionInfo.FileVersion
        product_version = ([string]$item.VersionInfo.ProductVersion).Trim()
        file_description = ([string]$item.VersionInfo.FileDescription).Trim()
        authenticode_status = [string]$signature.Status
        signer_subject = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Subject } else { "" }
    }
}

$wrongVersion = @($artifacts | Where-Object { -not $_.product_version.StartsWith($appVersion) })
if ($wrongVersion.Count -gt 0) {
    $details = ($wrongVersion | ForEach-Object { "$($_.path)=$($_.product_version)" }) -join ", "
    throw "Artifact product version does not match $appVersion`: $details"
}

if ($RequireSigned) {
    $unsigned = @($artifacts | Where-Object { $_.authenticode_status -ne "Valid" })
    if ($unsigned.Count -gt 0) {
        $names = ($unsigned | ForEach-Object { "$($_.path)=$($_.authenticode_status)" }) -join ", "
        throw "Unsigned or invalid Authenticode artifact(s): $names"
    }
}

$manifest = [pscustomobject]@{
    generated_at = (Get-Date).ToString("s")
    repository = (Split-Path -Leaf $RepoRoot)
    version = $appVersion
    git_commit = $gitCommit
    git_branch = $gitBranch
    git_dirty = $gitDirty
    require_signed = [bool]$RequireSigned
    artifacts = $artifacts
}

$manifest | ConvertTo-Json -Depth 5 | Set-Content -Path $Output -Encoding UTF8
Write-Output $Output
