param(
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$WebIndex = Join-Path $RepoRoot "src\host\flutter_app\build\web\index.html"
if (-not (Test-Path $WebIndex)) { throw "Build Host Web release before packaging." }
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory = Join-Path $RepoRoot "dist" }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$Stage = Join-Path $OutputDirectory "ai-rescue-box-host"
$Zip = Join-Path $OutputDirectory "ai-rescue-box-host.zip"
Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $Zip -Force -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Force -Path (Join-Path $Stage "src\host") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "src\host\config") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "src\uwb") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "deploy") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "docs") | Out-Null
Copy-Item (Join-Path $RepoRoot "src\host\host_app") (Join-Path $Stage "src\host\host_app") -Recurse
Copy-Item (Join-Path $RepoRoot "src\host\flutter_app") (Join-Path $Stage "src\host\flutter_app") -Recurse
Copy-Item (Join-Path $RepoRoot "src\host\config\host.env.example") (Join-Path $Stage "src\host\config\host.env.example")
Copy-Item (Join-Path $RepoRoot "src\uwb\protocol") (Join-Path $Stage "src\uwb\protocol") -Recurse
Copy-Item $PSScriptRoot (Join-Path $Stage "deploy\host_windows") -Recurse
Copy-Item (Join-Path $RepoRoot "docs\stage5_hardware_validation.md") (Join-Path $Stage "docs\stage5_hardware_validation.md")
Copy-Item (Join-Path $RepoRoot "docs\stage5_measurement_template.md") (Join-Path $Stage "docs\stage5_measurement_template.md")
Get-ChildItem $Stage -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Get-ChildItem $Stage -Recurse -Directory -Filter .dart_tool | Remove-Item -Recurse -Force
Get-ChildItem $Stage -Recurse -File -Include *.pyc,*.pyo | Remove-Item -Force

$Commit = "unknown"
if (Get-Command git -ErrorAction SilentlyContinue) {
    try { $Commit = (& git -C $RepoRoot rev-parse HEAD).Trim() } catch {}
}
@"
AI Rescue Box Windows Host release
Source commit: $Commit
Generated: $([DateTime]::UtcNow.ToString("o"))
Runtime requires Python 3.10+. Flutter SDK is not required after Web assets are built.
Hardware verification is not included in this bundle.
"@ | Set-Content (Join-Path $Stage "RELEASE.txt") -Encoding utf8
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip -CompressionLevel Optimal
Write-Host "Host release bundle: $Zip"
