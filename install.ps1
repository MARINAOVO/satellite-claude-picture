$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Find-Python {
    $checks = @(
        @{ Command = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"; Args = @() },
        @{ Command = "py"; Args = @("-3.12") },
        @{ Command = "python"; Args = @() }
    )

    foreach ($check in $checks) {
        if (-not (Get-Command $check.Command -ErrorAction SilentlyContinue)) {
            continue
        }

        & $check.Command @($check.Args) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $check
        }
    }

    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python 3.12 was not found. Please install Python 3.12 and run this script again."
    Write-Host "Download: https://www.python.org/downloads/"
    exit 1
}

if (-not (Test-Path "$root\.venv")) {
    & $python.Command @($python.Args) -m venv "$root\.venv"
}

& "$root\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$root\.venv\Scripts\python.exe" -m pip install -r "$root\requirements.txt"
& "$root\.venv\Scripts\python.exe" -m pip install -e "$root"
