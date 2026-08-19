param(
    [string]$VenvPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$HostRoot = Join-Path $RepoRoot "src\host"
if ([string]::IsNullOrWhiteSpace($VenvPath)) {
    $VenvPath = Join-Path $RepoRoot ".venv-host"
}

if (-not (Test-Path $VenvPath)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $VenvPath
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $VenvPath
    }
    else {
        throw "Python 3.10+ was not found. Install Python and rerun install.ps1."
    }
}

$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    throw "Host virtualenv Python was not created: $PythonExe"
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -e (Join-Path $HostRoot "host_app")

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    throw "Flutter was not found in PATH. Install Flutter, then rerun install.ps1."
}

Push-Location (Join-Path $HostRoot "flutter_app")
try {
    & flutter pub get
}
finally {
    Pop-Location
}

Write-Host "Host local dependencies are ready."
Write-Host "Next: .\deploy\host_windows\build_web.ps1"
