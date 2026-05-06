# Examples

Examples are complete workflows built from real or simulated datasets. Tutorials explain individual GUI concepts; examples should show the whole path from input data to exported result.

## Current examples

| Example | Current state | Use it for |
|---|---|---|
| [Synthetic quickstart](synthetic_quickstart.md) | Runnable generator and GUI workflow are included. | Testing installation, screenshots, and first NNLS/NNMF run. |
| [Stitching and preprocessing](stitching_and_preprocessing.md) | Workflow and decision guide are drafted; needs real tiled data. | Demonstrating tile parsing, overlap, scan direction, and preprocessing. |
| [Reproduce Figure 1](reproduce_figure_1.md) | Publication planning page; needs final figure assets. | Organizing paper figures and reproducibility files. |
| [CARS/SRS label-free data](cars_srs_label_free.md) | Workflow outline; needs representative dataset. | Showing CRS/CARS/SRS decomposition. |
| [SWIR reflection data](swir_reflection.md) | Workflow outline; needs representative dataset. | Showing wavelength-axis and fixed-H workflows. |
| [4D fluorescence unmixing](fluorescence_4d_unmixing.md) | Workflow outline; needs representative 4D stack. | Showing z/time browsing and cross-slice fitting. |

## What each finished example should include

| Item | Why it matters |
|---|---|
| Input data description | Lets users confirm dimensionality, axis order, and expected component count. |
| `wavelength.json` or axis instructions | Prevents silent channel-index analysis when a physical axis is expected. |
| Preset files | Makes seed setup, colors, solver settings, and histogram levels reproducible. |
| Step-by-step GUI actions | Makes the example usable without reading the full reference first. |
| Expected result images and H spectra | Gives users a way to tell whether their run is working. |
| Exported TIFF/CSV outputs | Documents what should be produced for downstream analysis or Fiji/ImageJ. |

## Media checklist

When adding screenshots and GIFs, prioritize media that removes ambiguity about where to click:

| Priority | Media |
|---|---|
| 1 | Synthetic quickstart: load TIFF, import spectra, run fixed-H NNLS, export composite. |
| 2 | ROI Manager: add ROI, assign component, rename, change color, plot spectrum. |
| 3 | Result viewer: channel browsing, histogram/LUT adjustment, H export, composite export. |
| 4 | 4D loading: axis-role dialog and result slice browsing. |
| 5 | Stitching: tile folder selection, regex helper, preview table, stitch output. |
