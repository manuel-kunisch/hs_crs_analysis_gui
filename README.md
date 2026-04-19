# HS MV Analysis

> [!IMPORTANT]
> Replace the placeholder sections in this README with your project-specific text before publishing.

## Overview

**[TODO: short project description]**

This repository contains a graphical user interface for loading, exploring, and analyzing hyperspectral CRS/CARS data.

**[TODO: 2-4 sentences describing the scientific goal, target users, and what makes this project useful.]**

## Features

- Load hyperspectral image stacks and associated spectral metadata
- Interactively define and manage ROIs
- Generate and inspect spectral/spatial seeds for NNMF workflows
- Run PCA and NNMF analysis from the GUI
- View component maps, spectra, and composite images
- Save presets, export spectra, and reuse imported result components as seed inputs

**[TODO: add or remove bullets so they match the actual scope you want to present publicly.]**

## Screenshots

**[TODO: add screenshots or GIFs here]**

Example:

```md
![Main GUI](docs/main_window.png)
```

## Documentation

Full tutorials and workflow documentation live in [`docs/`](docs/index.md).

Recommended starting points:

- [`Quickstart`](docs/quickstart.md): minimal end-to-end GUI workflow
- [`Concepts`](docs/concepts.md): unmixing model, seeds, NNMF, and fixed-H NNLS
- [`Tutorials`](docs/tutorials/01_loading_data.md): step-by-step GUI usage
- [`Examples`](docs/examples/reproduce_figure_1.md): figure-linked and modality-specific workflows
- [`Reference`](docs/reference/nnmf_nnls_modes.md): feature-specific notes

**[TODO: publish these docs with GitHub Pages / MkDocs once the tutorials contain screenshots, GIFs, and example data links.]**

## Repository Status

**[TODO: add project status if desired, e.g. active development / research prototype / internal tool / stable release.]**

## Installation

### Prerequisites

Before installation, users should have:

- Python **3.11 or newer**
- either **Conda** or plain **pip/venv**
- a supported desktop platform:
  - Windows
  - Linux
  - macOS

Optional, for GPU acceleration:

- **NVIDIA GPU**: recommended for the current PyTorch GPU path in this repository
- **AMD GPU on Linux**: potentially usable through ROCm
- **Apple Silicon**: the GUI should run, but this repository currently does not use the `mps` backend automatically

Useful links:

- PyTorch install selector: https://pytorch.org/get-started/locally/
- NVIDIA CUDA downloads: https://developer.nvidia.com/cuda-downloads
- NVIDIA driver downloads: https://www.nvidia.com/Download/index.aspx
- PyTorch Apple MPS notes: https://docs.pytorch.org/docs/stable/notes/mps.html
- PyTorch ROCm / HIP notes: https://docs.pytorch.org/docs/stable/notes/hip.html

### Which Environment File Should I Use?

- `environment.yml`
  - lean Conda setup
  - recommended for normal CPU usage
  - no PyTorch included
- `environment-pytorch.yml`
  - Conda setup with PyTorch included
  - recommended if you want to use the optional PyTorch-based NNMF / NNLS paths
  - good base for later adding NVIDIA CUDA support
  - CUDA does not need to be installed separately just to run the GUI, but you will need a CUDA-enabled PyTorch build for GPU acceleration
- `requirements.txt`
  - pip-based installation instead of Conda (not recommended)
  - simplest fallback if you do not want to use Conda

### Option 1: Conda environment without PyTorch

Recommended for a lean setup that uses the standard CPU/scikit-learn/SciPy fallbacks.

```bash
conda env create -f environment.yml
conda activate hs-mv-analysis
```

### Option 2: Conda environment with PyTorch

Recommended if you want the optional PyTorch-based NNMF / NNLS paths.
This environment gives you PyTorch, but not necessarily a CUDA-enabled build by itself.

```bash
conda env create -f environment-pytorch.yml
conda activate hs-mv-analysis-pytorch
```

Note:

If you need a specific CUDA-enabled PyTorch build for a particular GPU, you may want to adjust the PyTorch installation using the official PyTorch installation selector.

### Option 3: pip / requirements.txt

If you do not want to use Conda:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Optional PyTorch installation afterward:

```bash
pip install torch
```

## GPU Acceleration and Platform Notes

### NVIDIA GPUs on Windows / Linux

This project currently uses PyTorch GPU acceleration only through the `cuda` device path in the optional NNMF / NNLS backends.

Practical recommendation:

- use the `environment-pytorch.yml` environment
- for NVIDIA acceleration, install a CUDA-enabled PyTorch build afterward
- for this project, prefer **CUDA 12.6**

Why CUDA 12.6:

- the official PyTorch "Get Started" page currently lists stable builds for CUDA `11.8`, `12.6`, and `12.8`
- `12.6` is a good conservative recommendation for this repository: modern, well-supported, and less aggressive than simply chasing the newest option

Important:

