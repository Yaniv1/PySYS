$ErrorActionPreference = "Stop"

$venv = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
$venvActivate = Join-Path $venv "Scripts\Activate.ps1"
$requirements = Join-Path $PSScriptRoot "requirements.txt"

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    if (Test-Path -LiteralPath $venv) {
        throw "The existing $venv is not a usable Windows virtual environment."
    }
    $python = Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1
    & $python.Source -m venv $venv
    if ($LASTEXITCODE -ne 0) {
        throw "Virtual environment creation failed (exit code $LASTEXITCODE)."
    }
}

& $venvPython -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed (exit code $LASTEXITCODE)."
}

if (-not (Test-Path -LiteralPath $venvActivate -PathType Leaf)) {
    throw "Virtual environment activation script not found: $venvActivate"
}

& $venvActivate
if ($env:VIRTUAL_ENV -ne $venv) {
    throw "Failed to activate virtual environment: $venv"
}
Write-Host "Dependencies installed and virtual environment activated: $venv"
Write-Host "Activation applies to this PowerShell session. Run this script as .\build.ps1, not with powershell -File."
