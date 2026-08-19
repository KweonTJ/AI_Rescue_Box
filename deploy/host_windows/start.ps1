param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$EnableRosBridge,
    [switch]$NoBrowser,
    [string]$VenvPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$HostRoot = Join-Path $RepoRoot "src\host"
$WebRoot = Join-Path $HostRoot "flutter_app\build\web"
if ([string]::IsNullOrWhiteSpace($VenvPath)) {
    $VenvPath = Join-Path $RepoRoot ".venv-host"
}
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    throw "Host virtualenv is missing. Run .\deploy\host_windows\install.ps1 first."
}
if (-not (Test-Path (Join-Path $WebRoot "index.html"))) {
    throw "Host Web build is missing. Run .\deploy\host_windows\build_web.ps1 first."
}
if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535."
}

$BridgeMode = if ($EnableRosBridge) { "ros" } else { "offline" }
$DataRoot = Join-Path $RepoRoot "data\host"
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null

$Arguments = @(
    "-m", "host_app.api",
    "--host", $BindHost,
    "--port", $Port.ToString(),
    "--data-dir", $DataRoot,
    "--web-root", $WebRoot,
    "--bridge-mode", $BridgeMode
)

Write-Host "Starting Host Backend/Web at http://${BindHost}:$Port/"
Write-Host "UWB bridge mode: $BridgeMode"
$Process = Start-Process -FilePath $PythonExe -ArgumentList $Arguments -WorkingDirectory $RepoRoot -PassThru -NoNewWindow

Start-Sleep -Seconds 1
if (-not $NoBrowser) {
    Start-Process "http://${BindHost}:$Port/"
}

Write-Host "Host process PID: $($Process.Id)"
Write-Host "Press Ctrl+C to stop waiting; stop the PID above to terminate the backend."
Wait-Process -Id $Process.Id
