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

## Repository Status

**[TODO: add project status if desired, e.g. active development / research prototype / internal tool / stable release.]**

## Installation

### Option 1: Conda environment without PyTorch

Recommended for a lean setup that uses the standard CPU/scikit-learn/SciPy fallbacks.

```bash
conda env create -f environment.yml
conda activate hs-mv-analysis
```

### Option 2: Conda environment with PyTorch

Recommended if you want the optional PyTorch-based NNMF / NNLS paths.

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
