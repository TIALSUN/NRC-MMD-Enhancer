param(
    [string[]]$Targets,
    [string]$TargetFile,
    [string]$OutDir,
    [string]$ReportPath,
    [string]$ParserBundle,
    [string]$FModelSettings
)
if ($TargetFile) { $Targets = @(Get-Content $TargetFile -Encoding UTF8 | Where-Object { $_.Trim() -ne '' }) }
# Headless glTF export of skeletal meshes straight from the game paks via CUE4Parse.
Add-Type -TypeDefinition @"
using System;using System.IO;using System.Reflection;using System.Runtime.Loader;
public static class CueExportLoader {public static Assembly Load(string path){string dir=Path.GetDirectoryName(path);AssemblyLoadContext.Default.Resolving+=(ctx,name)=>{string file=Path.Combine(dir,name.Name+".dll");return File.Exists(file)?ctx.LoadFromAssemblyPath(file):null;};return AssemblyLoadContext.Default.LoadFromAssemblyPath(path);}}
"@
if (-not $ParserBundle) { $ParserBundle = $env:CUE4PARSE_BUNDLE }
if (-not $ParserBundle -or -not (Test-Path (Join-Path $ParserBundle 'CUE4Parse.dll'))) { throw 'Pass -ParserBundle or set CUE4PARSE_BUNDLE' }
$bundle = (Resolve-Path -LiteralPath $ParserBundle).Path
$core = [CueExportLoader]::Load((Join-Path $bundle 'CUE4Parse.dll'))
$conv = [CueExportLoader]::Load((Join-Path $bundle 'CUE4Parse-Conversion.dll'))

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

$optionsType = $conv.GetType('CUE4Parse_Conversion.Options.ExportOptions')
$optionsCtor = $optionsType.GetConstructors()[0]
$paramNames = ($optionsCtor.GetParameters() | ForEach-Object { $_.Name })
$paramTypes = ($optionsCtor.GetParameters() | ForEach-Object { $_.ParameterType })
$paramIndex = -1
$optionsArgs = @()
foreach ($pt in $paramTypes) {
    $paramIndex++
    $pn = $paramNames[$paramIndex]
    if ($pt.IsEnum) {
        # EMeshFormat.Gltf2=1, ETextureFormat.Png=0, EMeshQuality.All=2, ESocketFormat.Bone=1, rest 0
        $value = 0
        if ($pt.Name -eq 'EMeshFormat') { $value = 1 }
        elseif ($pt.Name -eq 'EMeshQuality') { $value = 2 }
        elseif ($pt.Name -eq 'ESocketFormat') { $value = 1 }
        elseif ($pt.Name -eq 'ENaniteMeshFormat') { $value = 1 }
        $optionsArgs += [Enum]::ToObject($pt, $value)
    } elseif ($pt -eq [int]) { $optionsArgs += 0 }
    elseif ($pt -eq [bool]) {
        # exportMorphTargets 必须显式打开，否则 glTF 里不会写 morph target
        $optionsArgs += ($pn -eq 'exportMorphTargets')
    }
    else { $optionsArgs += $null }
}
$options = $optionsCtor.Invoke($optionsArgs)
$highestArgs = @($optionsArgs)
for ($i = 0; $i -lt $paramTypes.Count; $i++) {
    if ($paramTypes[$i].Name -eq 'EMeshQuality') {
        $highestArgs[$i] = [Enum]::ToObject($paramTypes[$i], 0)
    }
}
$highestOptions = $optionsCtor.Invoke($highestArgs)

$sessionType = $conv.GetType('CUE4Parse_Conversion.ExportSession')
$meshType = $core.GetType('CUE4Parse.UE4.Assets.Exports.SkeletalMesh.USkeletalMesh')
$skinnedType = $core.GetType('CUE4Parse.UE4.Assets.Exports.Engine.USkinnedAsset')
$ipackageType = $core.GetType('CUE4Parse.UE4.Assets.IPackage')
$getExportsMethod = $ipackageType.GetMethods() | Where-Object { $_.Name -eq 'GetExports' -and $_.GetParameters().Count -eq 0 } | Select-Object -First 1
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

