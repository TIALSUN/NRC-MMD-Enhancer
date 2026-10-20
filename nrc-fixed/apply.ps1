param(
    [string]$BaseAsar,
    [string]$OutputAsar,
    [string]$StageDir,
    [string]$InstallRoot,
    [switch]$Install
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not $BaseAsar) {
    $candidate = Get-ChildItem -LiteralPath 'E:\' -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'NRC*' } | Select-Object -First 1
    if ($candidate) { $BaseAsar = Join-Path $candidate.FullName 'resources/app.asar' }
}
if (-not $BaseAsar -or -not (Test-Path -LiteralPath $BaseAsar)) {
    throw 'NRC base app.asar not found. Pass -BaseAsar.'
}
$BaseAsar = (Resolve-Path -LiteralPath $BaseAsar).Path
if (-not $OutputAsar) {
    $OutputAsar = Join-Path $root 'out/NRC-mmd-fixed.asar'
}
$OutputAsar = [System.IO.Path]::GetFullPath($OutputAsar)
if (-not $StageDir) {
    $StageDir = Join-Path ([System.IO.Path]::GetTempPath()) ('nrc-code-patch-' + [guid]::NewGuid().ToString('N'))
}
$StageDir = [System.IO.Path]::GetFullPath($StageDir)
$report = Join-Path $root 'out/patch-report.json'
New-Item -ItemType Directory -Path (Split-Path -Parent $OutputAsar) -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $report) -Force | Out-Null
$node = (Get-Command node -ErrorAction Stop).Source
& $node (Join-Path $root 'patch.mjs') $BaseAsar $OutputAsar $StageDir (Join-Path $root 'app-overlay') $report
if ($LASTEXITCODE -ne 0) { throw 'NRC code patch failed' }

if ($Install) {
    if (-not $InstallRoot) {
        $InstallRoot = Split-Path -Parent (Split-Path -Parent $BaseAsar)
    }
    $InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
    $target = Join-Path $InstallRoot 'resources/app.asar'
    if ((Get-FileHash -LiteralPath $target).Hash -ne (Get-FileHash -LiteralPath $BaseAsar).Hash) {
        throw 'Installed app.asar changed after the patch started'
    }
    $backup = Join-Path $InstallRoot ('resources/app.asar.before-code-only-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    Copy-Item -LiteralPath $target -Destination $backup
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { try { $_.Path -and $_.Path.StartsWith($InstallRoot + '\', [StringComparison]::OrdinalIgnoreCase) } catch { $false } } |
        Stop-Process -Force
    Copy-Item -LiteralPath $OutputAsar -Destination $target -Force
    if ((Get-FileHash -LiteralPath $target).Hash -ne (Get-FileHash -LiteralPath $OutputAsar).Hash) {
        throw 'Installed ASAR hash mismatch'
    }
    $exe = Get-ChildItem -LiteralPath $InstallRoot -File -Filter '*.exe' |
        Where-Object { $_.Name -like '*NRC*' } | Select-Object -First 1
    if ($exe) { Start-Process -FilePath $exe.FullName -WorkingDirectory $InstallRoot -WindowStyle Hidden }
    Write-Output "Installed. Backup: $backup"
}
