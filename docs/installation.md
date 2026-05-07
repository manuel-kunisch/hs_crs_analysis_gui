# Installation

This page covers all installation paths for HS MV Analysis.

## Prerequisites

Before installation, you need:

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

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
```

Optional PyTorch installation:

```bash
pip install torch
```

## Running the Application

### Windows

From an activated Conda or venv environment:

```bash
run_hs_crs_analysis_gui.bat
```

### Direct Python launch (all platforms)

```bash
python main.py
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

- Ensure the Conda environment is activated before running.
- On Linux, install the required Qt system libraries. The exact package names depend on the distro but typically include `libxcb-*` and `libGL` libraries.

**`ModuleNotFoundError: No module named 'tifffile'` or similar**:

- The environment was not activated, or installation was incomplete. Re-run `conda env create` or `pip install -r requirements.txt`.

**CUDA not detected after installing PyTorch**:

- The installed PyTorch build may not match the driver. Check `torch.version.cuda` and compare with the installed driver version.
- See the [PyTorch install selector](https://pytorch.org/get-started/locally/) for the right build.

**`wavelength.json` not detected**:

- The file must be named exactly `wavelength.json` (lowercase) and placed in the **same folder** as the TIFF file, not a parent folder. See [Spectral axis and wavelength.json](reference/spectral_axis_and_wavelength_json.md).
