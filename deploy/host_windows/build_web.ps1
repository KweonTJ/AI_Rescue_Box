param(
    [string]$ApiBaseUrl = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$FlutterRoot = Join-Path $RepoRoot "src\host\flutter_app"

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    throw "Flutter was not found in PATH. Flutter is required only to build release Web assets."
}

Push-Location $FlutterRoot
try {
    & flutter pub get
    if ($LASTEXITCODE -ne 0) { throw "flutter pub get failed." }
    $BuildArgs = @("build", "web", "--release")
    if (-not [string]::IsNullOrWhiteSpace($ApiBaseUrl)) {
        $BuildArgs += "--dart-define=API_BASE_URL=$ApiBaseUrl"
    }
    & flutter @BuildArgs
    if ($LASTEXITCODE -ne 0) { throw "Flutter Web release build failed." }
}
finally {
    Pop-Location
}

$Index = Join-Path $FlutterRoot "build\web\index.html"
if (-not (Test-Path $Index)) {
    throw "Flutter Web build did not produce $Index"
}
Write-Host "Host Flutter Web release ready: $Index"
Write-Host "Normal runtime no longer requires Flutter SDK."
