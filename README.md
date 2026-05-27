# HS-MOSAIC

[![PyPI version](https://img.shields.io/pypi/v/hs-mosaic?label=PyPI&cacheSeconds=300&v=2)](https://pypi.org/project/hs-mosaic/)
[![Python versions](https://img.shields.io/pypi/pyversions/hs-mosaic?cacheSeconds=300&v=2)](https://pypi.org/project/hs-mosaic/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20273076.svg)](https://doi.org/10.5281/zenodo.20273076)

**HS-MOSAIC (HyperSpectral Multivariate Optical Analysis Components) is a GUI for fast reconstruction and unmixing of hyperspectral imaging data — PCA, seeded NNMF and fixed-H NNLS, with GPU-accelerated backends and reproducible presets.**

Initially built for coherent Raman scattering (CARS, SRS) and related hyperspectral and multispectral imaging workflows, but applicable to any spectral image stack that needs non-negative unmixing.



![Demonstration of a typical hyperspectral stack stepping through its spectral channels — synthetic quickstart data shipped with the GUI](https://raw.githubusercontent.com/manuel-kunisch/hs_crs_analysis_gui/main/docs/assets/gifs/quick_synthetic_data_demo.gif)

*Above: a typical hyperspectral stack as it appears in HS-MOSAIC — one grayscale frame per spectral channel, with the channel slider scrolling through the cube.*

![Same dataset, four modes side by side — PCA, random NNMF, seeded NNMF, fixed-H NNLS — on the synthetic quickstart data shipped with the GUI](https://raw.githubusercontent.com/manuel-kunisch/hs_crs_analysis_gui/main/docs/assets/images/02_modes_comparison.png)

*Above: the same synthetic dataset analyzed with each of the four available modes. PCA misses peaks, random NNMF mixes components, seeded NNMF and fixed-H NNLS recover the underlying blob spectra.*

> [!IMPORTANT]
> HS-MOSAIC is under active development. For published analyses, cite the exact release tag or commit hash you used so the processing workflow remains reproducible.

---

## Why HS-MOSAIC?

- **Four analysis modes in one workflow**: PCA for variance-based diagnostics, random NNMF for unguided exploration, seeded NNMF for the main guided workflow, and fixed-H NNLS for spectral seed stability, particularly in 4D cross-slice / cross-time.
- **Seed-first interaction**: draw ROIs, load reference spectra, build Gaussian resonance models, or let the auto-suggester scan the image. Every seed source feeds the same H/W building pipeline.
- **3D and 4D stacks**: per-slice or fast multislice (NNMF on a reference slice → NNLS everywhere else) for time series and z-stacks.
- **Optional GPU acceleration** via PyTorch with CPU fallback (scikit-learn NMF, SciPy NNLS).
- **Reproducible by construction**: presets save the full analysis state, ROI configuration, and seed choices. Reload the same TIFF, reload the preset, get the same result.
- **Publication-friendly export**: Fiji/ImageJ-compatible TIFFs, CSV spectra, LUT presets, and scale-bar metadata that survive into downstream figures.

## Documentation

Full documentation, including tutorials and worked examples:

**🌐 [Live docs](https://manuel-kunisch.github.io/hs_crs_analysis_gui/)** · 📂 [`docs/`](https://github.com/manuel-kunisch/hs_crs_analysis_gui/tree/main/docs) in this repo

Quickest entry points:

- [Quickstart](https://manuel-kunisch.github.io/hs_crs_analysis_gui/quickstart/) — minimal end-to-end GUI workflow
- [Concepts](https://manuel-kunisch.github.io/hs_crs_analysis_gui/concepts/) — the unmixing model and the role of seeds
- [Loading data](https://manuel-kunisch.github.io/hs_crs_analysis_gui/tutorials/01_loading_data/) — TIFF conventions, 3D/4D axis selection, intensity handling
- [Analysis modes](https://manuel-kunisch.github.io/hs_crs_analysis_gui/tutorials/02_analysis_modes/) — which mode to choose and what to expect
- [Seeds, spectra, and W maps](https://manuel-kunisch.github.io/hs_crs_analysis_gui/tutorials/03_seeds_spectral_and_spatial/) — building H and W seeds
- [Presets and reproducibility](https://manuel-kunisch.github.io/hs_crs_analysis_gui/tutorials/06_presets_and_reproducibility/) — saving and restoring the full analysis state
- [NNMF and NNLS methods](https://manuel-kunisch.github.io/hs_crs_analysis_gui/methods/nnmf_nnls_modes/) — math, convergence criteria, references
- [Workflow checklist](https://manuel-kunisch.github.io/hs_crs_analysis_gui/tutorials/07_workflow_checklist/) — single-page reminder for a publication-grade run
- [Troubleshooting](https://manuel-kunisch.github.io/hs_crs_analysis_gui/troubleshooting/) — known issues and their fixes

To build the docs locally:

```bash
pip install -r docs-requirements.txt
mkdocs serve
```

## Install

###  PyPI:
The package is published on PyPI as `hs-mosaic`. Install in a virtual environment with pip.

**Recommended — GPU install (the right one for your hardware):**

Hyperspectral NNMF and fixed-H NNLS are heavy: typical fields of view (~10⁶ pixels × tens of channels) run in seconds on a GPU and in minutes on a CPU, with 4D z- and t-stacks multiplying the cost. Since v0.9.3 HS-MOSAIC supports three GPU backends — pick the one matching your hardware:

```bash
# NVIDIA CUDA GPU — install CUDA torch from PyTorch's index FIRST, then hs-mosaic.
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install hs-mosaic

# Apple Silicon (M1/M2/M3/M4) — PyPI's macOS torch wheel already includes MPS.
pip install hs-mosaic torch

# Intel Arc GPU — install XPU torch from PyTorch's index FIRST, then hs-mosaic.
pip install torch --index-url https://download.pytorch.org/whl/xpu
pip install hs-mosaic
```

> [!IMPORTANT]
> **PyPI does not host CUDA-enabled or XPU-enabled PyTorch wheels** — only CPU torch (and CPU+MPS on macOS). For the NVIDIA and Intel variants you must install GPU-enabled torch from PyTorch's own index **before** `pip install hs-mosaic`. The order is **not optional**: doing it in reverse downloads ~150 MB of CPU torch that gets immediately replaced. Apple Silicon does NOT have this issue because PyPI's macOS torch already includes MPS. This is a property of the whole Python packaging ecosystem (every GPU-accelerated package has the same constraint), not of HS-MOSAIC.

> [!WARNING]
> **Apple Silicon users: check your Python architecture before installing.** If your Python is the legacy x86_64 (Intel) build running under Rosetta 2, `pip install hs-mosaic torch` will silently pin `torch` at the last x86_64 macOS wheel (`2.2.2`, NumPy-1-era) while installing NumPy 2.x alongside, producing an `_ARRAY_API not found` error on launch. **Run this check before installing:**
>
> ```bash
> python -c "import platform; print(platform.machine())"
> ```
>
> `arm64` = native, good to go. `x86_64` = Rosetta'd Intel Python — install a native arm64 Python (Miniforge or the arm64 Anaconda installer) first; the telltale path for the wrong build is `/Users/<you>/opt/anaconda3/`. See [docs/installation.md → Apple Silicon (MPS)](https://manuel-kunisch.github.io/hs_crs_analysis_gui/installation/#apple-silicon-mps) for the full diagnostic, the fix, and a one-line `numpy<2` workaround if you can't reinstall conda right now.

For NVIDIA, pick the `cu124` URL to match your CUDA driver — `cu118`, `cu121`, `cu124`, `cu126`, etc. — using the [PyTorch selector](https://pytorch.org/get-started/locally/).

Verify the right GPU is detected after the install:

```bash
python -c "import torch; print('CUDA:', torch.cuda.is_available()); print('MPS :', torch.backends.mps.is_available() and torch.backends.mps.is_built()); print('XPU :', hasattr(torch, 'xpu') and torch.xpu.is_available())"
```

Whichever line says `True` is the GPU backend HS-MOSAIC will use. The fit-summary `backend` field reports `torch-cuda`, `torch-mps`, or `torch-xpu` so you can confirm in the GUI.

**Fallback — CPU install (no supported GPU):**

For machines without a compatible GPU (e.g. AMD on Windows, ARM Linux without ROCm, CI runners, older Macs), HS-MOSAIC runs on CPU using scikit-learn's NMF and SciPy's NNLS. It works correctly but expect minutes per run instead of seconds.

```bash
pip install hs-mosaic
```

> A `[torch]` extra also exists for users who want the PyTorch FISTA-NNLS backend on CPU (sometimes faster than SciPy's per-pixel solver for very large fixed-H NNLS mosaics). It does **not** provide GPU acceleration on its own. See [docs/installation.md](https://manuel-kunisch.github.io/hs_crs_analysis_gui/installation/) for the full comparison table and for the v0.9.2 → v0.9.3 `[gpu]` → `[torch]` rename recovery instructions.

### From source:
Detailed installation guide and platform-specific notes: [docs/installation.md](https://manuel-kunisch.github.io/hs_crs_analysis_gui/installation/).

**Prerequisites** — Python ≥ 3.10 on Windows, Linux, or macOS. Optionally a supported GPU for PyTorch acceleration: NVIDIA (CUDA), Apple Silicon (MPS), Intel Arc (XPU), or AMD on Linux (ROCm).

**Conda (recommended)** — use one of the packaged environment files in the repository root:

```bash
# Lean CPU-only environment
conda env create -f environment.yml
conda activate hs-mv-analysis

# Or: with PyTorch for the optional PyTorch NNMF/NNLS backends
conda env create -f environment-pytorch.yml
conda activate hs-mv-analysis-pytorch
```

Use the bundled `environment.yml` unless you specifically need the PyTorch-based backends. The bundled `environment-pytorch.yml` installs PyTorch, but it does not guarantee a CUDA-enabled build on every machine. For NVIDIA GPU acceleration, install a CUDA-enabled PyTorch build that matches your driver and platform after creating the environment from the `.yml` file.

**pip** — alternative if you prefer venv. The project is packaged; install the package itself rather than just its requirements file:

```bash
python -m venv .venv
.venv\Scripts\activate              # Windows
# source .venv/bin/activate         # Linux / macOS
pip install -e .                    # editable install from a clone
```


Optional extras:

```bash
pip install -e ".[torch]"           # add CPU PyTorch (NNMF MU + FISTA-NNLS backends)
pip install -e ".[dev]"             # add ruff, pytest, pyinstaller for development
```

For a CUDA-enabled PyTorch install, follow the [official PyTorch selector](https://pytorch.org/get-started/locally/) *after* the editable install — PyPI hosts CPU-only torch wheels, so CUDA builds come from `https://download.pytorch.org/whl/cu124` (or the version matching your driver). The GPU paths use the standard `torch.cuda` device convention; CUDA 12.6 is the recommended target when available. See [GPU acceleration](https://manuel-kunisch.github.io/hs_crs_analysis_gui/tutorials/02a_gpu_acceleration/) for the backend and platform notes, including Apple Silicon and AMD/ROCm.

## Run

After a pip install (editable or from PyPI) the GUI is reachable through the `hs-mosaic` console entry point or as a Python module:

```bash
hs-mosaic                    # console / shortcut launcher
python -m hs_mosaic          # equivalent module form
```

On Windows you can also use the bundled launcher (which calls `python -m hs_mosaic` under the hood):

```bash
hs-mosaic.bat
```

A pre-built standalone Windows executable is described in [docs/standalone_windows.md](https://manuel-kunisch.github.io/hs_crs_analysis_gui/standalone_windows/).

## At a glance

![Auto-suggested ROIs on synthetic microbead data — spatial detection followed by Ward hierarchical clustering on spectral fingerprints](https://raw.githubusercontent.com/manuel-kunisch/hs_crs_analysis_gui/main/docs/assets/gifs/03_suggest_rois_beads.gif)

The screenshot above demonstrates the **Suggest ROIs** tool on the bead dataset. The same GUI handles seed building, NNMF/NNLS analysis, and result export. See [docs/tutorials/03c_suggest_rois.md](https://manuel-kunisch.github.io/hs_crs_analysis_gui/tutorials/03c_suggest_rois/) for the algorithm and settings reference.

## Repository layout

```text
hs_mosaic/                          Top-level Python package (pip-installable)
├── app.py                          Application entry point — exports main()
├── __main__.py                     Enables `python -m hs_mosaic`
├── composite_image.py              Result / composite viewer
├── assets/                         Bundled icons and example metadata
└── widgets/                        Internal modules
    ├── analysis_manager.py         Analysis setup, seed handling, 4D orchestration
    ├── multivariate_analyzer.py    PCA / NNMF / NNLS core
    ├── torch_nmf.py                Optional PyTorch MU-NMF backend
    ├── nnls_pytorch.py             Optional PyTorch FISTA-NNLS backend
    ├── roi_manager_pg.py           ROI management and ROI plotting
    └── data_widgets.py             Raw-data loading and image viewer
pyproject.toml                      Package metadata, deps, hs-mosaic entry point
docs/                               User documentation (mkdocs site)
environment.yml                     Conda environment, CPU-only
environment-pytorch.yml             Conda environment, with PyTorch
requirements.txt                    pip-based dependencies (legacy; pyproject.toml is authoritative)
hs_crs_analysis_gui_cpu.spec        PyInstaller spec for standalone CPU build
hs_crs_analysis_gui_pytorch.spec    PyInstaller spec for standalone PyTorch / CUDA build
build_windows_cpu.ps1               Build script for the standalone CPU zip
build_windows_pytorch.ps1           Build script for the standalone PyTorch / CUDA zip
hs-mosaic.bat                       Windows launcher (calls `python -m hs_mosaic`)
```

## Repository status

HS-MOSAIC is a research software project under active development. The documented workflows are intended for reproducible image analysis, but users should validate settings and outputs for their own datasets before publication.

## Citation

If you use HS-MOSAIC in published work, please cite the Zenodo record and include the exact release tag or commit you used. GitHub can generate a citation from [`CITATION.cff`](https://github.com/manuel-kunisch/hs_crs_analysis_gui/blob/main/CITATION.cff).

Preliminary DOI: [10.5281/zenodo.20273076](https://doi.org/10.5281/zenodo.20273076)

```bibtex
@software{kunisch_hs_mosaic,
  author = {Kunisch, Manuel},
  title = {{HS MOSAIC} - A GUI for fast reconstruction and unmixing of hyperspectral imaging data},
  doi = {10.5281/zenodo.20273076},
  url = {https://github.com/manuel-kunisch/hs_crs_analysis_gui},
  note = {Please cite the exact release tag or commit hash used},
  year = {2026}
}
```

## License

Copyright (C) 2026 Manuel Kunisch.

HS-MOSAIC is licensed under the **GNU General Public License v3.0 or later** (`GPL-3.0-or-later`). See [`LICENSE`](https://github.com/manuel-kunisch/hs_crs_analysis_gui/blob/main/LICENSE).

The source code is distributed under GPL-3.0-or-later because the application uses PyQt5, which is available under GPLv3 or a commercial Riverbank license. Documentation and project media should be cited using the software citation above unless a file states otherwise.

## Acknowledgements

HS-MOSAIC builds on the scientific Python and Qt ecosystem, including NumPy, SciPy, scikit-image, scikit-learn, tifffile, matplotlib, pyqtgraph, PyQt5, QtAwesome, and optional PyTorch backends. Please also cite the method references listed in the documentation when they are relevant to your analysis.
