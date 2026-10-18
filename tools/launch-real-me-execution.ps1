param(
    [string]$ImagePath = (Join-Path $PSScriptRoot '..\working-copies\Lenovo T460 NM-A581.bin'),
    [string]$TracePath = (Join-Path $PSScriptRoot '..\qemu-work\traces\real-me-execution.jsonl'),
    [int]$DelayMs = 120,
    [switch]$AllowEmulationAuthBypass
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonCandidates = @(
    'C:\msys64\ucrt64\bin\python.exe',
    'C:\msys64\mingw64\bin\python.exe',
    'python.exe'
)
$python = $pythonCandidates | Where-Object {
    if ($_ -eq 'python.exe') { $true } else { Test-Path -LiteralPath $_ }
} | Select-Object -First 1

if (-not $python) {
    throw 'Python was not found. Install/use the MSYS2 UCRT64 Python environment.'
}

$image = (Resolve-Path -LiteralPath $ImagePath).Path
$trace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $TracePath))
$runner = (Resolve-Path (Join-Path $PSScriptRoot 'real_image_boot_console.py')).Path
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $TracePath) | Out-Null

$arguments = @(
    "`"$runner`""
    "`"$image`""
    '--trace'
    "`"$trace`""
    '--delay-ms'
    "$DelayMs"
)

if ($AllowEmulationAuthBypass) {
    $arguments += '--allow-emulation-auth-bypass'
}

Start-Process -FilePath $python `
    -WorkingDirectory $projectRoot `
    -ArgumentList $arguments `
    -NoNewWindow:$false `
    -Wait

