param(
  [Parameter(Mandatory = $true)]
  [string]$WebView2FixedRuntimePath,
  [string]$OutputDirectory = "artifacts/windows-x64"
)

$ErrorActionPreference = "Stop"
$Repository = Split-Path -Parent $MyInvocation.MyCommand.Path
$Version = (Get-Content (Join-Path $Repository "VERSION") -Raw).Trim()
$Desktop = Join-Path $Repository "desktop"
$Tauri = Join-Path $Desktop "src-tauri"
$RuntimeTarget = Join-Path $Tauri "WebView2.FixedVersionRuntime.x64"
$BinaryTarget = Join-Path $Tauri "binaries"
$PyInstallerOutput = Join-Path $Desktop "pyinstaller-dist"
$Artifacts = Join-Path $Repository $OutputDirectory

function Assert-NativeCommand([string]$Step) {
  if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" }
}

if (-not [Environment]::Is64BitOperatingSystem) { throw "Windows x64 build host is required" }
if (-not (Test-Path $WebView2FixedRuntimePath -PathType Container)) { throw "WebView2 fixed runtime directory does not exist" }
$WebViewExecutable = Get-ChildItem $WebView2FixedRuntimePath -Filter "msedgewebview2.exe" -File -Recurse | Select-Object -First 1
if (-not $WebViewExecutable) { throw "WebView2 fixed runtime does not contain msedgewebview2.exe" }
$WebViewRuntimeSource = $WebViewExecutable.Directory.FullName

Write-Host "Building WXY LAB Hardware v$Version for Windows x64"
New-Item -ItemType Directory -Force $Artifacts, $BinaryTarget | Out-Null

python -m pip install --upgrade pip pyinstaller cyclonedx-bom
Assert-NativeCommand "Build dependency installation"
python -m pip install -r (Join-Path $Repository "backend/requirements.txt")
Assert-NativeCommand "Backend dependency installation"
npm --prefix (Join-Path $Repository "frontend") ci
Assert-NativeCommand "Frontend dependency installation"
npm --prefix $Desktop ci
Assert-NativeCommand "Desktop dependency installation"

if (Test-Path $PyInstallerOutput) { Remove-Item -Recurse -Force $PyInstallerOutput }
python -m PyInstaller --noconfirm --clean `
  --distpath $PyInstallerOutput `
  --workpath (Join-Path $Desktop "pyinstaller-build") `
  (Join-Path $Desktop "pyinstaller/wxy-hardware-api.spec")
Assert-NativeCommand "PyInstaller sidecar build"

if (Test-Path $BinaryTarget) { Remove-Item -Recurse -Force $BinaryTarget }
New-Item -ItemType Directory -Force $BinaryTarget | Out-Null
$SidecarSource = Join-Path $PyInstallerOutput "wxy-hardware-api"
Copy-Item (Join-Path $SidecarSource "_internal") (Join-Path $BinaryTarget "_internal") -Recurse
Copy-Item (Join-Path $SidecarSource "wxy-hardware-api.exe") `
  (Join-Path $BinaryTarget "wxy-hardware-api-x86_64-pc-windows-msvc.exe")

if (Test-Path $RuntimeTarget) { Remove-Item -Recurse -Force $RuntimeTarget }
Copy-Item $WebViewRuntimeSource $RuntimeTarget -Recurse

npm --prefix $Desktop run build
Assert-NativeCommand "Tauri desktop build"

$Installer = Get-ChildItem (Join-Path $Tauri "target/release/bundle/nsis/*-setup.exe") | Select-Object -First 1
if (-not $Installer) { throw "NSIS installer was not generated" }
$PublishedInstaller = Join-Path $Artifacts "WXY-LAB-Hardware-Setup-x64.exe"
Copy-Item $Installer.FullName $PublishedInstaller -Force

cyclonedx-py environment --output-format JSON --output-file (Join-Path $Artifacts "backend-sbom.cdx.json")
Assert-NativeCommand "Backend SBOM generation"
npx --yes @cyclonedx/cyclonedx-npm@latest `
  --output-file (Join-Path $Artifacts "frontend-sbom.cdx.json") `
  (Join-Path $Repository "frontend/package-lock.json")
Assert-NativeCommand "Frontend SBOM generation"

$Hash = (Get-FileHash $PublishedInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
"$Hash  WXY-LAB-Hardware-Setup-x64.exe" | Set-Content `
  (Join-Path $Artifacts "WXY-LAB-Hardware-Setup-x64.exe.sha256") -Encoding ascii
Write-Host "Installer: $PublishedInstaller"
Write-Host "SHA256: $Hash"
