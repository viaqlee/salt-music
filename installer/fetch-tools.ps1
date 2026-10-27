<#
.SYNOPSIS
  Downloads ffmpeg, deno, adb and mpv into one folder (dist\SaltMusic\bin by default)
  so the installer can ship them. Every archive is checked against a published
  SHA-256 when its source publishes one.
#>
param([string]$Dest = (Join-Path (Split-Path -Parent $PSScriptRoot) 'dist\SaltMusic\bin'))
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is very slow with the progress bar
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

New-Item -ItemType Directory -Force $Dest | Out-Null
$Work = Join-Path ([IO.Path]::GetTempPath()) ("salt-tools-" + [guid]::NewGuid())
New-Item -ItemType Directory $Work | Out-Null

function Get-File([string]$Url, [string]$Name) {
    $out = Join-Path $Work $Name
    Write-Host "  $Url"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $out
    return $out
}

function Assert-Hash([string]$File, [string]$Expected) {
    $actual = (Get-FileHash -Algorithm SHA256 $File).Hash
    if ($actual -ne $Expected.Trim().ToUpper()) { throw "checksum mismatch: $File" }
}

function Expand-To([string]$Zip, [string]$Name) {
    $dir = Join-Path $Work $Name
    Expand-Archive -Path $Zip -DestinationPath $dir -Force
    return $dir
}

try {
    Write-Host 'FFmpeg (gyan.dev, release essentials)'
    $zip = Get-File 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' 'ffmpeg.zip'
    $sha = (Invoke-WebRequest -UseBasicParsing 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256').Content
    Assert-Hash $zip ([Text.Encoding]::ASCII.GetString($sha).Split()[0])
    $dir = Expand-To $zip 'ffmpeg'
    Get-ChildItem $dir -Recurse -Include ffmpeg.exe, ffprobe.exe | Copy-Item -Destination $Dest

    Write-Host 'Deno'
    $zip = Get-File 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip' 'deno.zip'
    $sha = Invoke-WebRequest -UseBasicParsing 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip.sha256sum'
    $text = if ($sha.Content -is [byte[]]) { [Text.Encoding]::ASCII.GetString($sha.Content) } else { $sha.Content }
    Assert-Hash $zip (($text -split '\s+') | Where-Object { $_ -match '^[0-9a-fA-F]{64}$' } | Select-Object -First 1)
    $dir = Expand-To $zip 'deno'
    Copy-Item (Join-Path $dir 'deno.exe') $Dest

    Write-Host 'Android platform-tools (adb)'
    $zip = Get-File 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' 'pt.zip'
    $dir = Expand-To $zip 'pt'
    Copy-Item (Join-Path $dir 'platform-tools\adb.exe'), (Join-Path $dir 'platform-tools\AdbWinApi.dll'),
              (Join-Path $dir 'platform-tools\AdbWinUsbApi.dll') $Dest

    Write-Host 'mpv (shinchiro builds, needs tar with 7z support or 7-Zip)'
    $rel = Invoke-RestMethod -UseBasicParsing 'https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest'
    $asset = $rel.assets | Where-Object { $_.name -match '^mpv-x86_64-\d{8}-git-[0-9a-f]+\.7z$' } | Select-Object -First 1
    if ($asset) {
        $arc = Get-File $asset.browser_download_url 'mpv.7z'
        if ($asset.digest -match '^sha256:([0-9a-f]{64})$') { Assert-Hash $arc $Matches[1] }
        $dir = Join-Path $Work 'mpv'
        New-Item -ItemType Directory $dir | Out-Null
        $seven = Get-Command 7z.exe -ErrorAction SilentlyContinue
        if ($seven) { & $seven.Source x $arc "-o$dir" -y | Out-Null } else { tar -xf $arc -C $dir }
        $mpv = Get-ChildItem $dir -Recurse -Filter mpv.exe | Select-Object -First 1
        if ($mpv) { Copy-Item $mpv.FullName $Dest } else { Write-Warning 'mpv.exe not found in the archive: skipped' }
    } else {
        Write-Warning 'no mpv release found: skipped'
    }
}
finally {
    Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue
}
Get-ChildItem $Dest | Format-Table Name, Length
