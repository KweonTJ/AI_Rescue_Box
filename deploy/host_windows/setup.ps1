param(
    [string]$VenvPath = ""
)

$ErrorActionPreference = "Stop"
$CurrentStage = "initialization"
$RepoRoot = $null
$PythonExe = $null
$UwbStatus = "NOT CONFIGURED"

function Resolve-Python310Plus {
    $Candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $Candidates += ,@("py", "-3")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $Candidates += ,@("python")
    }

    foreach ($Candidate in $Candidates) {
        $Command = $Candidate[0]
        $Prefix = @()
        if ($Candidate.Count -gt 1) { $Prefix = $Candidate[1..($Candidate.Count - 1)] }
        try {
            $VersionText = (& $Command @Prefix -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim()
            if ($LASTEXITCODE -eq 0 -and [version]$VersionText -ge [version]"3.10") {
                return [pscustomobject]@{
                    Command = $Command
                    Prefix = $Prefix
                    Version = $VersionText
                }
            }
        } catch {}
    }
    return $null
}

function Get-EnvValue([string]$Path, [string]$Name) {
    if (-not (Test-Path $Path)) { return "" }
    $Prefix = "${Name}="
    foreach ($Line in Get-Content $Path) {
        $Trimmed = $Line.Trim()
        if ($Trimmed.StartsWith($Prefix)) {
            return $Trimmed.Substring($Prefix.Length).Trim()
        }
    }
    return ""
}

function Show-PythonInstallHelp {
    Write-Host "Python 3.10+ is required for the Windows Host runtime." -ForegroundColor Yellow
    Write-Host "Install a current 64-bit Python 3 release (3.10 or newer), then run setup.ps1 again."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "winget is available. You can search available Python packages with:"
        Write-Host "  winget search Python.Python"
    }
}

function Show-FlutterInstallHelp {
    Write-Host "Flutter stable SDK is required for the first Host Web release build." -ForegroundColor Yellow
    Write-Host "Install Flutter stable, make flutter\bin available in PATH for this PowerShell session, then run setup.ps1 again."
    Write-Host "After setup completes, start.ps1 does not require Flutter SDK."
}

