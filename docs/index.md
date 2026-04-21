# HS MV Analysis Documentation

This documentation contains the basic GUI tutorials, example workflows, and feature reference for HS MV Analysis.

TODO:
- [] add screenshots and short GIFs for each major workflow.
- [] link small example datasets and expected outputs.
- [] replace placeholders with final paper datasets, presets, and expected outputs.
- [] check text for errors


## Start Here

- [Installation](installation.md)
- [Quickstart](quickstart.md)
- [Concepts](concepts.md)
- [Troubleshooting](troubleshooting.md)
- [Citation](citation.md)

## Tutorials

The tutorials explain the app from the basic workflow upward. They are intentionally modality-independent first; dataset-specific examples are listed separately below.

### 01 Data loading

- [Loading 3D TIFF and 4D data](tutorials/01_loading_data.md)
- [Spectral axis and channel labels](tutorials/01a_spectral_axis_and_channel_labels.md)
- [Stitching tile folders](tutorials/01b_stitching_tile_folders.md)

### 02 Analysis

- [Analysis modes](tutorials/02_analysis_modes.md)
- [GPU acceleration](tutorials/02a_gpu_acceleration.md)

### 03 Seeds

- [Seeds, spectra, and W maps](tutorials/03_seeds_spectral_and_spatial.md)
- [ROI Manager in detail](tutorials/03b_roi_manager.md)
- [Loading custom seed spectra](tutorials/03a_loading_custom_seed_spectra.md)

### Remaining workflow

- [04 Physical units and rolling-ball correction](tutorials/04_physical_units_and_rolling_ball.md)
- [05 Results and export](tutorials/05_results_and_export.md)
- [06 Presets and reproducibility](tutorials/06_presets_and_reproducibility.md)
- [07 Workflow checklist](tutorials/07_workflow_checklist.md)

## Examples

The example section is reserved for data-specific workflows and for reproducing figure panels from a paper.

- [Examples overview](examples/index.md)
- [Reproduce Figure 1](examples/reproduce_figure_1.md)
- [Synthetic quickstart](examples/synthetic_quickstart.md)
- [CARS/SRS label-free data](examples/cars_srs_label_free.md)
- [SWIR reflection data](examples/swir_reflection.md)
- [4D fluorescence unmixing](examples/fluorescence_4d_unmixing.md)
- [Stitching and preprocessing](examples/stitching_and_preprocessing.md)

## Reference

- [Spectral axis and wavelength.json](reference/spectral_axis_and_wavelength_json.md)
- [ROI manager and seed types](reference/roi_manager_and_seed_types.md)
- [NNMF and NNLS modes](reference/nnmf_nnls_modes.md)
- [Fiji export](reference/fiji_export.md)
- [Presets](reference/presets.md)

## TODO

- Add screenshots and short GIFs for each major workflow.
- Link small example datasets and expected outputs.
- Replace placeholders with final paper datasets, presets, and expected outputs.
