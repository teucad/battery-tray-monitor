<#
Builds battery-tray-monitor into a single standalone Windows executable,
dist\BatteryTrayMonitor.exe, that runs without Python installed. Must run
on Windows: PyInstaller can't cross-compile, and the exe bundles the
Windows-only Bluetooth (winrt) and tray (pystray._win32) backends. CI runs
this same script; see .github/workflows/battery-tray-monitor.yml.

Payment settings come from monetization_config.json. Any of these
environment variables, if set, override that file's values in the bundled
copy only, so CI can inject them from GitHub repository variables without
committing them:
  BTM_REVENUECAT_PUBLIC_API_KEY
  BTM_SUBSCRIPTION_PURCHASE_LINK
  BTM_LIFETIME_PURCHASE_LINK
  BTM_ADS_FEED_URL
#>
$ErrorActionPreference = "Stop"

$pythonwPath = & (Join-Path $PSScriptRoot "Ensure-Env.ps1")
if (-not $pythonwPath -or -not (Test-Path $pythonwPath)) {
    throw "Failed to resolve pythonw.exe via Ensure-Env.ps1"
}
$venvPython = Join-Path (Split-Path $pythonwPath -Parent) "python.exe"

Write-Host "Installing build requirements..." -ForegroundColor Cyan
& $venvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $PSScriptRoot "requirements-build.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install build requirements"
}

$buildDir = Join-Path $PSScriptRoot "build"
$distDir = Join-Path $PSScriptRoot "dist"
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

# --- Bundled monetization config, with any env var overrides applied ---
$config = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot "monetization_config.json") | ConvertFrom-Json
$overrides = @{
    "BTM_REVENUECAT_PUBLIC_API_KEY"  = "revenuecat_public_api_key"
    "BTM_SUBSCRIPTION_PURCHASE_LINK" = "subscription_purchase_link"
    "BTM_LIFETIME_PURCHASE_LINK"     = "lifetime_purchase_link"
    "BTM_ADS_FEED_URL"               = "ads_feed_url"
}
foreach ($envName in $overrides.Keys) {
    $value = [System.Environment]::GetEnvironmentVariable($envName)
    if ($value) {
        $config.($overrides[$envName]) = $value.Trim()
        Write-Host "Using $envName for $($overrides[$envName])"
    }
}
if (-not $config.revenuecat_public_api_key) {
    Write-Warning "No RevenueCat public API key configured - the exe will show ads, but its purchase buttons will be disabled. See MONETIZATION_SETUP.md."
}
$bundledConfig = Join-Path $buildDir "monetization_config.json"
# UTF-8 without a BOM - Windows PowerShell 5.1's Set-Content -Encoding UTF8 adds one.
[System.IO.File]::WriteAllText($bundledConfig, ($config | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding $false))

# --- App icon, drawn by the same code as the tray icon ---
$iconPath = Join-Path $buildDir "BatteryTrayMonitor.ico"
& $venvPython -c "import sys; sys.path.insert(0, r'$PSScriptRoot'); import battery_tray; battery_tray.make_icon([{'battery': 100}]).save(r'$iconPath', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to generate the app icon"
}

# --- PyInstaller ---
# Paths are absolute: PyInstaller resolves --add-data/--icon relative to
# --specpath, not the current directory.
$pyinstallerArgs = @(
    "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "BatteryTrayMonitor",
    "--icon", $iconPath,
    "--distpath", $distDir,
    "--workpath", (Join-Path $buildDir "pyinstaller"),
    "--specpath", $buildDir,
    "--add-data", "$(Join-Path $PSScriptRoot 'battery_query.ps1');.",
    "--add-data", "$bundledConfig;.",
    # Imported dynamically, so PyInstaller's static analysis misses them:
    # pystray picks its backend at runtime, and bleak loads its WinRT
    # backend (and the winrt namespace packages' .pyd modules) on demand.
    "--hidden-import", "pystray._win32",
    "--collect-submodules", "bleak",
    "--collect-submodules", "winrt",
    (Join-Path $PSScriptRoot "battery_tray.py")
)

Write-Host "Running PyInstaller..." -ForegroundColor Cyan
Push-Location $PSScriptRoot
try {
    & $venvPython -m PyInstaller @pyinstallerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed"
    }
} finally {
    Pop-Location
}

$exePath = Join-Path $distDir "BatteryTrayMonitor.exe"
if (-not (Test-Path $exePath)) {
    throw "PyInstaller finished but $exePath is missing"
}
Write-Host "Built $exePath" -ForegroundColor Green