try {
    $CurrentStage = "repository root"
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $RequiredPaths = @(
        (Join-Path $RepoRoot "src\host\host_app"),
        (Join-Path $RepoRoot "src\host\flutter_app"),
        (Join-Path $RepoRoot "src\host\config\host.env.example"),
        (Join-Path $PSScriptRoot "install.ps1"),
        (Join-Path $PSScriptRoot "build_web.ps1"),
        (Join-Path $PSScriptRoot "start.ps1")
    )
    foreach ($Path in $RequiredPaths) {
        if (-not (Test-Path $Path)) { throw "Required repository path is missing: $Path" }
    }
    if ([string]::IsNullOrWhiteSpace($VenvPath)) { $VenvPath = Join-Path $RepoRoot ".venv-host" }

    $CurrentStage = "PowerShell environment"
    if ($env:OS -ne "Windows_NT") {
        throw "setup.ps1 is intended for the Windows Host. Run it from Windows PowerShell or PowerShell on Windows."
    }
    if ($PSVersionTable.PSVersion -lt [version]"5.1") {
        throw "PowerShell 5.1 or newer is required. Current version: $($PSVersionTable.PSVersion)"
    }

    $CurrentStage = "Python prerequisite"
    $Python = Resolve-Python310Plus
    if ($null -eq $Python) {
        throw "Python 3.10+ was not found."
    }
    Write-Host "Python prerequisite: READY ($($Python.Version))"

    $CurrentStage = "Flutter prerequisite"
    if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
        throw "Flutter stable SDK was not found in PATH."
    }
    $FlutterVersionOutput = @(& flutter --version 2>&1)
    $FlutterExitCode = $LASTEXITCODE

    if ($FlutterExitCode -ne 0) {
        throw "Flutter command exists but could not run successfully."
    }

    $FlutterFirstLine = $FlutterVersionOutput | Select-Object -First 1
    Write-Host "Flutter prerequisite: READY ($FlutterFirstLine)"

    $CurrentStage = "Host Python install"
    & (Join-Path $PSScriptRoot "install.ps1") -VenvPath $VenvPath
    $PythonExe = Join-Path $VenvPath "Scripts\python.exe"
    if (-not (Test-Path $PythonExe)) { throw "Host virtualenv Python is missing after install: $PythonExe" }

    $CurrentStage = "Host config"
    $Config = Join-Path $RepoRoot "src\host\config\host.env"
    $Example = Join-Path $RepoRoot "src\host\config\host.env.example"
    if (-not (Test-Path $Config)) {
        Copy-Item $Example $Config
        Write-Host "Host config: CREATED from host.env.example"
    } else {
        Write-Host "Host config: READY (existing host.env preserved)"
    }

    $CurrentStage = "Host runtime directories"
    $RuntimeDirectories = @(
        (Join-Path $RepoRoot "data\host"),
        (Join-Path $RepoRoot "data\logs"),
        (Join-Path $RepoRoot "data\runtime"),
        (Join-Path $RepoRoot "data\uwb_spool\host")
    )
    foreach ($Directory in $RuntimeDirectories) {
        New-Item -ItemType Directory -Force -Path $Directory | Out-Null
        if (-not (Test-Path $Directory)) { throw "Runtime directory was not prepared: $Directory" }
    }

    $CurrentStage = "Flutter Web build"
    & (Join-Path $PSScriptRoot "build_web.ps1")
    $WebIndex = Join-Path $RepoRoot "src\host\flutter_app\build\web\index.html"
    if (-not (Test-Path $WebIndex)) { throw "Flutter Web index.html is missing after build: $WebIndex" }

    $CurrentStage = "Host Python sanity check"
    & $PythonExe -c "import host_app, ai_rescue_uwb_common, serial; print('Host/UWB Python imports: READY')"
    if ($LASTEXITCODE -ne 0) { throw "Host/UWB Python import sanity check failed." }

    $CurrentStage = "UWB configuration"
    $ConfiguredPort = Get-EnvValue $Config "AI_RESCUE_UWB_SERIAL_PORT"
    $SerialCandidates = @()
    try {
        $SerialCandidates = @(Get-CimInstance Win32_SerialPort -ErrorAction Stop | Where-Object { -not [string]::IsNullOrWhiteSpace($_.DeviceID) })
    } catch {
        Write-Host "Serial inventory could not be queried; UWB configuration will be determined from host.env only."
    }

    if ([string]::IsNullOrWhiteSpace($ConfiguredPort)) {
        $UwbStatus = "NOT CONFIGURED"
        if ($SerialCandidates.Count -eq 0) {
            Write-Host "UWB Serial: NOT CONFIGURED (no serial candidates detected; this does not block Host setup)"
        } elseif ($SerialCandidates.Count -eq 1) {
            $Candidate = $SerialCandidates[0]
            Write-Host "UWB Serial: NOT CONFIGURED"
            Write-Host "One generic serial candidate was detected but was NOT auto-selected: $($Candidate.DeviceID) - $($Candidate.Name)"
            Write-Host "Confirm the real ESP32 port during Stage 5B, then edit AI_RESCUE_UWB_SERIAL_PORT in host.env."
        } else {
            Write-Host "UWB Serial: NOT CONFIGURED ($($SerialCandidates.Count) generic serial candidates detected; automatic selection is disabled)"
            foreach ($Candidate in $SerialCandidates) {
                Write-Host "  $($Candidate.DeviceID) - $($Candidate.Name)"
            }
            Write-Host "Confirm the real ESP32 port during Stage 5B, then edit AI_RESCUE_UWB_SERIAL_PORT in host.env."
        }
    } else {
        $UwbStatus = "CONFIGURED ($ConfiguredPort)"
        Write-Host "UWB Serial: $UwbStatus (value preserved from host.env; hardware was not verified)"
    }

    Write-Host ""
    Write-Host "========================================"
    Write-Host "AI Rescue Box Host Setup Complete"
    Write-Host "========================================"
    Write-Host "Python Runtime : READY"
    Write-Host "Host Packages  : READY"
    Write-Host "Flutter Web    : READY"
    Write-Host "Host Config    : READY"
    Write-Host "UWB Serial     : $UwbStatus"
    Write-Host ""
    Write-Host "Next:"
    Write-Host ""
    Write-Host ".\deploy\host_windows\start.ps1"
    Write-Host ""
    Write-Host "========================================"
} catch {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "AI Rescue Box Host Setup Failed" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "Stage  : $CurrentStage" -ForegroundColor Yellow
    Write-Host "Reason : $($_.Exception.Message)" -ForegroundColor Yellow
    if ($CurrentStage -eq "Python prerequisite") { Show-PythonInstallHelp }
    if ($CurrentStage -eq "Flutter prerequisite") { Show-FlutterInstallHelp }
    Write-Host "Fix the item above and rerun: .\deploy\host_windows\setup.ps1"
    exit 1
}
