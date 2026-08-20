param(
    [string]$VenvPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$HostPackage = Join-Path $RepoRoot "src\host\host_app"
$UwbPackage = Join-Path $RepoRoot "src\uwb\protocol"
if ([string]::IsNullOrWhiteSpace($VenvPath)) {
    $VenvPath = Join-Path $RepoRoot ".venv-host"
}

function Find-PythonLauncher {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $VersionText = (& py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim()
            if ($LASTEXITCODE -eq 0 -and [version]$VersionText -ge [version]"3.10") {
                return @("py", "-3")
            }
        } catch {}
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        try {
            $VersionText = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim()
            if ($LASTEXITCODE -eq 0 -and [version]$VersionText -ge [version]"3.10") {
                return @("python")
            }
        } catch {}
    }
    throw "Python 3.10+ was not found. Install a current 64-bit Python 3 release and rerun setup.ps1 (or install.ps1 for manual setup)."
}

$Launcher = Find-PythonLauncher
if (-not (Test-Path $VenvPath)) {
    $Command = $Launcher[0]
    $Arguments = @()
    if ($Launcher.Count -gt 1) { $Arguments += $Launcher[1..($Launcher.Count - 1)] }
    $Arguments += @("-m", "venv", $VenvPath)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python virtual environment creation failed." }
}

$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    throw "Host virtualenv Python was not created: $PythonExe"
}

$VersionText = (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
$Version = [version]$VersionText
if ($Version -lt [version]"3.10") {
    throw "Python 3.10+ is required; virtualenv uses $VersionText."
}

& $PythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $PythonExe -m pip install -e "${UwbPackage}[serial]" -e $HostPackage
if ($LASTEXITCODE -ne 0) { throw "Host/UWB dependency installation failed." }

@(
    (Join-Path $RepoRoot "data\host"),
    (Join-Path $RepoRoot "data\logs"),
    (Join-Path $RepoRoot "data\runtime"),
    (Join-Path $RepoRoot "data\uwb_spool\host")
) | ForEach-Object { New-Item -ItemType Directory -Force -Path $_ | Out-Null }

$Config = Join-Path $RepoRoot "src\host\config\host.env"
$Example = Join-Path $RepoRoot "src\host\config\host.env.example"
if (-not (Test-Path $Config)) {
    Write-Host "Machine config is not created automatically by manual install.ps1."
    Write-Host "Use setup.ps1 for the normal first-time flow, or copy and edit manually:"
    Write-Host "  Copy-Item '$Example' '$Config'"
}

Write-Host "Host Python runtime is ready: $PythonExe"
Write-Host "Flutter SDK was not checked; it is needed only for build_web.ps1."
Write-Host "Normal first-time setup: .\deploy\host_windows\setup.ps1"
