param(
    [string]$CertificateThumbprint = "",
    [string]$PfxPath = "",
    [securestring]$PfxPassword,
    [string]$TimestampServer = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$artifactPaths = @(
    "dist\ScanBackupManager.exe",
    "dist\ScanBackupService.exe",
    "packaging\Output\ScanBackupManager-Setup.exe"
)

if ($CertificateThumbprint -and $PfxPath) {
    throw "Use either -CertificateThumbprint or -PfxPath, not both."
}
if (-not $CertificateThumbprint -and -not $PfxPath) {
    throw "Provide a code-signing certificate via -CertificateThumbprint or -PfxPath."
}

$certificate = $null
if ($CertificateThumbprint) {
    $certificate = Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My |
        Where-Object { $_.Thumbprint -replace "\s", "" -eq ($CertificateThumbprint -replace "\s", "") } |
        Select-Object -First 1
    if (-not $certificate) {
        throw "Certificate thumbprint was not found in CurrentUser\My or LocalMachine\My: $CertificateThumbprint"
    }
} elseif ($PfxPath) {
    if (-not (Test-Path $PfxPath)) {
        throw "PFX file was not found: $PfxPath"
    }
    if (-not $PfxPassword) {
        $PfxPassword = Read-Host "PFX password" -AsSecureString
    }
    $imported = Import-PfxCertificate -FilePath $PfxPath -CertStoreLocation Cert:\CurrentUser\My -Password $PfxPassword
    $certificate = $imported | Select-Object -First 1
    if (-not $certificate) {
        throw "PFX import did not return a certificate."
    }
}

$signed = foreach ($relative in $artifactPaths) {
    $path = Join-Path $RepoRoot $relative
    if (-not (Test-Path $path)) {
        throw "Missing release artifact: $relative"
    }

    $result = Set-AuthenticodeSignature -FilePath $path -Certificate $certificate -TimestampServer $TimestampServer

    if ($result.Status -ne "Valid") {
        throw "Signing failed for $relative with status $($result.Status): $($result.StatusMessage)"
    }
    [pscustomobject]@{
        path = $relative
        status = [string]$result.Status
        signer_subject = [string]$result.SignerCertificate.Subject
    }
}

[pscustomobject]@{
    ok = $true
    timestamp_server = $TimestampServer
    artifacts = $signed
} | ConvertTo-Json -Depth 4
