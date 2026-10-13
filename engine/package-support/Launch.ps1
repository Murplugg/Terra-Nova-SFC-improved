param([switch]$Demo,[switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$pilotRoot = [IO.Path]::GetFullPath($PSScriptRoot)
if ($pilotRoot -match '[^\x20-\x7E]') { throw 'This pilot requires an ASCII folder path.' }
$manifest = Get-Content -LiteralPath (Join-Path $pilotRoot 'portable.json') -Raw | ConvertFrom-Json
$template = Join-Path $pilotRoot 'native-template.bin'
if ((Get-FileHash -LiteralPath $template -Algorithm SHA256).Hash -ne $manifest.template_sha256) { throw 'The native template does not match the manifest.' }
foreach ($entry in $manifest.assets.psobject.Properties) {
    $asset = Join-Path $pilotRoot $entry.Name
    if (!(Test-Path -LiteralPath $asset) -or (Get-FileHash -LiteralPath $asset -Algorithm SHA256).Hash -ne $entry.Value) { throw "Missing or changed asset: $($entry.Name)" }
}
$bytes = [IO.File]::ReadAllBytes($template)
foreach ($entry in $manifest.relocations) {
    $value = [Text.Encoding]::ASCII.GetBytes($entry.value.Replace('{ROOT}', $pilotRoot))
    if ($value.Length -ge $entry.capacity) { throw 'The folder path is too long for this pilot. Move it nearer the drive root.' }
    [Array]::Clear($bytes, [int]$entry.offset, [int]$entry.capacity)
    [Array]::Copy($value, 0, $bytes, [int]$entry.offset, $value.Length)
}
$exe = Join-Path $pilotRoot 'native-startup.exe'
$running = @(Get-CimInstance Win32_Process -Filter "Name='native-startup.exe'" | Where-Object { $_.ExecutablePath -eq $exe })
if ($running.Count -gt 0) { throw 'This copy is already running.' }
[IO.File]::WriteAllBytes($exe, $bytes)
if ($CheckOnly) { Write-Output 'Portable files and paths verified.'; return }
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = $exe
$start.WorkingDirectory = $pilotRoot
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
if ($Demo) { $start.Arguments = '--demo' }
[void][Diagnostics.Process]::Start($start)
