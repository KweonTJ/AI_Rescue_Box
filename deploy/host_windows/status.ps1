param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000
)

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PidFile = Join-Path $RepoRoot "data\runtime\host.pid"
$WebIndex = Join-Path $RepoRoot "src\host\flutter_app\build\web\index.html"
$Running = $false
$PidValue = $null
if (Test-Path $PidFile) {
    try {
        $PidValue = [int](Get-Content $PidFile -Raw).Trim()
        $Running = $null -ne (Get-Process -Id $PidValue -ErrorAction SilentlyContinue)
    } catch { $Running = $false }
}

$ApiState = "STOPPED"
$WebState = if (Test-Path $WebIndex) { "BUILT" } else { "MISSING" }
$UwbState = "UNKNOWN"
if ($Running) {
    $ApiHost = if ($BindHost -in @("0.0.0.0", "::")) { "127.0.0.1" } else { $BindHost }
    try {
        $Response = Invoke-RestMethod -Uri "http://${ApiHost}:$Port/api/v1/status" -TimeoutSec 3
        $ApiState = "READY"
        $UwbState = [string]$Response.bridge.state
    } catch {
        $ApiState = "STARTING/UNREACHABLE"
        $UwbState = "UNKNOWN"
    }
}

if ((Test-Path $WebIndex) -and $ApiState -eq "READY") { $WebState = "READY" }

Write-Host ("Host Process   {0}{1}" -f $(if ($Running) { "RUNNING" } else { "STOPPED" }), $(if ($PidValue) { " (PID $PidValue)" } else { "" }))
Write-Host "Host API       $ApiState"
Write-Host "Host Web       $WebState"
Write-Host "Host UWB       $UwbState"
if (-not $Running -and (Test-Path $PidFile)) { Write-Host "Note: stale PID file exists; stop.ps1 will remove it." }
