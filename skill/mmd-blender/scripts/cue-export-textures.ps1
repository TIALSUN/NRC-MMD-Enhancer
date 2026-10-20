param(
    [string]$PlanJson,
    [string]$StageDir,
    [string]$ReportPath,
    [string]$ParserBundle,
    [string]$FModelSettings,
    [string]$DetexPath
)
# Decode textures straight out of the game paks and write them as PNG into a staging tree.
Add-Type -TypeDefinition @"
using System;using System.IO;using System.Reflection;using System.Runtime.Loader;
public static class CueTexLoader {public static Assembly Load(string path){string dir=Path.GetDirectoryName(path);AssemblyLoadContext.Default.Resolving+=(ctx,name)=>{string file=Path.Combine(dir,name.Name+".dll");return File.Exists(file)?ctx.LoadFromAssemblyPath(file):null;};return AssemblyLoadContext.Default.LoadFromAssemblyPath(path);}}
"@
if (-not $ParserBundle) { $ParserBundle = $env:CUE4PARSE_BUNDLE }
if (-not $ParserBundle -or -not (Test-Path (Join-Path $ParserBundle 'CUE4Parse.dll'))) { throw 'Pass -ParserBundle or set CUE4PARSE_BUNDLE' }
$bundle = (Resolve-Path -LiteralPath $ParserBundle).Path
$core = [CueTexLoader]::Load((Join-Path $bundle 'CUE4Parse.dll'))
$conv = [CueTexLoader]::Load((Join-Path $bundle 'CUE4Parse-Conversion.dll'))

if (-not $FModelSettings) { $FModelSettings = Join-Path $env:APPDATA 'FModel/AppSettings.json' }
$config = Get-Content -LiteralPath $FModelSettings -Raw | ConvertFrom-Json -AsHashtable
$key = ($env:NRC_AES -replace '^0x', '')
if (-not $key) { $key = ($config['PerDirectory'].Values | ForEach-Object { $_.AesKeys.mainKey } | Select-Object -First 1) -replace '^0x','' }
if (-not $key) { throw 'No authorized AES key in NRC_AES or FModel settings' }
$gameType = $core.GetType('CUE4Parse.UE4.Versions.EGame')
$game = [Enum]::Parse($gameType, 'GAME_RocoKingdomWorld')
$vcType = $core.GetType('CUE4Parse.UE4.Versions.VersionContainer')
$vcCtor = $vcType.GetConstructors() | Sort-Object { $_.GetParameters().Count } | Select-Object -First 1
$vcArgs = @()
foreach ($parameter in $vcCtor.GetParameters()) {
    if ($parameter.ParameterType -eq $gameType) { $vcArgs += $game }
    elseif ($parameter.ParameterType.IsEnum) { $vcArgs += [Enum]::ToObject($parameter.ParameterType, 0) }
    elseif ($parameter.ParameterType -eq [string]) { $vcArgs += '' }
    else { $vcArgs += $null }
}
$providerType = $core.GetType('CUE4Parse.FileProvider.DefaultFileProvider')
$provider = [Activator]::CreateInstance($providerType, @($config['GameDirectory'], [System.IO.SearchOption]::AllDirectories, $true, $vcCtor.Invoke($vcArgs)))
$provider.Initialize()
$aesKeyType = $core.GetType('CUE4Parse.Encryption.Aes.FAesKey')
$guidType = $core.GetType('CUE4Parse.UE4.Objects.Core.Misc.FGuid')
$pairType = [System.Collections.Generic.KeyValuePair`2].MakeGenericType($guidType, $aesKeyType)
$pair = [Activator]::CreateInstance($pairType, @(
    [Activator]::CreateInstance($guidType, @([uint32]0, [uint32]0, [uint32]0, [uint32]0)),
    [Activator]::CreateInstance($aesKeyType, @($key))))
$listType = [System.Collections.Generic.List`1].MakeGenericType($pairType)
$pairs = [Activator]::CreateInstance($listType)
$pairs.Add($pair)
$provider.SubmitKeys($pairs) | Out-Null
$provider.Mount() | Out-Null
Write-Output ("mounted " + $provider.MountedVfs.Count + " unloaded " + $provider.UnloadedVfs.Count)

