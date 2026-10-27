<#
.SYNOPSIS
  Builds dist\SaltMusic (the program) and dist\SaltMusic-Setup-<version>.exe (the installer).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File installer\build.ps1
  powershell -ExecutionPolicy Bypass -File installer\build.ps1 -BundleTools   # ffmpeg, deno, adb, mpv inside

  Needs: Python 3.12+ (python.org or winget install Python.Python.3.14) and Inno Setup 6
  (winget install JRSoftware.InnoSetup).
#>
param(
    [switch]$BundleTools,
    [switch]$NoInstaller
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Version = (Select-String -Path 'salt_music\__init__.py' -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "Salt Music $Version" -ForegroundColor Cyan

# --- clean build environment, separate from any development venv
$Venv = Join-Path $Root '.build-venv'
if (-not (Test-Path "$Venv\Scripts\python.exe")) {
    py -3 -m venv $Venv
    if ($LASTEXITCODE) { python -m venv $Venv }
}
$Py = "$Venv\Scripts\python.exe"
& $Py -m pip install --upgrade pip | Out-Null
& $Py -m pip install -r requirements.txt -r installer\requirements-build.txt
if ($LASTEXITCODE) { throw 'pip install failed' }

# --- pack with PyInstaller through flet
Remove-Item -Recurse -Force build, dist\SaltMusic -ErrorAction SilentlyContinue
$Parts = $Version.Split('.') + @('0', '0', '0')
$FileVersion = ($Parts[0..3] -join '.')
& "$Venv\Scripts\flet.exe" pack main.py `
    --onedir --name SaltMusic --icon assets\icon.ico `
    --add-data "assets;assets" `
    --product-name 'Salt Music' --file-description 'Salt Music' `
    --product-version $Version --file-version $FileVersion `
    --company-name 'Salt Music' --copyright 'Salt Music' `
    --distpath dist -y `
    -- --collect-all yt_dlp_ejs --collect-data ytmusicapi --collect-submodules yt_dlp --copy-metadata yt-dlp --noconfirm
if ($LASTEXITCODE) { throw 'flet pack failed' }

if ($BundleTools) {
    & "$PSScriptRoot\fetch-tools.ps1" -Dest "dist\SaltMusic\bin"
}

if ($NoInstaller) { return }

# --- installer
$Iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw 'Inno Setup 6 not found: winget install JRSoftware.InnoSetup' }
$IssArgs = @("/DAppVersion=$Version")
if ($BundleTools) { $IssArgs += '/DBundled' }
& $Iscc @IssArgs installer\SaltMusic.iss
if ($LASTEXITCODE) { throw 'ISCC failed' }
Get-Item "dist\SaltMusic-Setup-$Version.exe" | Format-Table Name, Length
