# Full Python Installation

This page covers the full Python-based installation of HS-MOSAIC.

Use this route when you want to run from source, modify the project, use Linux/macOS, or manage the Python environment yourself.

If you only want to run the GUI on Windows and do not want to install Python, use the [Standalone Windows .exe](standalone_windows.md) instead. The standalone `.exe` packages already contain Python and the required dependencies.

## Choose Your Install Route

| Route | Best for | Python install needed? | Page |
|---|---|---:|---|
| Standalone Windows `.exe` | Windows users who only want to run the GUI, including optional NVIDIA/CUDA packages | No | [Standalone Windows .exe](standalone_windows.md) |
| Full Python installation | Developers, source-code users, Linux/macOS users, custom environments | Yes | This page |

## Prerequisites

For the full Python installation, you need:

- Python **3.11 or newer**
- either **Conda** (recommended) or plain **pip/venv**
- a supported desktop platform: Windows, Linux, or macOS

Optional, for GPU acceleration:

- **NVIDIA GPU**: the recommended GPU path, using CUDA via PyTorch
- **AMD GPU on Linux**: potentially usable through ROCm (see [GPU notes](#gpu-notes))
- **Apple Silicon**: the GUI runs, but the PyTorch acceleration paths currently fall back to CPU

## Which Environment File Should I Use?

| File | Use |
|---|---|
| `environment.yml` | Lean Conda setup, CPU-only, no PyTorch |
| `environment-pytorch.yml` | Conda setup with PyTorch, needed for optional GPU/accelerated backends |
| `requirements.txt` | pip-based fallback if Conda is unavailable |

Use `environment.yml` unless you specifically need the PyTorch-based NNMF or NNLS backends.

## Option 1: Conda without PyTorch (recommended for most users)

```bash
conda env create -f environment.yml
conda activate hs-mv-analysis
```

## Option 2: Conda with PyTorch

```bash
conda env create -f environment-pytorch.yml
conda activate hs-mv-analysis-pytorch
```

This installs PyTorch but does not automatically give you a CUDA-enabled build. For NVIDIA GPU acceleration, add a CUDA-enabled PyTorch build afterward (see [GPU notes](#gpu-notes)).

## Option 3: pip / venv

The project ships as a proper Python package named **`hs-mosaic`**. Start by creating and activating a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux / macOS
```

Then install the package by one of two routes.

### 3a. From PyPI (recommended — once published)

```bash
pip install hs-mosaic                 # CPU-only
pip install "hs-mosaic[gpu]"          # adds CPU PyTorch (NNMF MU + FISTA-NNLS backends)
```

!!! note "PyPI availability"
    Publishing of `hs-mosaic` to PyPI is in progress. Until the first PyPI release is
    live, install from a git clone (Option 3b) — the resulting environment is identical.

### 3b. From a git clone

```bash
git clone https://github.com/manuel-kunisch/hs_crs_analysis_gui.git
cd hs_crs_analysis_gui

pip install -e .                      # editable install — picks up local edits
pip install -e ".[gpu]"               # add CPU PyTorch alongside
pip install -e ".[dev]"               # add pytest, ruff, pyinstaller for development
```

### CUDA-enabled PyTorch (NVIDIA GPUs)

In either case, PyPI only hosts the CPU build of PyTorch. To enable CUDA acceleration of the NNMF and NNLS backends, install a matching CUDA torch wheel *after* the package install:

```bash
pip install --upgrade --force-reinstall torch \
    --index-url https://download.pytorch.org/whl/cu124   # or the URL matching your driver
```

See [GPU acceleration](tutorials/02a_gpu_acceleration.md) for the backend and platform notes, including Apple Silicon and AMD/ROCm.

## Running the Application

### Windows

From an activated Conda or venv environment:

```bash
hs_mosaic.bat
```

The launcher calls `python -m hs_mosaic` under the hood.

### Direct launch (all platforms)

After `pip install`:

```bash
hs-mosaic                     # console / shortcut launcher
python -m hs_mosaic           # equivalent module form
```

> Screenshot placeholder: first successful GUI startup, showing the main window after launch and the empty data-loading area.

## GPU Notes

### NVIDIA (Windows and Linux)

The PyTorch NNMF and NNLS backends use the `cuda` device when available. To enable this:

1. Install the `environment-pytorch.yml` environment.
2. Add a CUDA-enabled PyTorch build that matches your system. Use the [PyTorch install selector](https://pytorch.org/get-started/locally/) for the current command.

Example pip install for a CUDA 12.6 build:

```bash
pip install --upgrade torch --index-url https://download.pytorch.org/whl/cu126
```

Example Conda install for a CUDA 12.6 build:

```bash
conda install pytorch pytorch-cuda=12.6 -c pytorch -c nvidia
```

Replace the CUDA version in these examples with the version recommended by the PyTorch selector for your driver and platform.

Verify CUDA is detected:

```bash
python -c "import torch; print(torch.cuda.is_available())"
```

`True` means the GPU backends in the project can use the CUDA path.

You need a compatible NVIDIA driver, but you do **not** need to install the full CUDA toolkit separately just to run the GUI.

### AMD (Linux + ROCm)

The project uses `torch.cuda` semantics internally, which PyTorch ROCm also maps to on Linux. This means AMD + ROCm on Linux is the most likely non-NVIDIA GPU path to work without code changes. AMD on Windows is not a practical target with the current PyTorch backend.

### Apple Silicon

The GUI runs on Apple Silicon. The analysis falls back to CPU because the project does not currently route to the `mps` backend. This may be improved in a future update.

## Exporting a Reproducible Environment

To share the exact environment from a working machine:

```bash
conda env export --no-builds > environment.full.yml
```

A leaner export based only on explicitly requested packages:

```bash
conda env export --from-history > environment.min.yml
```

## Common Installation Problems

**Qt plugin error on startup** (`Could not find or load the Qt platform plugin`):

- Ensure the Conda or venv environment is activated before running.
- On Linux, install the required Qt system libraries — typically `libxcb-*` and `libGL` packages from your distro.
- On Windows, the most common root cause is a missing **Microsoft Visual C++ 2015–2022 Redistributable (x64)** — install it from [Microsoft's download page](https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist) and reboot.
- If the error persists after the above, see the full [Qt platform plugin troubleshooting](troubleshooting.md#qt-platform-plugin-error) section — it covers forced PyQt5 reinstall, setting `QT_QPA_PLATFORM_PLUGIN_PATH`, and the last-resort manual install of standalone Qt 5.15 with the matching `PATH` entries on Windows.

**`ModuleNotFoundError: No module named 'tifffile'` or similar**:

- The environment was not activated, or installation was incomplete. Re-run `conda env create` or `pip install -r requirements.txt`.

**CUDA not detected after installing PyTorch**:

- The installed PyTorch build may not match the driver. Check `torch.version.cuda` and compare with the installed driver version.
- See the [PyTorch install selector](https://pytorch.org/get-started/locally/) for the right build.

**`wavelength.json` not detected**:

- The file must be named exactly `wavelength.json` (lowercase) and placed in the **same folder** as the TIFF file, not a parent folder. See [Spectral axis and wavelength.json](reference/spectral_axis_and_wavelength_json.md).
