param(
    [switch]$SkipInstall,
    [switch]$NoZip,
    [switch]$RequireCuda,
    [string]$PythonExeOverride,
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cpu",
    [string]$Version = "0.9.4"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectRoot ".venv-build-pytorch"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$DistDir = Join-Path $ProjectRoot "dist"
$StagingDir = Join-Path $DistDir "HS_MOSAIC_PyTorch"
$UsingExternalPython = $false
if ($PythonExeOverride) {
    $PythonExe = (Resolve-Path $PythonExeOverride).Path
    $UsingExternalPython = $true
}

Set-Location $ProjectRoot

function Compress-PackageWithRetry {
    param(
        [Parameter(Mandatory=$true)][string]$SourcePath,
        [Parameter(Mandatory=$true)][string]$DestinationPath
    )

    for ($Attempt = 1; $Attempt -le 5; $Attempt++) {
        try {
            Remove-Item -LiteralPath $DestinationPath -Force -ErrorAction SilentlyContinue
            Compress-Archive -Path $SourcePath -DestinationPath $DestinationPath -Force
            return
        } catch {
            if ($Attempt -eq 5) {
                throw
            }
            Start-Sleep -Seconds (5 * $Attempt)
        }
    }
}

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

$TorchBuildLabel = "CUSTOM"
if ($TorchIndexUrl -match "/whl/([^/]+)/?$") {
    $TorchBuildLabel = $Matches[1].ToUpperInvariant()
}
if ($TorchBuildLabel -match "^CU(\d+)$") {
    $TorchBuildLabel = "CUDA$($Matches[1])"
}
if ($TorchBuildLabel -eq "CPU") {
    $PackageName = "HS_MOSAIC_PyTorch_CPU_v$Version"
} elseif ($RequireCuda -or $TorchBuildLabel.StartsWith("CUDA")) {
    $PackageName = "HS_MOSAIC_GPU_${TorchBuildLabel}_v$Version"
} else {
    $PackageName = "HS_MOSAIC_PyTorch_${TorchBuildLabel}_v$Version"
}
$PackageDir = Join-Path $DistDir $PackageName
$ZipPath = Join-Path $DistDir "$PackageName.zip"

& $PythonExe -m PyInstaller --noconfirm --clean hs_crs_analysis_gui_pytorch.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$ExePath = Join-Path $StagingDir "HS_MOSAIC.exe"
if (-not (Test-Path $ExePath)) {
    throw "Expected executable was not created: $ExePath"
}

if (Test-Path $PackageDir) {
    Remove-Item -LiteralPath $PackageDir -Recurse -Force
}
Move-Item -LiteralPath $StagingDir -Destination $PackageDir
$ExePath = Join-Path $PackageDir "HS_MOSAIC.exe"

Write-Host "Built PyTorch-enabled executable:"
Write-Host $ExePath

if (-not $NoZip) {
    Compress-PackageWithRetry -SourcePath $PackageDir -DestinationPath $ZipPath
    Write-Host "Built portable zip:"
    Write-Host $ZipPath
}
