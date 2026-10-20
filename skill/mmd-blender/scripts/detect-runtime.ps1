param(
    [string]$GameDirectory,
    [string]$FModelSettings,
    [string]$ParserBundle,
    [string]$DetexPath,
    [string]$Blender,
    [string]$NrcInstallRoot,
    [string]$NrcConfig,
    [string]$OutFile
)
$ErrorActionPreference = 'Stop'
function Existing([string]$Path) { if ($Path -and (Test-Path -LiteralPath $Path)) { (Resolve-Path -LiteralPath $Path).Path } }
function FirstExisting([string[]]$Paths) { foreach ($path in $Paths) { $found = Existing $path; if ($found) { return $found } }; $null }
function Find-File([string[]]$Roots, [string]$Filter) {
    foreach ($root in $Roots) {
        if (-not $root -or -not (Test-Path -LiteralPath $root)) { continue }
        $hit = Get-ChildItem -LiteralPath $root -Recurse -File -Filter $Filter -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    $null
}

if (-not $FModelSettings) {
    $FModelSettings = FirstExisting @(
        (Join-Path $env:APPDATA 'FModel/AppSettings.json'),
        (Join-Path $env:LOCALAPPDATA 'FModel/AppSettings.json')
    )
}
$settings = $null
if ($FModelSettings) { $settings = Get-Content -LiteralPath $FModelSettings -Raw | ConvertFrom-Json -AsHashtable }
if (-not $GameDirectory -and $settings) { $GameDirectory = $settings['GameDirectory'] }
if (-not $GameDirectory) {
    $GameDirectory = FirstExisting @(
        'E:\洛克王国：世界(2002304)',
        'E:\洛克王国世界',
        'D:\洛克王国：世界'
    )
}

$parserRoots = @(
    (Join-Path $env:LOCALAPPDATA 'FModel'),
    (Join-Path $env:APPDATA 'FModel'),
    'E:\FModel',
    (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)
if (-not $ParserBundle) { $ParserBundle = $env:CUE4PARSE_BUNDLE }
$core = if ($ParserBundle) { Existing (Join-Path $ParserBundle 'CUE4Parse.dll') } else { Find-File $parserRoots 'CUE4Parse.dll' }
$detex = if ($DetexPath) { Existing $DetexPath } else { Find-File $parserRoots 'Detex.dll' }
$decoder = FirstExisting @(
    'E:\Roco-Kingdom-World-Data\Bin\decode_bin.py',
    (Join-Path $PSScriptRoot 'decode_bin.py')
)
if (-not $Blender) { $Blender = $env:MMD_BLENDER }
$blender = if ($Blender) {
    Existing $Blender
} else {
    FirstExisting @(
        'D:\Blender_\blender.exe',
        'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
    )
}

if (-not $NrcInstallRoot) {
    $candidate = Get-ChildItem -LiteralPath 'E:\' -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'NRC*' } | Select-Object -First 1
    if ($candidate) { $NrcInstallRoot = $candidate.FullName }
}
$nrcAsar = if ($NrcInstallRoot) { Existing (Join-Path $NrcInstallRoot 'resources/app.asar') }
if (-not $NrcConfig) { $NrcConfig = Existing (Join-Path $env:APPDATA 'nrc-closet-viewer/config.json') }
$nrcConfigData = if ($NrcConfig) { Get-Content -LiteralPath $NrcConfig -Raw | ConvertFrom-Json } else { $null }

$result = [ordered]@{
    found_at = (Get-Date).ToString('o')
    game_directory = (Existing $GameDirectory)
    fmodel_settings = (Existing $FModelSettings)
    cue4parse_dll = $core
    cue4parse_bundle = if ($core) { Split-Path -Parent $core } else { $null }
    detex_dll = $detex
    decoder_python = $decoder
    blender = $blender
    nrc_install_root = (Existing $NrcInstallRoot)
    nrc_app_asar = $nrcAsar
    nrc_config = (Existing $NrcConfig)
    nrc_roots = if ($nrcConfigData) {
        [ordered]@{
            dataRoot = $nrcConfigData.dataRoot
            modelRoot = $nrcConfigData.modelRoot
            mmdMorphRoot = $nrcConfigData.mmdMorphRoot
            mmdOutDir = $nrcConfigData.mmdOutDir
            mmdBlender = $nrcConfigData.mmdBlender
        }
    } else { $null }
    aes_environment_present = [bool]$env:NRC_AES
    missing = @()
}
foreach ($name in @('game_directory', 'cue4parse_bundle', 'blender', 'nrc_app_asar')) {
    if (-not $result[$name]) { $result.missing += $name }
}
$json = $result | ConvertTo-Json -Depth 6
if ($OutFile) {
    $parent = Split-Path -Parent $OutFile
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    Set-Content -LiteralPath $OutFile -Value $json -Encoding utf8
}
$json
if ($result.missing.Count) { exit 2 }
