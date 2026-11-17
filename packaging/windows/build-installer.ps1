# Builds the Windows installer: PyInstaller bundle + Inno Setup wrapper.
# Run from this directory in a venv that has serpentine3d installed:
#   powershell -ExecutionPolicy Bypass -File build-installer.ps1
param(
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"

& $Python -m pip install --quiet pyinstaller
# setuptools stages the package into the repo's build/ and never takes
# anything out again, so a rename leaves the old tree there to be installed
# alongside the new one. The Remove-Item below clears PyInstaller's workspace
# in this directory, which is a different build\ entirely.
Remove-Item ..\..\build -Recurse -Force -ErrorAction SilentlyContinue
# PyInstaller cannot trace PEP 660 editable installs - make sure the
# package is present as real files in site-packages
& $Python -m pip install --quiet --force-reinstall --no-deps ..\..
# a failed run leaves a poisoned Analysis-00.toc that later runs reuse;
# always start from a clean workspace
Remove-Item build, dist -Recurse -Force -ErrorAction SilentlyContinue
& $Python -m PyInstaller --clean -y serp3d.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "=== bundle selftest ==="
& ".\dist\serp3d\serp3d.exe" --selftest
$selftestExit = $LASTEXITCODE
# The frozen exe may run the selftest in a detached child, so its log file
# can lag/land elsewhere — echo it if present, but never fail on a missing
# file (the run above prints SELFTEST OK to the console either way).
Get-Content (Join-Path $env:TEMP "serp3d-selftest.txt") -ErrorAction SilentlyContinue
if ($selftestExit -ne 0) { throw "bundle selftest failed" }

$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "$env:ProgramFiles\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { throw "Inno Setup 6 not found - install from jrsoftware.org" }
& $iscc installer.iss
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }

# ISCC leaves Inno's 60-space placeholders after every version string, and
# SignPath compares ProductName and the rest exactly (see trim_version_info.py)
& $Python trim_version_info.py ".\Output\Serpentine3D-Setup-x86_64.exe"
if ($LASTEXITCODE -ne 0) { throw "Could not trim the installer's version strings" }

# Read them back the way Windows does, so a wrong name fails here rather
# than as a rejected signing request
$version = & $Python make_version_info.py --version
if ($LASTEXITCODE -ne 0 -or -not $version) { throw "Could not read the version" }
$info = (Get-Item ".\Output\Serpentine3D-Setup-x86_64.exe").VersionInfo
if ($info.ProductName -cne 'Serpentine3D' -or
    $info.CompanyName -cne 'Chisomo Banzi' -or
    $info.ProductVersion -cne $version) {
    throw ("Installer version info is not exact: ProductName='{0}' CompanyName='{1}' ProductVersion='{2}' (expected '{3}')" -f
        $info.ProductName, $info.CompanyName, $info.ProductVersion, $version)
}

$out = Get-Item ".\Output\Serpentine3D-Setup-x86_64.exe"
Write-Host ("INSTALLER OK: {0} ({1:N0} MB)" -f $out.FullName, ($out.Length / 1MB))
