param(
    [switch]$SkipInstall,
    [switch]$NoZip,
    [string]$Version = "0.9.0"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectRoot ".venv-build"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$DistDir = Join-Path $ProjectRoot "dist"
$StagingDir = Join-Path $DistDir "HS_MOSAIC_CPU"
$PackageDir = Join-Path $DistDir "HS_MOSAIC_CPU_v$Version"
$ZipPath = Join-Path $DistDir "HS_MOSAIC_CPU_v$Version.zip"

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

if (-not (Test-Path $PythonExe)) {
    py -3 -m venv $VenvDir
}

if (-not $SkipInstall) {
    & $PythonExe -m pip install --upgrade pip setuptools wheel
    & $PythonExe -m pip install -r requirements.txt pyinstaller
}

& $PythonExe -m PyInstaller --noconfirm --clean hs_crs_analysis_gui_cpu.spec
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

Write-Host "Built CPU-only executable:"
Write-Host $ExePath

if (-not $NoZip) {
    Compress-PackageWithRetry -SourcePath $PackageDir -DestinationPath $ZipPath
    Write-Host "Built portable zip:"
    Write-Host $ZipPath
}
