<#
.SYNOPSIS
    Set up HS-MOSAIC with GPU acceleration through DirectML (AMD Radeon GPUs,
    Ryzen APUs with integrated Radeon graphics, or any other DirectX-12 GPU on
    Windows).

.DESCRIPTION
    Creates a dedicated virtual environment (.venv-directml next to this
    script), installs Microsoft's torch-directml plugin together with the
    PyTorch version it pins, installs HS-MOSAIC from this checkout in editable
    mode, and finally runs the backend self-test so you can see immediately
    whether the GPU was picked up (look for "nmf_backend": "torch-dml").

    The environment is self-contained: your system Python and any PyTorch you
    already have installed there are left untouched. hs-mosaic.bat prefers
    this environment automatically once it exists.

.PARAMETER PythonExe
    Interpreter used to create the environment (default: "python" on PATH).
    torch-directml 0.2.5 ships wheels for Python 3.8 - 3.12.

.PARAMETER Recreate
    Delete an existing .venv-directml first.

.PARAMETER SkipSelfTest
    Do not run the backend self-test at the end.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows_directml.ps1
#>
param(
    [string]$PythonExe = "python",
    [switch]$Recreate,
    [switch]$SkipSelfTest
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectRoot ".venv-directml"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

Set-Location $ProjectRoot

if ($Recreate -and (Test-Path $VenvDir)) {
    Write-Host "Removing existing $VenvDir"
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment in $VenvDir"
    & $PythonExe -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment (exit code $LASTEXITCODE)." }
}

Write-Host "Upgrading pip"
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed (exit code $LASTEXITCODE)." }

# torch-directml pins the torch (and torchvision) build it was compiled
# against, so let pip resolve those from the plugin's own requirements.
Write-Host "Installing torch-directml (this pulls the matching PyTorch build, ~250 MB)"
& $VenvPython -m pip install "torch-directml>=0.2.5.dev0"
if ($LASTEXITCODE -ne 0) { throw "torch-directml install failed (exit code $LASTEXITCODE)." }

Write-Host "Installing HS-MOSAIC from this checkout (editable)"
& $VenvPython -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "hs-mosaic install failed (exit code $LASTEXITCODE)." }

& $VenvPython -c "import torch, torch_directml; n = torch_directml.device_count(); print('torch', torch.__version__, '| DirectML devices:', n, '|', torch_directml.device_name(0).strip() if n else 'none')"

if (-not $SkipSelfTest) {
    Write-Host ""
    Write-Host "Running the backend self-test (expect nmf_backend / nnls_backend = torch-dml):"
    # The self-test writes its JSON report to a file; its INFO log lines go to
    # stderr, which PowerShell would otherwise turn into terminating errors
    # under $ErrorActionPreference = "Stop".
    $ReportPath = Join-Path $env:TEMP "hs_mosaic_backend_selftest.json"
    $PreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $VenvPython -W ignore -m hs_mosaic --backend-self-test $ReportPath 2>&1 | Out-Null
    $SelfTestExit = $LASTEXITCODE
    $ErrorActionPreference = $PreviousPreference
    if (Test-Path $ReportPath) {
        Get-Content $ReportPath
    }
    if ($SelfTestExit -ne 0) {
        Write-Warning "The self-test did not report a working torch backend. Check the JSON above; the GUI still runs, on the CPU paths."
    }
}

Write-Host ""
Write-Host "Done. Start the GUI with:"
Write-Host "    .\hs-mosaic.bat"
Write-Host "or:"
Write-Host "    $VenvPython -m hs_mosaic"
