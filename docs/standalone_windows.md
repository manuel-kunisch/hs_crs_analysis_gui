# Standalone Windows .exe

This page is the Windows install guide for users who want to run HS-MOSAIC without installing Python.

The standalone packages are portable zip files. Each zip contains the application, Python, and the required Python packages. Users do not need Conda, pip, venv, PyTorch, or a project checkout.

Use the [full Python installation](installation.md) instead when you want to run from source, modify the code, use Linux/macOS, or manage the Python environment yourself.

## Choose A Package

| Package | Use this when | Python required? | GPU acceleration? |
|---|---|---:|---:|
| `HS_MOSAIC_CPU_vX.Y.Z.zip` | Most users want the normal CPU workflow. | No | No |
| `HS_MOSAIC_PyTorch_CPU_vX.Y.Z.zip` | Users want the optional PyTorch NNMF backend, but only on CPU. | No | No |
| `HS_MOSAIC_GPU_CUDA124_vX.Y.Z.zip` | Users want PyTorch GPU acceleration on a compatible NVIDIA GPU. | No | Yes, through CUDA 12.4 PyTorch |

For most users, start with `HS_MOSAIC_CPU_vX.Y.Z.zip`.

Use the CUDA PyTorch package only when the computer has a compatible NVIDIA GPU and a recent NVIDIA driver. The CUDA package is much larger because it bundles CUDA-enabled PyTorch.

## Install The Portable App

1. Download the chosen zip file.
2. Extract the whole zip to a normal writable folder, for example `Downloads`, `Documents`, or a lab software folder.
3. Open the extracted folder.
4. Double-click `HS_MOSAIC.exe`.

!!! warning "Do not move the `.exe` out of the extracted folder"
    Keep `HS_MOSAIC.exe` next to its `_internal` folder. The `.exe` alone is not a complete application, and moving it to the Desktop or another folder will break the portable app.

    To start HS-MOSAIC from the Desktop, create a Windows shortcut instead: right-click `HS_MOSAIC.exe`, choose **Show more options** if needed, then choose **Send to > Desktop (create shortcut)**. You can also right-click the `.exe` and use **Create shortcut**, then move only the shortcut.

Do not run executables from the repository `build/` folder. That folder is temporary PyInstaller output. The distributable application is the portable zip or the unpacked folder inside `dist/`.

## First Launch On Windows

Windows SmartScreen may show a warning because the application is not code-signed. If you trust the source of the build, choose **More info** and then **Run anyway**.

If antivirus software scans the folder on first launch, startup may be slower the first time.

## CUDA And NVIDIA GPU Support

End users do not rebuild the application for their GPU. The same CUDA zip can be used on different compatible NVIDIA GPUs.

Users do not need to install the CUDA Toolkit. The CUDA runtime libraries used by PyTorch are bundled in the CUDA package.

Users do need a compatible NVIDIA driver. For the `CU124` package, use an NVIDIA driver that supports CUDA 12.4. On Windows, driver version `551.61` or newer is a practical minimum. Newer NVIDIA drivers are normally compatible.

The CUDA package is intended for NVIDIA GPUs. AMD, Intel, and Apple GPUs are not CUDA devices and will not use the CUDA backend on Windows.

If CUDA is not available on a user's computer, the application can still open. PyTorch NNMF falls back to CPU PyTorch, and fixed-H NNLS falls back to the CPU SciPy path.

## How To Use The GPU Backend

The GPU backend is used by the PyTorch multiplicative-update NNMF path and by fixed-H NNLS when CUDA is available.

In the GUI:

1. Choose **NNMF**.
2. Set **Solver** to **Multiplicative Updates (mu)**.
3. Set **Backend** to **Prefer GPU** (the default).
4. Run the analysis.

The **Coordinate Descent (cd)** solver always uses the scikit-learn CPU backend. This is expected behavior.

## Loading Data

The portable app can load TIFF stacks and metadata from any normal user folder. Data files do not need to be inside the application folder.

If a TIFF has a matching spectral-axis metadata file, keep `wavelength.json` in the same folder as the TIFF. See [Spectral axis and wavelength.json](reference/spectral_axis_and_wavelength_json.md).

