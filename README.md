# HS-MOSAIC

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20273076.svg)](https://doi.org/10.5281/zenodo.20273076)

**HS-MOSAIC (HyperSpectral Multivariate Optical Analysis Components) is a GUI for fast reconstruction and unmixing of hyperspectral imaging data — PCA, seeded NNMF and fixed-H NNLS, with GPU-accelerated backends and reproducible presets.**

Initially built for coherent Raman scattering (CARS, SRS) and related hyperspectral and multispectral imaging workflows, but applicable to any spectral image stack that needs non-negative unmixing.



![Demonstration of a typical hyperspectral stack stepping through its spectral channels — synthetic quickstart data shipped with the GUI](docs/assets/gifs/quick_synthetic_data_demo.gif)

*Above: a typical hyperspectral stack as it appears in HS-MOSAIC — one grayscale frame per spectral channel, with the channel slider scrolling through the cube.*

![Same dataset, four modes side by side — PCA, random NNMF, seeded NNMF, fixed-H NNLS — on the synthetic quickstart data shipped with the GUI](docs/assets/images/02_modes_comparison.png)

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
- **Publication-friendly export**: Fiji/ImageJ-compatible TIFFs, CSV spectra, and scale-bar metadata that survive into downstream figures.

## Documentation

Full documentation, including tutorials and worked examples:

**🌐 [Live docs](https://manuel-kunisch.github.io/hs_crs_analysis_gui/)** · 📂 [`docs/`](docs/index.md) in this repo

Quickest entry points:

- [Quickstart](docs/quickstart.md) — minimal end-to-end GUI workflow
- [Concepts](docs/concepts.md) — the unmixing model and the role of seeds
- [Loading data](docs/tutorials/01_loading_data.md) — TIFF conventions, 3D/4D axis selection, intensity handling
- [Analysis modes](docs/tutorials/02_analysis_modes.md) — which mode to choose and what to expect
- [Seeds, spectra, and W maps](docs/tutorials/03_seeds_spectral_and_spatial.md) — building H and W seeds
- [Presets and reproducibility](docs/tutorials/06_presets_and_reproducibility.md) — saving and restoring the full analysis state
- [NNMF and NNLS methods](docs/methods/nnmf_nnls_modes.md) — math, convergence criteria, references
- [Workflow checklist](docs/tutorials/07_workflow_checklist.md) — single-page reminder for a publication-grade run
- [Troubleshooting](docs/troubleshooting.md) — known issues and their fixes

To build the docs locally:

```bash
pip install -r docs-requirements.txt
mkdocs serve
```

## Install

###  PyPI:
The package is published on PyPI as `hs-mosaic`. Install in a virtual environment with pip:

```bash
pip install hs-mosaic
```

### From source:
Detailed installation guide and platform-specific notes: [docs/installation.md](docs/installation.md).

**Prerequisites** — Python ≥ 3.11 on Windows, Linux, or macOS. Optionally an NVIDIA GPU (or ROCm-capable AMD on Linux) for PyTorch acceleration.

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
pip install -e ".[gpu]"             # add CPU PyTorch (NNMF MU + FISTA-NNLS backends)
pip install -e ".[dev]"             # add ruff, pytest, pyinstaller for development
```

For a CUDA-enabled PyTorch install, follow the [official PyTorch selector](https://pytorch.org/get-started/locally/) *after* the editable install — PyPI hosts CPU-only torch wheels, so CUDA builds come from `https://download.pytorch.org/whl/cu124` (or the version matching your driver). The GPU paths use the standard `torch.cuda` device convention; CUDA 12.6 is the recommended target when available. See [GPU acceleration](docs/tutorials/02a_gpu_acceleration.md) for the backend and platform notes, including Apple Silicon and AMD/ROCm.

## Run

After a pip install (editable or from PyPI) the GUI is reachable through the `hs-mosaic` console entry point or as a Python module:

```bash
hs-mosaic                    # console / shortcut launcher
python -m hs_mosaic          # equivalent module form
```

On Windows you can also use the bundled launcher (which calls `python -m hs_mosaic` under the hood):

```bash
hs_mosaic.bat
```

A pre-built standalone Windows executable is described in [docs/standalone_windows.md](docs/standalone_windows.md).

## At a glance

![Auto-suggested ROIs on synthetic microbead data — spatial detection followed by Ward hierarchical clustering on spectral fingerprints](docs/assets/gifs/03_suggest_rois_beads.gif)

The screenshot above demonstrates the **Suggest ROIs** tool on the bead dataset. The same GUI handles seed building, NNMF/NNLS analysis, and result export. See [docs/tutorials/03c_suggest_rois.md](docs/tutorials/03c_suggest_rois.md) for the algorithm and settings reference.

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
hs_mosaic.bat                       Windows launcher (calls `python -m hs_mosaic`)
```

## Repository status

HS-MOSAIC is a research software project under active development. The documented workflows are intended for reproducible image analysis, but users should validate settings and outputs for their own datasets before publication.

## Citation

If you use HS-MOSAIC in published work, please cite the Zenodo record and include the exact release tag or commit you used. GitHub can generate a citation from [`CITATION.cff`](CITATION.cff).

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

HS-MOSAIC is licensed under the **GNU General Public License v3.0 or later** (`GPL-3.0-or-later`). See [`LICENSE`](LICENSE).

The source code is distributed under GPL-3.0-or-later because the application uses PyQt5, which is available under GPLv3 or a commercial Riverbank license. Documentation and project media should be cited using the software citation above unless a file states otherwise.

## Acknowledgements

HS-MOSAIC builds on the scientific Python and Qt ecosystem, including NumPy, SciPy, scikit-image, scikit-learn, tifffile, matplotlib, pyqtgraph, PyQt5, QtAwesome, and optional PyTorch backends. Please also cite the method references listed in the documentation when they are relevant to your analysis.
