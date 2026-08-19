param(
    [string]$ApiBaseUrl = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$FlutterRoot = Join-Path $RepoRoot "src\host\flutter_app"

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    throw "Flutter was not found in PATH. Run install.ps1 after installing Flutter."
}

Push-Location $FlutterRoot
try {
    & flutter pub get
    $BuildArgs = @("build", "web", "--release")
    if (-not [string]::IsNullOrWhiteSpace($ApiBaseUrl)) {
        $BuildArgs += "--dart-define=API_BASE_URL=$ApiBaseUrl"
    }
    & flutter @BuildArgs
}
finally {
    Pop-Location
}

$Index = Join-Path $FlutterRoot "build\web\index.html"
if (-not (Test-Path $Index)) {
    throw "Flutter Web build did not produce $Index"
}
Write-Host "Host Flutter Web build ready: $Index"