## Updating The App

To update to a newer release, download and extract the new portable zip. Existing data files do not need to be moved into the application folder.

Presets and exported result files are normal files. Keep them wherever your workflow stores analysis outputs.

## Common Problems

**The app says `python312.dll` is missing.**

The `.exe` was moved away from its `_internal` folder, or an executable from the temporary `build/` folder was launched. Extract the whole portable zip again and run the `.exe` from the extracted folder.

**The CUDA package opens but does not use the GPU.**

Check that the computer has an NVIDIA GPU and a recent NVIDIA driver. In the GUI, use the **Multiplicative Updates (mu)** solver and the **Prefer GPU** backend (default since v0.9.4). The **Coordinate Descent (cd)** solver is CPU-only regardless of backend setting.

**The CUDA package is very large.**

This is expected. CUDA-enabled PyTorch includes large runtime libraries. Use the normal CPU package when GPU acceleration is not needed.

**Windows blocks the first launch.**

Unsigned applications can trigger SmartScreen. Choose **More info** and **Run anyway** if the build came from a trusted source.

## Rebuilding After Project Changes

This section is for release maintainers, not end users. End users should download a portable zip and do not run the PowerShell build scripts.

Rebuild a standalone package whenever the executable should include source-code or dependency changes.

Rebuild when any of these changed:

- Python source files, such as `.py` files.
- PyInstaller files, such as `.spec` files.
- Build scripts, such as `build_windows_*.ps1`.
- Runtime dependencies in `requirements.txt`.
- The PyTorch target, for example switching between CPU PyTorch and CUDA PyTorch.
- Bundled application assets, such as the `.ico` file.

Documentation-only changes do not require rebuilding the `.exe`, unless the documentation is being published as part of the same release package.

## Release Build Commands

Run all commands from the repository root in PowerShell.

Build the normal CPU package:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows_cpu.ps1
```

For a release version, pass the version explicitly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows_cpu.ps1 -Version 0.9.3
```

Build the PyTorch CPU package:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows_pytorch.ps1
```

Build a CUDA PyTorch package by installing a CUDA-enabled PyTorch wheel into the build environment:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows_pytorch.ps1 -TorchIndexUrl https://download.pytorch.org/whl/cu124 -RequireCuda -Version 0.9.3
```

`-RequireCuda` makes the build fail if the build environment cannot import CUDA-enabled PyTorch and see a CUDA device.

If CUDA PyTorch already works in an existing Conda environment, build from that interpreter:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows_pytorch.ps1 -SkipInstall -RequireCuda -PythonExeOverride C:\path\to\env\python.exe -TorchIndexUrl https://download.pytorch.org/whl/cu124 -Version 0.9.3
```

In this form, `-TorchIndexUrl` is used to label the output zip, for example `CUDA124`. The actual PyTorch build comes from the supplied Python interpreter.

Use `-SkipInstall` only when dependencies are already correct. Do not use `-SkipInstall` after changing dependencies or switching between CPU and CUDA PyTorch.

Add `-NoZip` when only the unpacked `dist/` folder is needed.

## Release Checklist

Before sharing a zip:

1. Build from the intended commit or working tree.
2. Start the packaged `.exe`.
3. Confirm the main window opens.
4. For CUDA builds, run the packaged backend self-test and confirm `torch-cuda` for NNMF and NNLS.
5. Load a small TIFF stack.
6. Run a small PCA or NNMF test.
7. Export a result file.
8. Test the zip on a Windows machine without the project Python environment.

The clean-machine test is the most important packaging check. It catches missing DLLs and hidden imports that may be masked on the development computer.

Backend self-test command for CUDA builds:

```powershell
.\dist\HS_MOSAIC_GPU_CUDA124_v0.9.3\HS_MOSAIC.exe --backend-self-test $env:TEMP\hs_backend_selftest.json
Get-Content $env:TEMP\hs_backend_selftest.json
```

A working CUDA package reports `cuda_available: true`, `nmf_backend: torch-cuda`, `nnls_backend: torch-cuda`, and `ok: true`.
