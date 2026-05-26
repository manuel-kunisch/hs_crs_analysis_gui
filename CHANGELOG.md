# Changelog

All notable user-facing changes to HS-MOSAIC are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/).

## [0.9.3] — 2026-05-24

### Added
- **Color-blind-safe component palette.** Two new bidirectionally-synced
  **Palette** dropdowns (one in the result-viewer toolbar next to *Save
  Histogram and Spectra Preset*, one in the ROI Manager next to *Load
  Lookup Table and Spectra Preset*) let users switch between the new
  default **Okabe-Ito** palette (designed for protanopia and deuteranopia; Wong, *Nat. Methods* **8**, 441, 2011),
  a **High-Contrast** palette (also designed for colour vision deficiencies), and the legacy
  **Classic RGB** palette that HS-MOSAIC shipped before v0.9.3. The
  selected palette is persisted in the application JSON preset.
  Custom palettes can be added by editing the `PALETTES` /
  `PALETTE_LABELS` dictionaries in `hs_mosaic/widgets/color_manager.py`
  — see *Results and export → Default colour palette → Adding a custom
  palette* in the docs.

### Changed
- **Default component-colour palette switched to Magenta–Cyan–Yellow.**
  Fresh sessions and new analyses now use the additive-secondary trio
  (magenta + cyan + yellow) as components 1, 2, 3 by default, with five
  supplementary colours filling slots 4–8. This palette gives the highest
  three-way contrast on a black composite background of any three-colour
  combination. The previous "High contrast" magenta-green palette and the
  Okabe-Ito palette remain available in the dropdown. Per-component colour
  choices made with the colour pickers (and colours loaded from any
  `.preset`) always override the palette and are not affected.
- **Palette dropdown now shows `(customized)` when colours diverge from the
  active palette's baseline.** Modifying any component colour via the
  picker tags the current palette in both dropdowns as e.g.
  *"Magenta–Cyan–Yellow (max contrast) (customized)"*; switching palette
  or re-applying the same palette resets the tag. The custom colour values
  themselves persist through preset save/load via the existing ROI and
  histogram serialisation, so a customised palette round-trips through
  `Save Preset` / `Load Preset` correctly.
- **Confirmed minimum Python version is 3.10.**
- Renamed the Windows launcher from `hs_mosaic.bat` to `hs-mosaic.bat` for
  consistency with the PyPI package name (`hs-mosaic`) and the console-script
  command (`hs-mosaic`).
- README and docs now use absolute URLs for embedded images and cross-links
  so they render correctly on the PyPI project page in addition to GitHub.
- **Renamed the optional `[gpu]` install extra to `[torch]`.** The previous
  name was misleading: PyPI only hosts CPU PyTorch, so `pip install
  "hs-mosaic[gpu]"` never gave GPU acceleration — it just added the
  PyTorch backend running on CPU. The new `[torch]` name reflects what is
  actually installed. For real NVIDIA-CUDA GPU acceleration, the
  recommended path is now to install CUDA-enabled torch from PyTorch's
  index **first**, then `pip install hs-mosaic`; see the *CUDA-enabled
  PyTorch* section of the installation docs. **Breaking change for v0.9.2
  users who scripted `pip install "hs-mosaic[gpu]"`** — they need to
  switch to `[torch]` or drop the extra entirely. A one-command recovery
  path is documented in README → Install → PyPI.

### Backwards compatibility
- Application JSON presets saved before v0.9.3 do **not** carry a
  `palette_name` field. When such a legacy preset is loaded, HS-MOSAIC
  falls back to the **Classic RGB** palette, preserving the visual identity
  of the original session. New presets always serialise the active palette
  name explicitly.

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
