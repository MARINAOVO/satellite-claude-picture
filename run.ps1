$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

& "$root\install.ps1"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& "$root\.venv\Scripts\python.exe" -m satellite_cloud_reader.main
