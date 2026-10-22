<#
.SYNOPSIS
Build the standalone Windows executable dist\GameFlow.exe.
.EXAMPLE
.\build.ps1
.EXAMPLE
.\build.ps1 -Python C:\Python314\python.exe
.EXAMPLE
.\build.ps1 -SkipInstall
#>
[CmdletBinding()]
param(
    # Use this interpreter directly; otherwise use/create the project's .venv.
    [string]$Python,
    [switch]$SkipInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') {
    throw 'Build on Windows to create a Windows distribution.'
}

Push-Location -LiteralPath $PSScriptRoot
try {
    if (-not $Python) {
        $Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $Python)) {
            if ($SkipInstall) {
                throw 'No .venv found. Run without -SkipInstall or supply -Python.'
            }
            & python -m venv (Join-Path $PSScriptRoot '.venv')
            if ($LASTEXITCODE -ne 0) {
                throw "Creating .venv failed (exit $LASTEXITCODE). Install Python 3.11 or newer."
            }
        }
    }

    & $Python -c 'import sys; sys.exit(sys.version_info < (3, 11))'
    if ($LASTEXITCODE -ne 0) {
        throw 'A working Python 3.11 or newer interpreter is required.'
    }

    if (-not $SkipInstall) {
        & $Python -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements-build.txt')
        if ($LASTEXITCODE -ne 0) {
            throw "Installing build dependencies failed (exit $LASTEXITCODE)."
        }
    }

    & $Python -m PyInstaller --noconfirm --clean `
        --distpath (Join-Path $PSScriptRoot 'dist') `
        --workpath (Join-Path $PSScriptRoot 'build\pyinstaller') `
        (Join-Path $PSScriptRoot 'GameFlow.spec')
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed (exit $LASTEXITCODE)."
    }

    $executable = Join-Path $PSScriptRoot 'dist\GameFlow.exe'
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "Build finished without the expected executable: $executable"
    }
    Write-Host "Built: $executable"
    Write-Host 'Distribute GameFlow.exe by itself; Python does not need to be installed.'
}
finally {
    Pop-Location
}
