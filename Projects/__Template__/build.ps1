$ErrorActionPreference = "Stop"

param(
    [string]$Python = "",
    [switch]$NoActivate,
    [switch]$Upgrade
)

$projectRoot = $PSScriptRoot
$venv = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
$venvActivate = Join-Path $venv "Scripts\Activate.ps1"
$paramsFile = Join-Path $projectRoot "Params\params.json"

function Resolve-Python {
    if ($Python) {
        $candidate = Get-Command $Python -CommandType Application -ErrorAction SilentlyContinue
        if ($candidate) {
            return $candidate.Source
        }
        if (Test-Path -LiteralPath $Python -PathType Leaf) {
            return (Resolve-Path -LiteralPath $Python).Path
        }
        throw "Python executable not found: $Python"
    }
    $candidate = Get-Command python -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
    return $candidate.Source
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    if (Test-Path -LiteralPath $venv) {
        throw "The existing $venv is not a usable Windows virtual environment."
    }
    $pythonExecutable = Resolve-Python
    & $pythonExecutable -m venv $venv
    if ($LASTEXITCODE -ne 0) {
        throw "Virtual environment creation failed: $venv"
    }
}

$requirementsFiles = @(
    (Join-Path $projectRoot "requirements.txt"),
    (Join-Path $PSScriptRoot "..\requirements.txt")
) | Select-Object -Unique

foreach ($requirements in $requirementsFiles) {
    if (Test-Path -LiteralPath $requirements -PathType Leaf) {
        $pipArguments = @("-m", "pip", "install")
        if ($Upgrade) {
            $pipArguments += "--upgrade"
        }
        $pipArguments += @("-r", $requirements)
        & $venvPython $pipArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Dependency installation failed: $requirements"
        }
    }
}

if (Test-Path -LiteralPath $paramsFile -PathType Leaf) {
    $params = Get-Content -LiteralPath $paramsFile -Raw | ConvertFrom-Json
    if ($null -ne $params.Timeout -and -not $env:PYSYS_TIMEOUT) {
        $env:PYSYS_TIMEOUT = [string]$params.Timeout
    }
    if ($null -ne $params.OutputFile -and -not $env:PYSYS_OUTPUT_FILE) {
        $env:PYSYS_OUTPUT_FILE = [string]$params.OutputFile
    }
    if ($null -ne $params.RunCode -and -not $env:PYSYS_RUN_CODE) {
        $env:PYSYS_RUN_CODE = [string]$params.RunCode
    }
    if ($params.LanguageModelSettings) {
        if ($params.LanguageModelSettings.model -and -not $env:PYSYS_MODEL) {
            $env:PYSYS_MODEL = [string]$params.LanguageModelSettings.model
        }
        if ($params.LanguageModelSettings.endpoint -and -not $env:PYSYS_ENDPOINT) {
            $env:PYSYS_ENDPOINT = [string]$params.LanguageModelSettings.endpoint
        }
        if ($params.LanguageModelSettings.reasoning.effort -and -not $env:PYSYS_REASONING_EFFORT) {
            $env:PYSYS_REASONING_EFFORT = [string]$params.LanguageModelSettings.reasoning.effort
        }
    }
}

if (-not $NoActivate) {
    if (-not (Test-Path -LiteralPath $venvActivate -PathType Leaf)) {
        throw "Virtual environment activation script not found: $venvActivate"
    }
    & $venvActivate
    if ($env:VIRTUAL_ENV -ne $venv) {
        throw "Failed to activate virtual environment: $venv"
    }
}

Write-Host "PySYS virtual environment ready: $venv"
Write-Host "Project: $projectRoot"
if ($NoActivate) {
    Write-Host "Environment activation skipped; use: & '$venvActivate'"
} else {
    Write-Host "Environment activated for this PowerShell session."
}
