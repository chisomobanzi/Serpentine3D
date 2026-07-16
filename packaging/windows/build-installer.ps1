# Builds the Windows installer: PyInstaller bundle + Inno Setup wrapper.
# Run from this directory in a venv that has serpentine3d installed:
#   powershell -ExecutionPolicy Bypass -File build-installer.ps1
param(
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"

& $Python -m pip install --quiet pyinstaller
# PyInstaller cannot trace PEP 660 editable installs - make sure the
# package is present as real files in site-packages
& $Python -m pip install --quiet --force-reinstall --no-deps ..\..
& $Python -m PyInstaller --clean -y serp3d.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "=== bundle selftest ==="
& ".\dist\serp3d\serp3d.exe" --selftest
if ($LASTEXITCODE -ne 0) {
    Get-Content (Join-Path $env:TEMP "serp3d-selftest.txt")
    throw "bundle selftest failed"
}
Get-Content (Join-Path $env:TEMP "serp3d-selftest.txt")

$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "$env:ProgramFiles\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { throw "Inno Setup 6 not found - install from jrsoftware.org" }
& $iscc installer.iss
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }

$out = Get-Item ".\Output\Serpentine3D-Setup-x86_64.exe"
Write-Host ("INSTALLER OK: {0} ({1:N0} MB)" -f $out.FullName, ($out.Length / 1MB))
