param(
    [string]$Manifest = (Join-Path $PSScriptRoot '../references/required-assets.json'),
    [string]$NrcRoot,
    [string]$OutFile
)
$ErrorActionPreference = 'Stop'
$manifestPath = (Resolve-Path -LiteralPath $Manifest).Path
$data = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$checks = @()
if ($NrcRoot) {
    $root = (Resolve-Path -LiteralPath $NrcRoot).Path
    foreach ($relative in $data.nrc_runtime_required) {
        $path = Join-Path $root $relative
        $checks += [ordered]@{
            path = $relative
            exists = [bool](Test-Path -LiteralPath $path)
            kind = if ((Test-Path -LiteralPath $path -PathType Container)) { 'directory' } else { 'file' }
        }
    }
}
$result = [ordered]@{
    manifest = $manifestPath
    runtime_root = if ($NrcRoot) { $root } else { $null }
    checked = $checks.Count
    missing = @($checks | Where-Object { -not $_.exists } | ForEach-Object path)
    checks = $checks
}
$json = $result | ConvertTo-Json -Depth 5
if ($OutFile) { Set-Content -LiteralPath $OutFile -Value $json -Encoding utf8 }
$json
if ($result.missing.Count) { exit 2 }
