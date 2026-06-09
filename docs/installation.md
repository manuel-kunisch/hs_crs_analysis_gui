# Installation

HS-MOSAIC ships as a regular Python package on PyPI. **For almost every user the recommended install is a `pip install hs-mosaic` into a virtual environment bacause it is platform-independent.** Conda environment files are still provided for users who prefer that workflow, and a pre-built standalone Windows `.exe` (including a CUDA build) is provided for Windows users who do not want to install Python at all.

!!! tip "TL;DR — pick one"
    * **Any platform, you have Python ≥ 3.10**: `pip install hs-mosaic` into a venv. Important: add CUDA / XPU torch *before* `hs-mosaic` if you have an NVIDIA or Intel Arc GPU. See [Default install: pip](#default-install-pip) below.
    * **Windows, you do not want to install Python at all, and you have an NVIDIA GPU**: download the pre-built [Standalone Windows .exe (CUDA build)](standalone_windows.md). One zip, double-click to run, GPU acceleration included.
    * **Apple Silicon Mac, you do not want to install Python**: download the pre-built [Standalone macOS .dmg](#standalone-macos-apple-silicon-dmg). Metal/MPS GPU acceleration included.
    * **You prefer Conda / Mamba**: see [Alternative: Conda](#alternative-conda) below. The pip route works inside a Conda env too.

## Choose Your Install Route

| Route | Best for | Python install needed? | Page |
|---|---|---:|---|
| **pip install hs-mosaic** *(default)* | Any platform with Python ≥ 3.10 — Windows, Linux, macOS, Apple Silicon, Intel Arc | Yes | This page, [Default install: pip](#default-install-pip) |
| **Standalone Windows .exe** | Windows users who do not want to install Python; CUDA build available | No | [Standalone Windows .exe](standalone_windows.md) |
| **Standalone macOS .dmg** | Apple Silicon Mac users who do not want to install Python; Metal/MPS GPU included | No | This page, [Standalone macOS](#standalone-macos-apple-silicon-dmg) |
| **Conda** | Users who already manage scientific Python environments via Conda / Mamba | Yes | This page, [Alternative: Conda](#alternative-conda) |
| **From source (editable install)** | Developers, contributors, anyone modifying the code | Yes | This page, [From a git clone](#from-a-git-clone-for-development) |

## Standalone macOS (Apple Silicon) .dmg

Apple Silicon Macs (M1/M2/M3/M4) have a pre-built download for users who do not want to install Python: `HS_MOSAIC_AppleSilicon_v0.9.6.dmg`. Open the DMG and drag **HS-MOSAIC** into **Applications**. GPU acceleration via Metal (MPS) is included; no Python or PyTorch setup is required.

### First launch: "Apple could not verify..." / "unidentified developer"

The app is not signed with a paid Apple Developer ID, so on the **first** launch macOS Gatekeeper blocks it with a message such as *"HS-MOSAIC.app cannot be opened because Apple cannot check it for malicious software"* (or *"unidentified developer"*). This is expected for an unsigned app and does not mean anything is wrong with it. Use one of the two methods below (the old Control-click → **Open** trick has been removed for unsigned apps on recent macOS, so it no longer works).

**Method 1 — System Settings (no Terminal):**

1. Double-click **HS-MOSAIC** in **Applications** once. macOS blocks it; click **Done**.
2. Open **System Settings → Privacy & Security** and scroll to the **Security** section.
3. Click **Open Anyway** next to the message about HS-MOSAIC, then authenticate (Touch ID or password).
4. Click **Open** in the final confirmation dialog.

**Method 2 — Terminal:** remove the quarantine flag, then open the app normally:

```bash
xattr -dr com.apple.quarantine /Applications/HS-MOSAIC.app
```

You only need to do either of these once. After that, double-clicking launches the app normally.

Requires macOS 12.3 or newer (for the Metal/MPS GPU backend). If you would rather not use the standalone build, `pip install hs-mosaic torch` gives the same MPS acceleration on Apple Silicon.

## Prerequisites

- Python **3.10 or newer** (Python 3.10 is the lower bound because the codebase uses PEP 604 `X | Y` runtime annotation syntax; 3.11 and 3.12 are tested).
- A supported desktop platform: Windows, Linux, or macOS.
- Optional, for GPU acceleration:
    - **NVIDIA GPU** — the recommended GPU path, using CUDA via PyTorch.
    - **Apple Silicon (M1/M2/M3/M4)** — NNMF and NNLS run on the Metal MPS backend (PyTorch ≥ 2.0). The standard PyPI macOS torch wheel already includes MPS.
    - **Intel Arc** — XPU-enabled PyTorch (≥ 2.5) gives hardware acceleration on Arc cards.
    - **AMD GPU on Linux** — potentially usable through ROCm; see [GPU notes](#gpu-notes).

## Default install: pip

The project is published on PyPI as **`hs-mosaic`** ([pypi.org/project/hs-mosaic](https://pypi.org/project/hs-mosaic/)). Start by creating and activating a virtual Python environment, then run the install commands below.
### Step 1 — install GPU-enabled torch first (if you have a GPU)

Skip this step if you do not have a supported GPU; the next step alone gives a working CPU-only install.

```bash
# NVIDIA CUDA GPU — install CUDA torch from PyTorch's index FIRST.
pip install torch --index-url https://download.pytorch.org/whl/cu124

# Intel Arc (XPU) — install XPU torch from PyTorch's index FIRST.
pip install torch --index-url https://download.pytorch.org/whl/xpu

# Apple Silicon (MPS) — PyPI's macOS torch wheel already includes MPS, just:
pip install torch
```

!!! warning "Install order matters for CUDA and XPU — not optional"
    PyPI hosts only the **CPU** build of PyTorch on Linux/Windows. CUDA wheels live on PyTorch's own index (`https://download.pytorch.org/whl/cu124` etc.); XPU wheels live at `https://download.pytorch.org/whl/xpu`. **For these two variants you must install the GPU-enabled torch wheel *before* `hs-mosaic`.** Doing it in reverse downloads ~150 MB of CPU torch that then gets immediately discarded. **For the same reason, do not use `pip install "hs-mosaic[torch]"` for any GPU variant** — that extra pulls CPU torch from PyPI.

    Apple Silicon does not have this issue: PyPI's macOS torch wheel already includes MPS, so order is free.

For NVIDIA, pick the `cu124` URL to match your CUDA driver — `cu118`, `cu121`, `cu124`, `cu126`, etc. — using the [PyTorch selector](https://pytorch.org/get-started/locally/).

### Step 2 — install hs-mosaic

```bash
pip install hs-mosaic
```

### Step 3 — verify

```bash
python -c "import torch; print('CUDA:', torch.cuda.is_available()); print('MPS :', torch.backends.mps.is_available() and torch.backends.mps.is_built()); print('XPU :', hasattr(torch, 'xpu') and torch.xpu.is_available())"
```

Whichever line says `True` is the GPU backend HS-MOSAIC will use. The fit-summary `backend` field in the GUI reports `torch-cuda`, `torch-mps`, `torch-xpu`, `torch-cpu`, or `scipy-cpu` so you can confirm which path actually ran. All `False` means the install is CPU-only and that is fine — see [Performance settings](#cpu-recommended-performance-settings) below for how to keep CPU runs tolerable.

### What does pip install actually give you?

The bare `pip install hs-mosaic` pulls only the dependencies needed to run the GUI: NumPy, SciPy, scikit-learn, scikit-image, tifffile, matplotlib, pyqtgraph, PyQt5, QtAwesome. It does **not** pull PyTorch, because PyTorch is an optional accelerator and a ~2 GB GPU wheel should never be auto-installed. The CPU fallback (scikit-learn NMF + SciPy NNLS) runs correctly without torch.

The five practical install variants are summarised below; the recommended one for your hardware is whichever GPU variant matches.

| Variant | Hardware | What it installs | Install command(s) | Dispatch label | When to use |
|---|---|---|---|---|---|
| **1. NVIDIA CUDA GPU** *(primary tested)* | NVIDIA GPU + driver | CUDA-enabled PyTorch from PyTorch's index (~2 GB) + hs-mosaic | `pip install torch --index-url https://download.pytorch.org/whl/cu124`<br>`pip install hs-mosaic` | `torch-cuda` | Any NVIDIA GPU machine. **Install order matters** (see warning above). |
| **2. Apple Silicon (MPS)** | M1 / M2 / M3 / M4 Mac | macOS PyPI torch (includes MPS by default) + hs-mosaic | `pip install torch`<br>`pip install hs-mosaic` | `torch-mps` | Any Apple Silicon Mac on macOS 12.3+. PyPI's macOS torch wheel includes the Metal backend, so no separate index URL is needed. |
| **3. Intel Arc (XPU)** | Intel Arc GPU on Linux/Windows | XPU-enabled PyTorch from PyTorch's index + hs-mosaic | `pip install torch --index-url https://download.pytorch.org/whl/xpu`<br>`pip install hs-mosaic` | `torch-xpu` | Intel Arc hardware with PyTorch ≥ 2.5. Same two-command order as CUDA. |
| **4. CPU only** *(fallback)* | Anything else | hs-mosaic only | `pip install hs-mosaic` | `scipy-cpu` | Machines without a supported GPU (older Macs, AMD on Windows, ARM Linux without ROCm, CI runners). Functionally complete; minutes per FOV instead of seconds. |
| **5. CPU + PyTorch** *(advanced)* | Anything else | hs-mosaic + CPU PyTorch from PyPI (~150 MB) | `pip install hs-mosaic torch` | `torch-cpu` | Niche. Sometimes faster than variant 4 for very large fixed-H NNLS mosaics (≥ 10⁶ pixels) where PyTorch's vectorized FISTA beats SciPy's per-pixel active-set. For typical images variant 4 is equal or faster. **Does not provide GPU acceleration.** |

On macOS / zsh the quotes around `"hs-mosaic[torch]"` are required (zsh treats `[` as a glob); on Windows and Linux/bash they are harmless.

### CPU-recommended performance settings

!!! important "Recommended Analysis-panel settings for CPU-only machines"
    The HS-MOSAIC defaults are tuned for a GPU. On a CPU-only install (variant 4 or 5, or any machine where the verify command above returned all `False`), reduce work per run so an exploratory pass stays in the seconds-to-tens-of-seconds range instead of minutes. Walk these settings up only once you are happy with the seed and result layout and want a publication-grade reconstruction.

    | Setting | CPU recommendation | GPU recommendation | Notes |
    |---|---|---|---|
    | **Spatial binning** | **≥ 2** for exploration | 1 (default) | Each doubling of binning cuts the pixel count 4×. Set in the data area before analysis. |
    | **W-seed downsample factor** *(Performance column, v0.9.4+)* | 4 (default) or 8 | **4 (default)** | Block-mean downsample for NNLS / selective-score W-seed (and residual H-seed) estimation; quality cosine similarity ~0.9999 vs full-res at 4. Set 1 for exact pre-v0.9.4 reproduction (and for sharp Fixed-H NNLS maps). See [Analysis modes → Performance column](tutorials/02_analysis_modes.md#performance-column-v094). |
    | **NNMF max iterations** | **250** for exploration | 1000 (default) | Raise back to 1000 (or higher) for the final publication-grade run; check the fit summary to see whether the lower cap was iteration-limited. |
    | **NNLS max iterations** | **250** for exploration | 1000 (default) | Same logic. |
    | **NNMF solver** | `mu` (default) | `mu` (default) | The PyTorch MU path is the one that benefits from GPU; on CPU, scikit-learn `mu` is used automatically. |
    | **Use torch.compile (MU)** | Off | Off, or On if Triton is installed | Inconsistent on CPU; opt-in. |

    **Workflow: confirm settings on a fast pass before the slow one.** Pick seeds, palette, component count, and W-seed mode using the *exploration* column above so each run finishes in seconds. Only after the layout is what you want, restore binning to 1 and iterations to 1000 and do **one** quality reconstruction. The W-seed downsample can stay at its default 4 — it is near-lossless for the seed — or drop to 1 for an exact full-resolution seed (use 1 for Fixed-H NNLS, where the W maps are the final result). On a CPU this single high-quality pass can take several minutes per field of view — that is fine because it is the only run that has to.

    On GPU, the defaults are already optimal; the recommended Performance-column entries (W-seed downsample 4 by default, patience 1, torch.compile off unless Triton is installed) are documented in [Analysis modes → Performance column](tutorials/02_analysis_modes.md#performance-column-v094).

### From a git clone (for development)

```bash
git clone https://github.com/manuel-kunisch/hs_crs_analysis_gui.git
cd hs_crs_analysis_gui

pip install -e .                       # editable install — picks up local edits
pip install -e ".[torch]"              # adds CPU PyTorch alongside
pip install -e ".[dev]"                # adds pytest, ruff, pyinstaller for development
```

For CUDA from a clone, install CUDA torch first (as in Step 1 above), then `pip install -e .` — the same install-order rule applies.

### Recovery — coming from `hs-mosaic[gpu]` (v0.9.2 users) or a CPU torch install

The `[gpu]` extra was renamed to `[torch]` in v0.9.3 because PyPI's torch is CPU-only and the old name was misleading. If you previously installed `hs-mosaic[gpu]` and now want CUDA, a single command replaces the CPU torch in place with the CUDA build:

```bash
pip install --upgrade --force-reinstall torch \
    --index-url https://download.pytorch.org/whl/cu124
```

Replace the index URL with the one matching your CUDA version. For Apple Silicon, just `pip install --upgrade --force-reinstall torch` is enough since the MPS-enabled torch wheel is already on PyPI.
For Intel Arc, use the XPU index URL instead.

## Alternative: Conda

Conda is supported as an alternative but is no longer the default. Use this if you already manage scientific Python with Conda / Mamba and want to keep that workflow.

| File | Use |
|---|---|
| `environment.yml` | Lean Conda setup, CPU-only, no PyTorch |
| `environment-pytorch.yml` | Conda setup with PyTorch, needed for optional GPU/accelerated backends |
| `requirements.txt` | pip-based fallback if Conda is unavailable |

### Conda without PyTorch

```bash
conda env create -f environment.yml
conda activate hs-mv-analysis
```

### Conda with PyTorch

```bash
conda env create -f environment-pytorch.yml
conda activate hs-mv-analysis-pytorch
```

This installs PyTorch but does **not** automatically give you a CUDA-enabled build. For NVIDIA GPU acceleration, add a CUDA-enabled PyTorch build afterward:

```bash
conda install pytorch pytorch-cuda=12.6 -c pytorch -c nvidia
```

Replace `12.6` with the version recommended by the [PyTorch selector](https://pytorch.org/get-started/locally/) for your driver. You need a compatible NVIDIA driver, but you do **not** need to install the full CUDA toolkit separately just to run the GUI.

You can also use the pip route *inside* a Conda environment if you prefer — `pip install hs-mosaic` works just as well there as in a venv.

## Running the Application

After any of the above installs, the GUI is reachable through the `hs-mosaic` console entry point or as a Python module:

```bash
hs-mosaic                     # console / shortcut launcher
python -m hs_mosaic           # equivalent module form
```

On Windows there is also a bundled launcher that calls `python -m hs_mosaic`:

```bash
hs-mosaic.bat
```

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

### Apple Silicon (MPS)

Since v0.9.3, Apple Silicon Macs (M1/M2/M3/M4) get hardware acceleration through PyTorch's MPS backend. The standard PyPI macOS torch wheel includes MPS, so the install reduces to:

```bash
pip install hs-mosaic torch
```

(no PyTorch-index step is needed; PyPI's macOS torch wheel already includes the Metal/MPS backend.)

!!! danger "Important: your Python must be a native arm64 build, not an x86_64 build running under Rosetta"
    The single most common Apple Silicon install failure is silently running an x86_64 Python under Apple's Rosetta 2 translation layer instead of the native arm64 build. The symptoms look like a NumPy bug but are actually a Python-architecture problem:

    * pip can only resolve `torch` up to **2.2.2** the last x86_64 macOS wheel PyTorch ever shipped. (Modern arm64 macOS torch is 2.3+, currently ~2.12.)
    * That `torch==2.2.2` wheel was compiled against NumPy 1.x, but pip installs NumPy 2.x alongside.
    * On launch you get:
      ```
      UserWarning: Failed to initialize NumPy: _ARRAY_API not found
      A module that was compiled using NumPy 1.x cannot be run in NumPy 2.x
      ```
      raised from `torch/nn/modules/transformer.py`.

    **Why it's so easy to miss:** the Intel Anaconda installer (the default download up until a few years ago) installs to `/Users/<you>/opt/anaconda3/`. The `opt/` in the path is the giveaway — it's the legacy Intel layout. Many Apple Silicon users still have this from a years-old install and don't realise their Python is being translated through Rosetta on every launch.

    **Check before you install** (one command, takes a second):

    ```bash
    python -c "import platform; print(platform.machine())"
    ```

    | Output | Verdict |
    |---|---|
    | `arm64` | ✅ Native Apple Silicon Python — proceed with `pip install hs-mosaic torch` below. |
    | `x86_64` | ❌ Rosetta'd Intel Python — `pip install hs-mosaic torch` will silently install the broken `torch==2.2.2` + NumPy 2 combo. Fix this **before** installing — see "Fixing it" below. |

    **Fixing it (recommended):** install a native arm64 Python distribution. Either:

    * **Miniforge** (lightweight, conda-compatible) — download from <https://github.com/conda-forge/miniforge>; the `Miniforge3-MacOSX-arm64.sh` installer is the one you want.
    * **Anaconda for Apple Silicon** — at <https://www.anaconda.com/download>; pick the arm64 / Apple Silicon installer explicitly (the default page may still serve the Intel build first).

    Then create a fresh environment from the arm64 base and `pip install hs-mosaic torch` inside it. With native arm64 Python, pip resolves a modern torch wheel built against NumPy 2 and everything works — bonus: MPS acceleration becomes available automatically (it isn't on Rosetta'd torch).

    **Quick workaround if you can't reinstall conda right now:** pin NumPy below 2 so the ABI matches the old torch 2.2.2 wheel:

    ```bash
    pip install "numpy<2" --force-reinstall
    ```

    This keeps you on `torch==2.2.2` without GPU acceleration (the x86_64 torch wheels never had MPS), but it removes the `_ARRAY_API not found` error so the application launches. Not recommended long-term — fix the Python architecture properly when you can.

**Verify the install worked** (run this from your activated env):

```bash
python -c "import platform, numpy, torch; print('arch:', platform.machine()); print('numpy:', numpy.__version__); print('torch:', torch.__version__); print('mps available:', torch.backends.mps.is_available())"
```

Expected output on a healthy native arm64 install:

```
arch: arm64
numpy: 2.x        (e.g. 2.4.6)
torch: 2.3+        (e.g. 2.12.0)
mps available: True
```

If you see `arch: x86_64` or `torch: 2.2.2`, you are on the broken Rosetta'd combo — return to "Fixing it" above. Otherwise launch the app:

```bash
hs-mosaic
```

It should start without any `_ARRAY_API not found` warning or NumPy ABI error. Requires macOS 12.3 or newer for MPS. The fit-summary `backend` field will read `torch-mps` once you run an analysis.

### Intel Arc (XPU)

Since v0.9.3, Intel Arc GPUs are picked up automatically via `torch.xpu.is_available()` when an XPU-enabled PyTorch is installed (PyTorch ≥ 2.5 with the XPU build, or the Intel Extension for PyTorch / IPEX). Dispatch label is `torch-xpu`. Untested in CI — please report issues.

### AMD (Linux + ROCm)

HS-MOSAIC's PyTorch paths use the `torch.cuda` API; PyTorch ROCm maps that to ROCm devices on Linux. AMD GPUs on Linux therefore work incidentally, but this is not part of the test matrix. Please install via the official AMD ROCm PyTorch builds. AMD on Windows is not a practical target.

## Exporting a Reproducible Environment

To share the exact environment from a working machine:

```bash
conda env export --no-builds > environment.full.yml
```

A leaner export based only on explicitly requested packages:

```bash
conda env export --from-history > environment.min.yml
```

For pip-based environments, `pip freeze > requirements-frozen.txt` plays the same role.

## Common Installation Problems

**Qt plugin error on startup** (`Could not find or load the Qt platform plugin`):

- Ensure the Conda or venv environment is activated before running.
- On Linux, install the required Qt system libraries — typically `libxcb-*` and `libGL` packages from your distro.
- On Windows, the most common root cause is a missing **Microsoft Visual C++ 2015–2022 Redistributable (x64)** — install it from [Microsoft's download page](https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist) and reboot.
- If the error persists after the above, see the full [Qt platform plugin troubleshooting](troubleshooting.md#qt-platform-plugin-error) section — it covers forced PyQt5 reinstall, setting `QT_QPA_PLATFORM_PLUGIN_PATH`, and the last-resort manual install of standalone Qt 5.15 with the matching `PATH` entries on Windows.

**`ModuleNotFoundError: No module named 'tifffile'` or similar**:

- The environment was not activated, or installation was incomplete. Re-run `pip install hs-mosaic` (or `conda env create`) inside the activated environment.

**CUDA not detected after installing PyTorch**:

- The installed PyTorch build may not match the driver. Check `torch.version.cuda` and compare with the installed driver version.
- See the [PyTorch install selector](https://pytorch.org/get-started/locally/) for the right build.


