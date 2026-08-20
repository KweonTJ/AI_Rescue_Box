param(
    [string]$BindHost = "",
    [int]$Port = 0,
    [string]$UwbPort = "",
    [int]$UwbBaud = 0,
    [switch]$UwbAutoDiscover,
    [switch]$EnableRosBridge,
    [switch]$Offline,
    [switch]$NoBrowser,
    [string]$VenvPath = "",
    [string]$EnvFile = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if ([string]::IsNullOrWhiteSpace($VenvPath)) { $VenvPath = Join-Path $RepoRoot ".venv-host" }
if ([string]::IsNullOrWhiteSpace($EnvFile)) { $EnvFile = Join-Path $RepoRoot "src\host\config\host.env" }

function Import-EnvFile([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $Line = $_.Trim()
        if (-not $Line -or $Line.StartsWith("#") -or -not $Line.Contains("=")) { return }
        $Parts = $Line.Split("=", 2)
        [Environment]::SetEnvironmentVariable($Parts[0].Trim(), $Parts[1].Trim(), "Process")
    }
}

function Quote-Argument([string]$Value) {
    return '"' + ($Value -replace '"', '\"') + '"'
}

Import-EnvFile $EnvFile
if ([string]::IsNullOrWhiteSpace($BindHost)) { $BindHost = if ($env:AI_RESCUE_API_HOST) { $env:AI_RESCUE_API_HOST } else { "127.0.0.1" } }
if ($Port -eq 0) { $Port = if ($env:AI_RESCUE_API_PORT) { [int]$env:AI_RESCUE_API_PORT } else { 8000 } }
if ([string]::IsNullOrWhiteSpace($UwbPort)) {
    if ($env:AI_RESCUE_UWB_SERIAL_PORT) { $UwbPort = $env:AI_RESCUE_UWB_SERIAL_PORT }
    elseif ($env:AI_RESCUE_UWB_PORT) { $UwbPort = $env:AI_RESCUE_UWB_PORT }
}
if ($UwbBaud -eq 0) {
    if ($env:AI_RESCUE_UWB_BAUD) { $UwbBaud = [int]$env:AI_RESCUE_UWB_BAUD }
    elseif ($env:AI_RESCUE_UWB_BAUDRATE) { $UwbBaud = [int]$env:AI_RESCUE_UWB_BAUDRATE }
    else { $UwbBaud = 460800 }
}
if ($EnableRosBridge -and $Offline) { throw "-EnableRosBridge and -Offline cannot be used together." }
if ($Port -lt 1 -or $Port -gt 65535) { throw "Port must be between 1 and 65535." }
if ($UwbBaud -lt 1) { throw "UwbBaud must be positive." }

$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$WebRoot = Join-Path $RepoRoot "src\host\flutter_app\build\web"
$DataRoot = Join-Path $RepoRoot "data\host"
$LogRoot = Join-Path $RepoRoot "data\logs"
$RuntimeRoot = Join-Path $RepoRoot "data\runtime"
$SpoolRoot = Join-Path $RepoRoot "data\uwb_spool\host"
$PidFile = Join-Path $RuntimeRoot "host.pid"
$StopFile = Join-Path $RuntimeRoot "host.stop"
@($DataRoot, $LogRoot, $RuntimeRoot, $SpoolRoot) | ForEach-Object { New-Item -ItemType Directory -Force -Path $_ | Out-Null }

if (-not (Test-Path $PythonExe)) { throw "Host virtualenv is missing. Run install.ps1 first." }
if (-not (Test-Path (Join-Path $WebRoot "index.html"))) { throw "Host Web release is missing. Run build_web.ps1 first." }
if (Test-Path $PidFile) {
    $ExistingPid = [int](Get-Content $PidFile -Raw).Trim()
    if (Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue) {
        throw "Host runtime is already running (PID $ExistingPid)."
    }
    Remove-Item $PidFile -Force
}
Remove-Item $StopFile -Force -ErrorAction SilentlyContinue

$BridgeMode = "serial"
if ($EnableRosBridge) { $BridgeMode = "ros" }
elseif ($Offline) { $BridgeMode = "offline" }
$Arguments = @(
    "-m", "host_app.api",
    "--host", $BindHost,
    "--port", $Port.ToString(),
    "--data-dir", (Quote-Argument $DataRoot),
    "--web-root", (Quote-Argument $WebRoot),
    "--log-dir", (Quote-Argument $LogRoot),
    "--shutdown-file", (Quote-Argument $StopFile),
    "--bridge-mode", $BridgeMode,
    "--uwb-baud", $UwbBaud.ToString(),
    "--uwb-spool", (Quote-Argument $SpoolRoot)
)
if (-not [string]::IsNullOrWhiteSpace($UwbPort)) { $Arguments += @("--uwb-port", (Quote-Argument $UwbPort)) }
if ($UwbAutoDiscover) { $Arguments += "--uwb-auto-discover" }

$Stdout = Join-Path $LogRoot "host.stdout.log"
$Stderr = Join-Path $LogRoot "host.stderr.log"
$Process = Start-Process -FilePath $PythonExe -ArgumentList $Arguments -WorkingDirectory $RepoRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
$Process.Id | Set-Content -Path $PidFile -Encoding ascii
$BrowserHost = if ($BindHost -in @("0.0.0.0", "::")) { "127.0.0.1" } else { $BindHost }
$Url = "http://${BrowserHost}:$Port/"
$ApiReady = $false
for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
    Start-Sleep -Milliseconds 250
    $Process.Refresh()
    if ($Process.HasExited) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        $Tail = if (Test-Path $Stderr) { (Get-Content $Stderr -Tail 30) -join [Environment]::NewLine } else { "No stderr log." }
        throw "Host runtime exited during startup.`n$Tail"
    }
    try {
        $null = Invoke-RestMethod -Uri "${Url}api/v1/health" -TimeoutSec 1
        $ApiReady = $true
        break
    } catch {}
}
if (-not $ApiReady) {
    New-Item -ItemType File -Force -Path $StopFile | Out-Null
    Start-Sleep -Seconds 1
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    Remove-Item $StopFile -Force -ErrorAction SilentlyContinue
    $Tail = if (Test-Path $Stderr) { (Get-Content $Stderr -Tail 30) -join [Environment]::NewLine } else { "No stderr log." }
    throw "Host API did not become ready within 10 seconds.`n$Tail"
}
Write-Host "Host API/Web started PID=$($Process.Id) URL=$Url"
Write-Host "Host UWB mode=$BridgeMode port=$(if ($UwbPort) { $UwbPort } else { '<unconfigured>' }) baud=$UwbBaud"
Write-Host "A missing ESP32 is reported as DISCONNECTED; Host local features remain available."
Write-Host "Logs: $LogRoot"
if (-not $NoBrowser) { Start-Process $Url }
