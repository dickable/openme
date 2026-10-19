param(
    [string]$Python = 'C:\msys64\ucrt64\bin\python.exe',
    [string]$Qemu = '',
    [switch]$Test,
    [switch]$InPlace
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw 'Python not found. Pass -Python with your Python executable.'
}
if (-not $Test -and -not $InPlace) {
    $windowArguments = @('-NoProfile', '-NoExit', '-File', "`"$PSCommandPath`"",
                         '-InPlace', '-Python', "`"$Python`"")
    if ($Qemu) { $windowArguments += @('-Qemu', "`"$Qemu`"") }
    Start-Process -FilePath 'powershell.exe' -WorkingDirectory $projectRoot `
        -ArgumentList $windowArguments -WindowStyle Normal
    return
}
Push-Location $projectRoot
try {
    & $Python (Join-Path $PSScriptRoot 'build_openme.py')
    if ($LASTEXITCODE -ne 0) { throw "OpenME build failed ($LASTEXITCODE)." }
    $runnerArguments = @((Join-Path $PSScriptRoot 'run_openme_qemu.py'))
    if ($Qemu) { $runnerArguments += @('--qemu', $Qemu) }
    if (-not $Test) { $runnerArguments += '--interactive' }
    & $Python @runnerArguments
    if ($LASTEXITCODE -ne 0) { throw "OpenME QEMU run failed ($LASTEXITCODE)." }
} finally {
    Pop-Location
}
