# Unattended sequential build of the HS-MOSAIC Windows packages.
# Runs CPU, then CUDA, then DirectML. Each build runs in its own child
# process, so a failure in one does NOT abort the others -- you get maximum
# information on return.
#
# Package choice for users: the CUDA zip is the fastest on NVIDIA GPUs; the
# DirectML zip runs on ANY DirectX-12 GPU (AMD Radeon / Ryzen APUs, Intel,
# also NVIDIA) but cannot use CUDA, so on NVIDIA hardware the dedicated CUDA
# build is substantially faster; the CPU zip needs no GPU at all.

param(
    [string]$Version = "0.9.10",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu124"
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
# Logs live under dist\ because /dist/ is already gitignored -- no new untracked files.
$LogDir  = Join-Path $Root "dist\build-logs"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Invoke-Build {
    param(
        [string]$Name,
        [string]$Script,
        [string[]]$ExtraArgs
    )

    $out = Join-Path $LogDir "$Stamp-$Name.out.log"
    $err = Join-Path $LogDir "$Stamp-$Name.err.log"

    $argList = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', (Join-Path $Root $Script),
        '-Version', $Version
    ) + $ExtraArgs

    Write-Host ""
    Write-Host ("=" * 70)
    Write-Host "[$(Get-Date -Format HH:mm:ss)] START $Name"
    Write-Host "  log: $out"
    Write-Host ("=" * 70)

    $started = Get-Date
    $p = Start-Process -FilePath "powershell.exe" `
                       -ArgumentList $argList `
                       -WorkingDirectory $Root `
                       -NoNewWindow -Wait -PassThru `
                       -RedirectStandardOutput $out `
                       -RedirectStandardError  $err

    $mins = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
    $code = $p.ExitCode

    if ($code -eq 0) {
        Write-Host "[$(Get-Date -Format HH:mm:ss)] OK   $Name  ($mins min)" -ForegroundColor Green
    } else {
        Write-Host "[$(Get-Date -Format HH:mm:ss)] FAIL $Name  (exit $code, $mins min)" -ForegroundColor Red
        Write-Host "--- last 25 lines of stderr ---" -ForegroundColor Yellow
        if ((Test-Path $err) -and (Get-Item $err).Length -gt 0) {
            Get-Content $err -Tail 25
        } else {
            Get-Content $out -Tail 25
        }
    }

    return [pscustomobject]@{
        Name = $Name; Exit = $code; Minutes = $mins; Out = $out; Err = $err
    }
}

$results = @()

$results += Invoke-Build -Name "CPU" `
                         -Script "build_windows_cpu.ps1" `
                         -ExtraArgs @()

$results += Invoke-Build -Name "CUDA" `
                         -Script "build_windows_pytorch.ps1" `
                         -ExtraArgs @('-TorchIndexUrl',$TorchIndexUrl,'-RequireCuda')

# DirectML (AMD Radeon / Ryzen APUs / any DirectX-12 GPU). Uses its own
# .venv-build-directml because torch-directml pins torch 2.4.1, which must
# not mix with the CUDA build environment. The verify step only needs SOME
# DX12 adapter on the build machine (an NVIDIA card qualifies).
$results += Invoke-Build -Name "DirectML" `
                         -Script "build_windows_pytorch.ps1" `
                         -ExtraArgs @('-DirectML')

# ----- summary -----------------------------------------------------------
Write-Host ""
Write-Host ("=" * 70)
Write-Host "SUMMARY  (HS-MOSAIC v$Version)"
Write-Host ("=" * 70)
$results | Format-Table Name, Exit, Minutes -AutoSize

Write-Host "Expected artifacts in dist\:"
$expected = @(
    "HS_MOSAIC_CPU_v$Version.zip",
    "HS_MOSAIC_GPU_CUDA124_v$Version.zip",
    "HS_MOSAIC_GPU_DirectML_v$Version.zip"
)
foreach ($f in $expected) {
    $path = Join-Path $Root "dist\$f"
    if (Test-Path $path) {
        $mb = [math]::Round((Get-Item $path).Length / 1MB, 1)
        Write-Host ("  OK      {0}  ({1} MB)" -f $f, $mb) -ForegroundColor Green
    } else {
        Write-Host ("  MISSING {0}" -f $f) -ForegroundColor Red
    }
}

$failed = @($results | Where-Object { $_.Exit -ne 0 }).Count
Write-Host ""
if ($failed -eq 0) {
    Write-Host "All builds succeeded. Next: smoke-test the exes." -ForegroundColor Green
    Write-Host "  .\dist\HS_MOSAIC_CPU_v$Version\HS_MOSAIC.exe"
    Write-Host "  .\dist\HS_MOSAIC_GPU_CUDA124_v$Version\HS_MOSAIC.exe --backend-self-test `$env:TEMP\hs_selftest.json"
    Write-Host "  .\dist\HS_MOSAIC_GPU_DirectML_v$Version\HS_MOSAIC.exe --backend-self-test `$env:TEMP\hs_selftest_dml.json"
    Write-Host "  (DirectML self-test: expect directml_available=true and nnls/nmf backend torch-dml;"
    Write-Host "   on this machine DirectML drives the NVIDIA card, which is fine for the smoke test.)"
    Write-Host ""
    Write-Host "IMPORTANT: build venvs ship NumPy 2.4.4 (dev has 1.26.4)." -ForegroundColor Yellow
    Write-Host "Exercise the new 0.9.8 features IN THE EXE: diagnostics window"  -ForegroundColor Yellow
    Write-Host "(SVD scree / effective rank / separability) and Purify seed."     -ForegroundColor Yellow
} else {
    Write-Host "$failed build(s) FAILED - see logs in $LogDir" -ForegroundColor Red
}
Write-Host ("=" * 70)