For normal PyTorch usage, you usually do **not** need to install the full NVIDIA CUDA toolkit separately just to run this GUI. In practice, you mainly need:

- a compatible NVIDIA driver
- a CUDA-enabled PyTorch build

Official links:

- PyTorch install selector: https://pytorch.org/get-started/locally/
- NVIDIA CUDA downloads: https://developer.nvidia.com/cuda-downloads
- NVIDIA driver downloads: https://www.nvidia.com/Download/index.aspx


Example pip install inside the PyTorch environment:

```bash
pip install --upgrade torch --index-url https://download.pytorch.org/whl/cu126
```

Or, if you want to follow the official Conda-style PyTorch packaging route:

```bash
conda install pytorch pytorch-cuda=12.6 -c pytorch -c nvidia
```

Verification:

```bash
python -c "import torch; print('torch:', torch.__version__); print('cuda available:', torch.cuda.is_available()); print('torch cuda:', torch.version.cuda)"
```

If `torch.cuda.is_available()` prints `True`, the current code should be able to use the PyTorch GPU path.

### Apple Silicon / macOS

PyTorch itself supports Apple Silicon acceleration through the `mps` backend on supported macOS systems.

However, this repository does **not** currently select `mps` in its own PyTorch backend code. The current implementation checks CUDA availability and otherwise falls back to CPU.

So, today:

- the GUI should still run on Apple Silicon
- the PyTorch parts should still install
- but the custom PyTorch NNMF / NNLS acceleration paths in this project will currently behave as **CPU-only**, unless the code is extended

To add proper Apple GPU support later, the project would need to detect and route to `mps`, especially in:

- `contents/torch_nmf.py`
- `contents/nnls_pytorch.py`
- `contents/multivariate_analyzer.py`

### AMD GPUs

For AMD GPUs, the best path is **Linux + ROCm + PyTorch ROCm**.

This is promising for this project because official PyTorch ROCm uses the same `torch.cuda` Python-level semantics, and this repository already uses the `cuda` device naming convention in its PyTorch backend code.

So in practice:

- **AMD on Linux with ROCm**: potentially workable with the current code, and this is the most likely non-NVIDIA GPU route
- **AMD on Windows**: not a realistic target for this PyTorch path right now; use CPU unless you test a working alternative backend

### Intel and Other GPU Backends

There is no dedicated support in this repository for Intel GPU backends or other non-CUDA/non-ROCm accelerators.

For those systems, assume:

- the GUI itself can still run
- the analysis will still work
- PyTorch acceleration should be considered **unsupported unless explicitly adapted and tested**

### Keep This Section Updated

CUDA / ROCm / PyTorch packaging changes over time. Before publishing a release, it is worth re-checking the official PyTorch installation page:

- https://pytorch.org/get-started/locally/
- https://docs.pytorch.org/docs/stable/notes/mps
- https://docs.pytorch.org/docs/stable/notes/hip.html

## Running the Application

### Windows

From an activated environment:

```bash
run_hs_crs_analysis_gui.bat
```

### Direct Python launch

```bash
python main.py
```

## Exporting a Reproducible Conda Environment

If you want to share the exact environment from a machine where the GUI is already working:

```bash
conda env export --no-builds > environment.full.yml
```

This is the best compromise between reproducibility and avoiding overly machine-specific build strings.

A leaner export based only on explicitly requested packages is:

```bash
conda env export --from-history > environment.min.yml
```

## Project Structure

```text
main.py                         Main application entry point
composite_image.py              Result/composite viewer
contents/analysis_manager.py    Analysis setup and seed handling
contents/data_widgets.py        Raw-data loading and image viewer wiring
contents/roi_manager_pg.py      ROI management and ROI plotting
contents/multivariate_analyzer.py Core PCA / NNMF logic
docs/                           Tutorial and reference documentation
docs/tutorials/                 Step-by-step workflow tutorials
docs/examples/                  Dataset-specific and figure-linked examples
docs/reference/                 Feature-specific reference notes
environment.yml                 Conda environment without PyTorch
environment-pytorch.yml         Conda environment with PyTorch
requirements.txt                pip-based core dependencies
run_hs_crs_analysis_gui.bat     Windows launcher
```

## Usage Notes

- The PyTorch backends are optional. If PyTorch is not installed, the code falls back to the non-PyTorch implementations where supported.
- Presets, ROI state, and imported dummy ROI seed rows are intended to support iterative analysis workflows.
- Some functionality is optimized for Windows/PyQt usage, especially the provided batch launcher.

**[TODO: add any data-format assumptions, instrument-specific notes, or known workflow caveats.]**

## Citation

**[TODO: add paper / preprint / thesis / DOI / how you want the software cited.]**

## License

**[TODO: add the project license here, e.g. MIT / GPL-3.0 / proprietary / internal academic use only.]**

If you plan to publish this on GitHub, it is better to add an actual `LICENSE` file as well.

## Acknowledgements

**[TODO: add collaborators, institutes, funding, datasets, or upstream packages you want to acknowledge.]**
