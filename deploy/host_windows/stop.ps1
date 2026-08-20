$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$RuntimeRoot = Join-Path $RepoRoot "data\runtime"
$PidFile = Join-Path $RuntimeRoot "host.pid"
$StopFile = Join-Path $RuntimeRoot "host.stop"
if (-not (Test-Path $PidFile)) {
    Remove-Item $StopFile -Force -ErrorAction SilentlyContinue
    Write-Host "Host runtime is not running (PID file absent)."
    exit 0
}
$PidValue = [int](Get-Content $PidFile -Raw).Trim()
$Process = Get-Process -Id $PidValue -ErrorAction SilentlyContinue
if ($Process) {
    New-Item -ItemType File -Force -Path $StopFile | Out-Null
    $ExitedCleanly = $false
    for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
        Start-Sleep -Milliseconds 250
        $Process.Refresh()
        if ($Process.HasExited) { $ExitedCleanly = $true; break }
    }
    if ($ExitedCleanly) {
        Write-Host "Host runtime stopped cleanly (PID $PidValue)."
    } else {
        Stop-Process -Id $PidValue -Force -ErrorAction SilentlyContinue
        try { $null = $Process.WaitForExit(5000) } catch {}
        Write-Host "Host runtime exceeded the shutdown deadline and was terminated (PID $PidValue)."
    }
} else {
    Write-Host "Removed stale Host PID file (PID $PidValue was not running)."
}
Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Remove-Item $StopFile -Force -ErrorAction SilentlyContinue
