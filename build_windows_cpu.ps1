param(
    [switch]$SkipInstall,
    [switch]$NoZip
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectRoot ".venv-build"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

Set-Location $ProjectRoot

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

$ExePath = Join-Path $ProjectRoot "dist\HS_CRS_Analysis_GUI\HS_CRS_Analysis_GUI.exe"
if (-not (Test-Path $ExePath)) {
    throw "Expected executable was not created: $ExePath"
}

Write-Host "Built CPU-only executable:"
Write-Host $ExePath

if (-not $NoZip) {
    $PackageDir = Join-Path $ProjectRoot "dist\HS_CRS_Analysis_GUI"
    $ZipPath = Join-Path $ProjectRoot "dist\HS_CRS_Analysis_GUI_CPU_portable.zip"
    Compress-Archive -Path $PackageDir -DestinationPath $ZipPath -Force
    Write-Host "Built portable zip:"
    Write-Host $ZipPath
}
