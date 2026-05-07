# Build the fishbot one-shot bootstrap installer.
#
# Run from the repo root in PowerShell:
#   powershell -ExecutionPolicy Bypass -File installer\build-bootstrap.ps1
#
# Optional: set the source URL the bootstrapper will download fishbot from.
#   $env:FISHBOT_SOURCE_URL =
#       "https://github.com/<user>/fishbot-windows/archive/refs/tags/v1.0.0.zip"
#   powershell -ExecutionPolicy Bypass -File installer\build-bootstrap.ps1
#
# Produces: dist\fishbot-setup.exe   (single-file, windowed, ~10 MB)

$ErrorActionPreference = "Stop"

$repo = Resolve-Path "$PSScriptRoot\.."
Set-Location $repo

Write-Host "==> repo: $repo"

# Build venv -- isolated from the dev venv so PyInstaller's analysis only sees
# stdlib + pyinstaller, keeping the bootstrap exe small.
$venv = Join-Path $repo ".bootstrap-venv"
if (-not (Test-Path $venv)) {
    Write-Host "==> creating bootstrap build venv at $venv"
    python -m venv $venv
}
$venvPython = Join-Path $venv "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip | Out-Null
& $venvPython -m pip install --upgrade "pyinstaller>=6.10" | Out-Null

# Clean prior bootstrap output (don't touch the full installer's dist).
foreach ($p in @("build\bootstrap", "dist\fishbot-setup.exe")) {
    $full = Join-Path $repo $p
    if (Test-Path $full) {
        Write-Host "==> removing $full"
        Remove-Item -Recurse -Force $full
    }
}

if ($env:FISHBOT_SOURCE_URL) {
    Write-Host "==> baking FISHBOT_SOURCE_URL=$($env:FISHBOT_SOURCE_URL)"
    # PyInstaller picks up env vars at build time only if the script reads them
    # at runtime; we want compile-time substitution. Patch a temp copy of the
    # bootstrap module before freezing.
    $boot = Join-Path $repo "installer\bootstrap.py"
    $orig = Get-Content -Raw $boot
    # Replace whichever GitHub archive URL is currently the default.
    $patched = $orig -replace `
        '"https://github\.com/[^"]+\.zip"', `
        ('"' + $env:FISHBOT_SOURCE_URL + '"')
    Set-Content -Path $boot -Value $patched -NoNewline
    $restoreBoot = $true
} else {
    Write-Host "==> using default source URL baked into bootstrap.py"
    $restoreBoot = $false
}

try {
    Write-Host "==> building fishbot-setup.exe"
    & $venvPython -m PyInstaller installer\bootstrap.spec --noconfirm `
        --distpath dist --workpath build\bootstrap
} finally {
    if ($restoreBoot) {
        Set-Content -Path (Join-Path $repo "installer\bootstrap.py") `
            -Value $orig -NoNewline
    }
}

$out = Join-Path $repo "dist\fishbot-setup.exe"
if (-not (Test-Path $out)) {
    Write-Error "PyInstaller did not produce $out"
}

Write-Host ""
Write-Host "==> done. Bootstrap installer:"
Get-Item $out | ForEach-Object {
    Write-Host ("    {0}  ({1} MB)" -f $_.FullName, [math]::Round($_.Length / 1MB, 1))
}
