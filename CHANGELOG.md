# Changelog

All notable user-facing changes to HS-MOSAIC are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/).

## [0.9.2] — 2026-05-24

### Added
- The application is now distributable as a pip-installable Python package
  (`pip install hs-mosaic`), with an `hs-mosaic` console entry point that
  launches the GUI without invoking a script directly.
- Optional dependency extras: `[gpu]` (CPU PyTorch backend for MU-NMF and
  FISTA-NNLS) and `[dev]` (PyInstaller, ruff, pytest).
- `python -m hs_mosaic` is supported as an equivalent module-style launch.

### Changed
- Source restructured into a single top-level package, `hs_mosaic/`, with
  the previous `contents/` directory becoming `hs_mosaic/widgets/`, and
  the previous root-level `main.py` and `composite_image.py` moving inside
  the package. Bundled assets (logo, etc.) moved to `hs_mosaic/assets/`.
- PyInstaller spec files and the Windows launcher updated to match the new
  layout; standalone Windows builds (`HS_MOSAIC_*_v0.9.2.zip`) regenerated.
- Documentation install and launch commands updated throughout (`README.md`,
  `docs/installation.md`, `docs/quickstart.md`, `docs/troubleshooting.md`,
  `docs/examples/synthetic_quickstart.md`, `docs/standalone_windows.md`).

### Removed
- Two leftover learning scripts (`pyqt_overview.py`, `pyqtgraph_test.py`)
  that were never imported by the application.

## [0.9.1] — 2026

Last release before the package restructure. Adds the live "Composite (from
analysis)" projection mirror in the raw image viewer, the Save / Load
Histogram and Spectra Preset workflow for cross-FOV reproducibility,
documentation polish (Essentials TL;DR, stitching internals, results page),
and assorted seed-construction and stitching improvements (cosine blending
profile, per-tile intensity matching, H-seed unity normalisation).

## [0.9.0] — 2026

Initial public release of HS-MOSAIC: seeded NNMF and fixed-H NNLS for
hyperspectral and multispectral microscopy data, with optional NVIDIA-CUDA
PyTorch backend and 4D processing support.
