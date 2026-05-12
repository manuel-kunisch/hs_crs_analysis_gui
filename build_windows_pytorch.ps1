param(
    [switch]$SkipInstall,
    [switch]$NoZip,
    [switch]$RequireCuda,
    [string]$PythonExeOverride,
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cpu"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectRoot ".venv-build-pytorch"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$UsingExternalPython = $false
if ($PythonExeOverride) {
    $PythonExe = (Resolve-Path $PythonExeOverride).Path
    $UsingExternalPython = $true
}

Set-Location $ProjectRoot

if (-not $UsingExternalPython -and -not (Test-Path $PythonExe)) {
    py -3 -m venv $VenvDir
}

if (-not $SkipInstall) {
    & $PythonExe -m pip install --upgrade pip setuptools wheel
    & $PythonExe -m pip install -r requirements.txt pyinstaller
    & $PythonExe -m pip install --upgrade --force-reinstall torch --index-url $TorchIndexUrl
    if ($LASTEXITCODE -ne 0) {
        throw "PyTorch install failed with exit code $LASTEXITCODE"
    }
}

& $PythonExe -c "import sys, torch; print('Torch:', torch.__version__); print('Torch CUDA build:', torch.version.cuda); print('CUDA available:', torch.cuda.is_available()); print('CUDA devices:', torch.cuda.device_count()); print('CUDA device 0:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none'); sys.exit(2 if '$RequireCuda' == 'True' and not torch.cuda.is_available() else 0)"
if ($LASTEXITCODE -ne 0) {
    throw "PyTorch verification failed with exit code $LASTEXITCODE"
}

& $PythonExe -m PyInstaller --noconfirm --clean hs_crs_analysis_gui_pytorch.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$ExePath = Join-Path $ProjectRoot "dist\HS_CRS_Analysis_GUI_PyTorch\HS_CRS_Analysis_GUI_PyTorch.exe"
if (-not (Test-Path $ExePath)) {
    throw "Expected executable was not created: $ExePath"
}

Write-Host "Built PyTorch-enabled executable:"
Write-Host $ExePath

if (-not $NoZip) {
    $PackageDir = Join-Path $ProjectRoot "dist\HS_CRS_Analysis_GUI_PyTorch"
    $TorchBuildLabel = "CUSTOM"
    if ($TorchIndexUrl -match "/whl/([^/]+)/?$") {
        $TorchBuildLabel = $Matches[1].ToUpperInvariant()
    }
    $ZipPath = Join-Path $ProjectRoot "dist\HS_CRS_Analysis_GUI_PyTorch_${TorchBuildLabel}_portable.zip"
    Compress-Archive -Path $PackageDir -DestinationPath $ZipPath -Force
    Write-Host "Built portable zip:"
    Write-Host $ZipPath
}
