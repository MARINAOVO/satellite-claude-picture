$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

& "$root\install.ps1"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& "$root\.venv\Scripts\python.exe" -m pip install -r "$root\requirements-dev.txt"
& "$root\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --windowed --name "SatelliteCloudReader" --add-data "$root\config.json;." "$root\app.py"
Write-Host "Build complete. The app is in dist\SatelliteCloudReader."