$ipackageType = $core.GetType('CUE4Parse.UE4.Assets.IPackage')
$getExports = $ipackageType.GetMethods() | Where-Object { $_.Name -eq 'GetExports' -and $_.GetParameters().Count -eq 0 } | Select-Object -First 1
$utextureType = $core.GetType('CUE4Parse.UE4.Assets.Exports.Texture.UTexture')
$platformType = $core.GetType('CUE4Parse.UE4.Assets.Exports.Texture.ETexturePlatform')
$decoderType = $conv.GetType('CUE4Parse_Conversion.Textures.TextureDecoder')
$encoderType = $conv.GetType('CUE4Parse_Conversion.Textures.TextureEncoder')
$formatType = $conv.GetType('CUE4Parse_Conversion.Options.ETextureFormat')
$detexHelper = $conv.GetType('CUE4Parse_Conversion.Textures.BC.DetexHelper')
$platform = [Enum]::ToObject($platformType, 0)
$pngFormat = [Enum]::ToObject($formatType, 0)
$decodeMethod = $decoderType.GetMethods() | Where-Object { $_.Name -eq 'Decode' -and $_.GetParameters().Count -eq 2 } | Select-Object -First 1
$encodeMethod = $encoderType.GetMethods() | Where-Object { $_.Name -eq 'Encode' -and $_.GetParameters().Count -eq 5 } | Select-Object -First 1
$detexPath = $DetexPath
if (-not $detexPath) { $detexPath = $env:DETEX_DLL }
if (-not $detexPath) {
    $candidate = Get-ChildItem -LiteralPath (Join-Path (Split-Path -Parent $FModelSettings) '') -Recurse -File -Filter 'Detex.dll' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($candidate) { $detexPath = $candidate.FullName }
}
if (-not (Test-Path $detexPath)) { throw "Detex native library not found at $detexPath" }
$initDetex = $detexHelper.GetMethods() | Where-Object { $_.Name -eq 'Initialize' -and $_.GetParameters()[0].ParameterType -eq [string] } | Select-Object -First 1
$initDetex.Invoke($null, [object[]]@([string]$detexPath))
Write-Output 'detex native library initialised'

$plan = Get-Content $PlanJson -Raw | ConvertFrom-Json
if (-not (Test-Path $StageDir)) { New-Item -ItemType Directory -Path $StageDir -Force | Out-Null }
$report = New-Object System.Collections.ArrayList

foreach ($row in $plan.textures) {
    $asset = $row.asset -replace '\.uasset$', ''
    $entry = [ordered]@{ asset = $asset; dest = $row.dest; ok = $false; bytes = 0; error = $null }
    try {
        $package = $provider.LoadPackage($asset + '.uasset')
        $exports = @($getExports.Invoke($package, $null))
        $texture = $exports | Where-Object { $utextureType.IsInstanceOfType($_) } | Select-Object -First 1
        if (-not $texture) { throw 'no texture export' }
        $textureArg = [System.Management.Automation.LanguagePrimitives]::ConvertTo($texture, $utextureType)
        $platformArg = [System.Management.Automation.LanguagePrimitives]::ConvertTo($platform, $platformType)
        $bitmap = $decodeMethod.Invoke($null, [object[]]@($textureArg, $platformArg))
        $bitmapType = $conv.GetType('CUE4Parse_Conversion.Textures.CTexture')
        $bitmapArg = [System.Management.Automation.LanguagePrimitives]::ConvertTo($bitmap, $bitmapType)
        $formatArg = [System.Management.Automation.LanguagePrimitives]::ConvertTo($pngFormat, $formatType)
        $encodeArgs = [object[]]@($bitmapArg, $formatArg, $false, $null, 100)
        $data = $encodeMethod.Invoke($null, $encodeArgs)
        if (-not $data -or $data.Length -eq 0) { throw 'encoder returned no data' }
        $target = Join-Path $StageDir $row.dest
        New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
        [System.IO.File]::WriteAllBytes($target, $data)
        $entry.ok = $true
        $entry.bytes = $data.Length
    } catch {
        $entry.error = $_.Exception.Message
        if ($_.Exception.InnerException) { $entry.error += ' / ' + $_.Exception.InnerException.Message }
    }
    [void]$report.Add($entry)
}

$report | ConvertTo-Json -Depth 5 | Set-Content -Path $ReportPath -Encoding UTF8
$ok = @($report | Where-Object { $_.ok })
Write-Output ('textures exported: ' + $ok.Count + ' / ' + $report.Count)
foreach ($entry in $report) {
    if (-not $entry.ok) { Write-Output ('  FAIL ' + $entry.dest + ' -> ' + $entry.error) }
}
