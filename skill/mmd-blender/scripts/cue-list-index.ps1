param(
    [string]$Pattern,
    [string]$OutFile,
    [string]$ParserBundle,
    [string]$FModelSettings
)
# Dump every index entry matching a regex (case-insensitive) from the mounted game index.
Add-Type -TypeDefinition @"
using System;using System.IO;using System.Reflection;using System.Runtime.Loader;
public static class CueIndexLoader {public static Assembly Load(string path){string dir=Path.GetDirectoryName(path);AssemblyLoadContext.Default.Resolving+=(ctx,name)=>{string file=Path.Combine(dir,name.Name+".dll");return File.Exists(file)?ctx.LoadFromAssemblyPath(file):null;};return AssemblyLoadContext.Default.LoadFromAssemblyPath(path);}}
"@
if (-not $ParserBundle) { $ParserBundle = $env:CUE4PARSE_BUNDLE }
if (-not $ParserBundle -or -not (Test-Path (Join-Path $ParserBundle 'CUE4Parse.dll'))) { throw 'Pass -ParserBundle or set CUE4PARSE_BUNDLE' }
$bundle = (Resolve-Path -LiteralPath $ParserBundle).Path
$core = [CueIndexLoader]::Load((Join-Path $bundle 'CUE4Parse.dll'))
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

$filesProp = $null; $t = $providerType
while ($t -and -not $filesProp) { $filesProp = $t.GetProperty('Files'); $t = $t.BaseType }
$files = $filesProp.GetValue($provider)

$regex = [regex]$Pattern
$hits = New-Object System.Collections.ArrayList
foreach ($name in $files.Keys) { if ($regex.IsMatch($name)) { [void]$hits.Add($name) } }
$sorted = $hits | Sort-Object
Write-Output ('mounted=' + $provider.MountedVfs.Count + ' unloaded=' + $provider.UnloadedVfs.Count + ' entries=' + $files.Count + ' hits=' + $sorted.Count)
if ($OutFile) { $sorted | Set-Content -Path $OutFile -Encoding UTF8 }
$sorted | Select-Object -First 200 | ForEach-Object { Write-Output ('  ' + $_) }
