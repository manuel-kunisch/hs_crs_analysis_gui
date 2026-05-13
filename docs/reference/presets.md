# Presets

Presets store the full analysis session state and make workflows reproducible. There are two preset types: the **main JSON preset** and the **result-viewer `.preset` file**. Both are described here.

For a workflow-oriented introduction, see [Presets and reproducibility](../tutorials/06_presets_and_reproducibility.md).

## Main JSON Preset

The main JSON preset is the most complete snapshot of a GUI session. Save it with **Save Preset** in the analysis panel.

### What it stores

| Section | Fields |
|---|---|
| Data | `image_path`, `binning_factor`, `current_slice_index` |
| Physical units | `fov`, `unit` (nm / um / mm) |
| Spectral axis | `wavenumber_widget` (source mode, unit, pump/Stokes settings, custom values, custom labels), `wavenumbers` (derived array) |
| Analysis settings | `num_components`, `analysis_method`, `custom_initialization`, `nnmf_solver` (mu / cd), `nnmf_backend` (Automatic / CPU only / Prefer GPU), `nnmf_max_iter`, `nnls_max_iter` |
| Seed settings | `seed_init_settings` (`w_seed_mode`, `overwrite_existing_w_from_h`, `normalize_h_to_unity`, `seed_pixel_metric`, fixed-H and 4D fast-mode flags, result scaling flag) |
| Resonance / spectral seeds | `resonance_settings` |
| Stitching | `stitch_manager` (pattern, binning, overlaps) |
| ROI manager | `roi_manager` (all ROI rows: geometry, component, color, spectrum, flags) |
| Display | `labels`, histogram / LUT state |

### What it does not store

- The raw image data itself (only the file path).
- Rolling-ball correction reference TIFF payload (only the correction parameters).
- Temporary analysis results or in-progress W/H matrices.

### Loading a preset

Load the preset via **Load Preset** in the analysis panel. The GUI:

1. Restores all stored settings.
2. Tries to reload the image from the stored `image_path`. If the path is stale (file moved or renamed), the rest of the preset still loads; the image must be opened manually.
3. Checks whether the spectral axis length in the preset matches the loaded image. If not, a warning is shown.

### Dataset compatibility

Presets are most useful when applied to the same dataset or a dataset with identical dimensions and spectral axis. Cross-dataset transfer works for:

- ROI seeds (if the image size is the same),
- spectral seeds (resampled to match the target axis),
- display settings (colors, labels, histograms).

Cross-dataset transfer does not automatically work for:

- ROI geometry if the image resolution changed,
- spectral axis if the channel count or axis range differs.

---

## Result-Viewer `.preset` File

The result-viewer `.preset` is a lighter snapshot focused on display settings and seed spectra. It is saved from the result viewer.

### What it stores

- Component colors (one per component).
- Histogram / LUT ranges for each component.
- Saved H spectra.
- Spectral axis values at the time of saving.

### What it does not store

- Full ROI geometry.
- Physical units.
- 4D slice selection.
- Solver settings or preprocessing choices.

### Loading a `.preset`

Load it from the ROI Manager. The GUI asks how it should be applied:

**LUTs Only**: applies the saved colors and histogram levels to the current components without changing ROIs.

**LUTs + ROIs**: applies colors and levels *and* imports the saved spectra as dummy ROI rows in the ROI Manager.

Use **LUTs Only** to reuse a carefully styled color scheme on a new analysis result. Use **LUTs + ROIs** to transfer seed spectra from one session to a new dataset.

---

## Solver and Backend Fields

The main preset stores solver and backend choices. These affect how NNMF and NNLS are executed.

| Field | Values | Meaning |
|---|---|---|
| `nnmf_solver` | `mu`, `cd` | Multiplicative Update (default) or Coordinate Descent for NNMF. `mu` is usually more stable; `cd` can be faster on some data. |
| `nnmf_backend` | `Automatic`, `CPU only`, `Prefer GPU` | GUI backend preference for multiplicative-update NNMF. `Automatic` uses the PyTorch/CUDA backend when CUDA is available and falls back to scikit-learn; `CPU only` uses the scikit-learn CPU backend; `Prefer GPU` requests PyTorch/CUDA and falls back to CPU if CUDA is unavailable. The preset stores these choices as `auto`, `cpu`, and `gpu`. |
| `nnmf_max_iter` | integer (default 1000) | Maximum NNMF iterations for the scikit-learn and PyTorch NNMF backends. |
| `nnls_max_iter` | integer (default 1000) | Maximum NNLS iterations for fixed-H NNLS reconstruction. Used by the PyTorch/CUDA NNLS backend and passed to SciPy NNLS where supported. |

These settings are also shown in the analysis panel and can be changed before each run.

---

## Seed-Initialization Fields

The main preset stores the seed-initialization controls under `seed_init_settings`.

| Field | Values | Meaning |
|---|---|---|
| `w_seed_mode` | `NNLS abundance map`, `Selective score map`, `H weights`, `Average image`, `Homogeneous (empty)` | How W maps are estimated from available H spectra. |
| `overwrite_existing_w_from_h` | `true` / `false` | Whether H-based W reconstruction replaces existing W seeds or only fills missing W columns. |
| `normalize_h_to_unity` | `true` / `false` | Restores the **Normalize H spectra to unity** checkbox. When enabled, completed H seed spectra are scaled to max=1 before seed display, W reconstruction, and analysis. |
| `seed_pixel_metric` | `Max Intensity`, `Score` | How residual fallback pixels are ranked when H seeds are missing. |

---

## Practical Notes

**Always save the preset before exporting figures.** The preset is the only complete record of the analysis decisions (seeds, colors, solver settings). Without it, reproducing the exact result from the same data requires manually reconstructing all settings.

**Presets are human-readable JSON.** They can be opened in a text editor for inspection, but manual editing should be limited to simple, intentional changes (e.g., updating a stale image path). The ROI section in particular contains nested data that is easy to corrupt.

**Publication workflow**: for a paper, provide the input data (or a representative crop), the preset, and the expected exported result. This makes the analysis inspectable and repeatable. See [Presets and reproducibility](../tutorials/06_presets_and_reproducibility.md#publication-recommendation).
