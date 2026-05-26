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

- Python **3.10 or newer** (Python 3.10 is the lower bound because the codebase uses PEP 604 `X | Y` runtime annotation syntax; 3.11 and 3.12 are tested.)
- either **Conda** (recommended) or plain **pip/venv**
- a supported desktop platform: Windows, Linux, or macOS

Optional, for GPU acceleration:

- **NVIDIA GPU**: the recommended GPU path, using CUDA via PyTorch
- **AMD GPU on Linux**: potentially usable through ROCm (see [GPU notes](#gpu-notes))
- **Apple Silicon (M1/M2/M3/M4)**: NNMF and NNLS run on the Metal MPS backend (PyTorch ≥ 2.0)

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

### Pick an install variant

Five variants cover the realistic hardware setups. The choice does **not** affect the application's features — only which numerical backend the NNMF and NNLS code paths use, and where torch comes from. **For serious hyperspectral analysis, the matching GPU variant for your hardware is recommended** (CPU runs typically take minutes per field of view; GPU runs finish in seconds, and 4D z- or t-stacks multiply the cost).

| Variant | Hardware | What it installs | Dispatch label | When to use |
|---|---|---|---|---|
| **1. NVIDIA CUDA GPU** *(primary tested)* | NVIDIA GPU + driver | CUDA-enabled PyTorch from PyTorch's index (~2 GB) + hs-mosaic | `torch-cuda` | Any NVIDIA GPU machine. **Install order matters** — see admonition below. |
| **2. Apple Silicon (MPS)** | M1 / M2 / M3 / M4 Mac | macOS PyPI torch (includes MPS by default) + hs-mosaic | `torch-mps` | Any Apple Silicon Mac on macOS 12.3+. PyPI's macOS torch wheel includes the Metal backend, so no separate CUDA-style index URL is needed. |
| **3. Intel Arc (XPU)** | Intel Arc GPU on Linux/Windows | XPU-enabled PyTorch from PyTorch's index + hs-mosaic | `torch-xpu` | Intel Arc hardware with PyTorch ≥ 2.5. Same two-command order as CUDA. |
| **4. CPU only** *(fallback)* | Anything else | hs-mosaic only | `scipy-cpu` | Machines without a supported GPU — older Macs, AMD on Windows, ARM Linux without ROCm, CI runners. Functionally complete; minutes per FOV instead of seconds. |
| **5. CPU + PyTorch** *(advanced)* | Anything else | hs-mosaic + CPU PyTorch from PyPI (~150 MB) | `torch-cpu` | Niche. Sometimes faster than variant 4 for very large fixed-H NNLS mosaics (≥ 10⁶ pixels) where PyTorch's vectorised FISTA beats SciPy's per-pixel active-set. For typical images variant 4 is equal or faster. **Does not provide GPU acceleration.** |

!!! important "PyPI does NOT host CUDA or XPU PyTorch — install order matters for those variants"
    PyPI only hosts the **CPU** build of PyTorch on Linux/Windows, and the **CPU + MPS** build on macOS. CUDA wheels live on PyTorch's own index (`https://download.pytorch.org/whl/cu124` etc.); XPU wheels live at `https://download.pytorch.org/whl/xpu`. For these two variants you must install the GPU-enabled torch wheel *before* hs-mosaic. Doing it in reverse downloads ~150 MB of CPU torch that gets immediately discarded. **For the same reason, do not use `pip install "hs-mosaic[torch]"` for any GPU variant** — that extra pulls CPU torch from PyPI.

    Apple Silicon does **not** have this issue: PyPI's macOS torch wheel already includes MPS, so `pip install torch` works directly without an index URL.

Concrete commands per variant:

```bash
# Variant 1 — NVIDIA CUDA GPU. Two commands, GPU-first.
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install hs-mosaic

# Variant 2 — Apple Silicon (MPS). One command suffices on macOS.
pip install hs-mosaic torch
# (equivalent: `pip install torch && pip install hs-mosaic` — order is free on macOS
# because PyPI's macOS torch wheel includes the MPS backend, no special index needed.)

# Variant 3 — Intel Arc (XPU). Two commands, GPU-first.
pip install torch --index-url https://download.pytorch.org/whl/xpu
pip install hs-mosaic

# Variant 4 — CPU only (fallback). One command.
pip install hs-mosaic

# Variant 5 — CPU + PyTorch (advanced, see table).
pip install "hs-mosaic[torch]"
```

For variant 1, pick the `cu124` URL to match your CUDA driver: `cu118`, `cu121`, `cu124`, `cu126`, etc. — see the [PyTorch selector](https://pytorch.org/get-started/locally/). For variant 3, the XPU URL is currently a single endpoint regardless of GPU; check the [PyTorch XPU install guide](https://pytorch.org/get-started/locally/) for any updates.

Verify the GPU is detected after the install:

```bash
# Variant 1 — CUDA
python -c "import torch; print('CUDA:', torch.cuda.is_available())"

# Variant 2 — MPS (Apple Silicon)
python -c "import torch; print('MPS :', torch.backends.mps.is_available() and torch.backends.mps.is_built())"

# Variant 3 — XPU (Intel Arc)
python -c "import torch; print('XPU :', hasattr(torch, 'xpu') and torch.xpu.is_available())"
```

`True` means the corresponding GPU backend will be used; `False` means HS-MOSAIC silently falls back to CPU (still works). The fit-summary `backend` field reports `torch-cuda`, `torch-mps`, `torch-xpu`, `torch-cpu`, or `scipy-cpu` so you can see which path actually ran.

On macOS/zsh the quotes around `"hs-mosaic[torch]"` are required (zsh treats `[` as a glob); on Windows and Linux/bash they are harmless. The project page is at [pypi.org/project/hs-mosaic](https://pypi.org/project/hs-mosaic/).

### From a git clone (for development)

```bash
git clone https://github.com/manuel-kunisch/hs_crs_analysis_gui.git
cd hs_crs_analysis_gui

pip install -e .                       # editable install — picks up local edits
pip install -e ".[torch]"              # adds CPU PyTorch alongside
pip install -e ".[dev]"                # adds pytest, ruff, pyinstaller for development
```

For CUDA from a clone, install CUDA torch first (as in variant 1 above), then `pip install -e .` — the same install-order rule applies.

### Recovery — coming from `hs-mosaic[gpu]` (v0.9.2 users)

The `[gpu]` extra was renamed to `[torch]` in v0.9.3 because PyPI's torch is CPU-only and the old name was misleading. If you previously installed `hs-mosaic[gpu]` and now want CUDA, a single command replaces the CPU torch in place with the CUDA build:

```bash
pip install --upgrade --force-reinstall torch \
    --index-url https://download.pytorch.org/whl/cu124
```

## Running the Application

### Windows

From an activated Conda or venv environment:

```bash
hs-mosaic.bat
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

### Supported GPU backends — at a glance

Since v0.9.3, HS-MOSAIC's PyTorch NNMF and NNLS backends pick a device in this priority order: **CUDA → MPS → XPU → CPU**. Whichever PyTorch reports as available first gets used.

| Hardware + driver stack | Detection | Acceleration | Notes |
|---|---|---|---|
| **NVIDIA GPU + CUDA-enabled PyTorch** | `torch.cuda.is_available() == True` | ✅ Full, primary tested platform | Use the matching `cuXXX` wheel from PyTorch's index. The dispatch label in the fit summary is `torch-cuda`. |
| **AMD GPU on Linux + ROCm-built PyTorch** | `torch.cuda.is_available() == True` (ROCm maps to the CUDA namespace) | ✅ Incidental | Works without code changes but is not part of the CI matrix. Install the official AMD ROCm PyTorch build for your distro. |
| **AMD GPU on Windows** | No supported PyTorch backend | ❌ CPU only | ROCm has no Windows distribution. |
| **Apple Silicon (M1/M2/M3/M4) + MPS-enabled PyTorch** | `torch.backends.mps.is_available() == True` | ✅ Supported since v0.9.3 | The standard PyPI macOS torch wheel includes the MPS backend, so `pip install hs-mosaic torch` Just Works on Apple Silicon. Dispatch label: `torch-mps`. The Lipschitz-constant `torch.linalg.eigvalsh` call in fixed-H NNLS internally falls back to CPU for that one ~1 ms op on older PyTorch builds — negligible. |
| **Intel Arc GPU + Intel XPU PyTorch** | `torch.xpu.is_available() == True` | ✅ Supported since v0.9.3 (untested in CI) | Requires PyTorch built with XPU support (PyTorch ≥ 2.5 or IPEX). Dispatch label: `torch-xpu`. Please report issues if you have hardware to test. |
| **CPU only (any platform)** | n/a | ❌ CPU paths used | scikit-learn NMF + SciPy NNLS for the bare install; PyTorch on CPU if `[torch]` extra installed. Dispatch label: `torch-cpu` (PyTorch path) or `scipy-cpu` (bare path). |

CUDA remains the primary tested platform. MPS and XPU support is dispatch-clean (`torch_nmf.gpu_available()` returns `True`, the backend label appears as `torch-mps` or `torch-xpu` in the fit summary), but absolute throughput on those backends depends on PyTorch's own op coverage for the hardware.

### NVIDIA (Windows and Linux)

For the **pip install path**, see Option 3 above — CUDA PyTorch is installed before hs-mosaic from PyTorch's index. For the **conda install path** (Option 2 + CUDA add-on):

```bash
conda install pytorch pytorch-cuda=12.6 -c pytorch -c nvidia
```

Replace `12.6` with the version recommended by the [PyTorch selector](https://pytorch.org/get-started/locally/) for your driver. You need a compatible NVIDIA driver, but you do **not** need to install the full CUDA toolkit separately just to run the GUI.

### AMD (Linux + ROCm)

HS-MOSAIC's PyTorch paths use the `torch.cuda` API; PyTorch ROCm maps that to ROCm devices on Linux. AMD GPUs on Linux therefore work incidentally, but this is not part of the test matrix — install via the official AMD ROCm PyTorch builds. AMD on Windows is not a practical target.

### Apple Silicon (MPS)

Since v0.9.3, Apple Silicon Macs (M1/M2/M3/M4) get hardware acceleration through PyTorch's MPS backend. The standard PyPI macOS torch wheel includes MPS, so the install reduces to:

```bash
pip install hs-mosaic torch
```

(no PyTorch-index step is needed; PyPI's macOS torch wheel already includes the Metal/MPS backend.)

Verify MPS is detected:

```bash
python -c "import torch; print('MPS available:', torch.backends.mps.is_available() and torch.backends.mps.is_built())"
```

`True` → HS-MOSAIC's PyTorch NNMF and NNLS backends run on the GPU; you'll see `torch-mps` as the backend label in the fit summary. Requires macOS 12.3 or newer and PyTorch ≥ 2.0.

### Intel Arc (XPU)

Since v0.9.3, Intel Arc GPUs are picked up automatically via `torch.xpu.is_available()` when an XPU-enabled PyTorch is installed (PyTorch ≥ 2.5 with the XPU build, or the Intel Extension for PyTorch / IPEX). Dispatch label is `torch-xpu`. Untested in CI — please report issues.

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
