# Fishbot Windows build pipeline.
#
# Run from the repo root in PowerShell:
#   powershell -ExecutionPolicy Bypass -File installer\build.ps1
#
# Produces dist\fishbot-setup-<version>.exe.
#
# Prerequisites on the build machine:
#   - Python 3.12+ on PATH
#   - Inno Setup 6 installed (default: C:\Program Files (x86)\Inno Setup 6)
#   - installer\vendor\tesseract\ populated with tesseract.exe + tessdata\eng.traineddata
#     (download the UB-Mannheim portable build from
#      https://github.com/UB-Mannheim/tesseract/wiki and unpack into that folder)

$ErrorActionPreference = "Stop"

# Always run from the repo root so relative paths in the spec files resolve.
$repo = Resolve-Path "$PSScriptRoot\.."
Set-Location $repo

Write-Host "==> repo: $repo"

# --- Sanity: bundled Tesseract must be in place ---
$tessExe = Join-Path $repo "installer\vendor\tesseract\tesseract.exe"
$tessData = Join-Path $repo "installer\vendor\tesseract\tessdata\eng.traineddata"
if (-not (Test-Path $tessExe) -or -not (Test-Path $tessData)) {
    Write-Error @"
Bundled Tesseract not found. Place tesseract.exe + tessdata\eng.traineddata under:
  installer\vendor\tesseract\
Download the portable UB-Mannheim build from:
  https://github.com/UB-Mannheim/tesseract/wiki
"@
}

# --- Build venv ---
$venv = Join-Path $repo ".build-venv"
if (-not (Test-Path $venv)) {
    Write-Host "==> creating build venv at $venv"
    python -m venv $venv
}
$venvPython = Join-Path $venv "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e ".[build]"

# --- Clean previous PyInstaller output ---
foreach ($p in @("build", "dist\fishbot", "dist\fishbot-gui")) {
    $full = Join-Path $repo $p
    if (Test-Path $full) {
        Write-Host "==> removing $full"
        Remove-Item -Recurse -Force $full
    }
}

# --- PyInstaller: CLI ---
Write-Host "==> building fishbot.exe"
& $venvPython -m PyInstaller installer\fishbot.spec --noconfirm

# --- PyInstaller: GUI ---
Write-Host "==> building fishbot-gui.exe"
& $venvPython -m PyInstaller installer\fishbot-gui.spec --noconfirm

# --- Stage Tesseract into the GUI dist (the installer copies CLI under
#     fishbot-gui\fishbot\, so a single tesseract folder serves both). ---
$vendorSrc = Join-Path $repo "installer\vendor\tesseract"
$vendorDst = Join-Path $repo "dist\fishbot-gui\vendor\tesseract"
Write-Host "==> staging Tesseract: $vendorSrc -> $vendorDst"
New-Item -ItemType Directory -Force -Path $vendorDst | Out-Null
Copy-Item -Recurse -Force "$vendorSrc\*" $vendorDst

# --- Inno Setup ---
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    $iscc = "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
}
if (-not (Test-Path $iscc)) {
    Write-Error "Inno Setup 6 (ISCC.exe) not found. Install from https://jrsoftware.org/isinfo.php"
}
Write-Host "==> compiling installer with $iscc"
& $iscc installer\fishbot.iss

Write-Host ""
Write-Host "==> done. Setup file:"
Get-ChildItem dist\fishbot-setup-*.exe | ForEach-Object {
    Write-Host "    $($_.FullName)  ($([math]::Round($_.Length / 1MB, 1)) MB)"
}