$report = New-Object System.Collections.ArrayList
foreach ($target in $Targets) {
    $clean = $target -replace '\.uasset$', ''
    $entry = [ordered]@{ target = $clean; loaded = $false; exports = @(); meshClass = $null; ok = $false; files = @(); morphLodFallback = $false; error = $null }
    $package = $null
    foreach ($attempt in @(
        @{ kind = 'full'; args = @($clean + '.uasset') },
        @{ kind = 'spl-ext'; args = @($clean, 'uasset', [System.StringComparison]::OrdinalIgnoreCase) }
    )) {
        try { $package = $provider.LoadPackage.Invoke($attempt.args); if ($package) { $entry.loaded = $true; break } }
        catch { $entry.error = $attempt.kind + ': ' + $_.Exception.Message }
    }
    if (-not $package) { [void]$report.Add($entry); continue }

    $exportObjects = @()
    try { $exportObjects = @($getExportsMethod.Invoke($package, $null)) } catch { $entry.error = 'GetExports: ' + $_.Exception.Message }
    $entry.exports = @($exportObjects | ForEach-Object { $_.GetType().Name + ':' + $_.Name })
    $mesh = $exportObjects | Where-Object { $skinnedType.IsInstanceOfType($_) -or $_.GetType().Name -eq 'USkeletalMesh' } | Select-Object -First 1
    if (-not $mesh) { $entry.error = 'no skeletal mesh export'; [void]$report.Add($entry); continue }
    $entry.meshClass = $mesh.GetType().FullName

    $session = [Activator]::CreateInstance($sessionType, @($null))
    $session.Clear()
    $session.Add($mesh) | Out-Null
    try {
        $task = $session.RunAsync($OutDir, $options, $null, [System.Threading.CancellationToken]::None)
        $results = $task.GetAwaiter().GetResult()
        $entry.files = @($results | ForEach-Object { @($_.DiskFilePaths) })
        $entry.ok = (@($results | Where-Object { $_.Success }).Count -gt 0)
        $failures = @($results | Where-Object { -not $_.Success })
        if ($failures.Count -gt 0) { $entry.error = 'export failures: ' + (@($failures | ForEach-Object { $_.Error.Message }) -join '; ') }
        # Some face meshes have morph indices that the all-LOD glTF writer
        # cannot remap at lower LODs. LOD0 keeps the full facial morph set.
        if (-not $entry.ok -and @($exportObjects | Where-Object { $_.GetType().Name -eq 'UMorphTarget' }).Count -gt 0 -and $entry.error -match 'Index was outside the bounds of the array') {
            $session.Clear()
            $session.Add($mesh) | Out-Null
            $retry = $session.RunAsync($OutDir, $highestOptions, $null, [System.Threading.CancellationToken]::None).GetAwaiter().GetResult()
            $entry.files = @($retry | ForEach-Object { @($_.DiskFilePaths) })
            $entry.ok = (@($retry | Where-Object { $_.Success }).Count -gt 0)
            if ($entry.ok) {
                $entry.morphLodFallback = $true
                $entry.error = $null
            } else {
                $entry.error += '; highest-LOD retry: ' + (@($retry | Where-Object { -not $_.Success } | ForEach-Object { $_.Error.Message }) -join '; ')
            }
        }
    } catch {
        $entry.error = 'RunAsync: ' + $_.Exception.Message
    }
    [void]$report.Add($entry)
}

$report | ConvertTo-Json -Depth 6 | Set-Content -Path $ReportPath -Encoding UTF8
foreach ($entry in $report) {
    Write-Output ('--- ' + $entry.target)
    Write-Output ('  loaded=' + $entry.loaded + ' mesh=' + $entry.meshClass + ' ok=' + $entry.ok)
    if ($entry.morphLodFallback) { Write-Output '  morphLodFallback=highest (lower LODs omitted)' }
    Write-Output ('  exports: ' + ($entry.exports -join ', '))
    foreach ($file in $entry.files) { Write-Output ('  file: ' + $file) }
    if ($entry.error) { Write-Output ('  error: ' + $entry.error) }
}

