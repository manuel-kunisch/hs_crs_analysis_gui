# Examples

Examples are complete workflows built from real or simulated datasets. Tutorials explain individual GUI concepts; examples show the whole path from input data to exported result.

## Available now

| Example | What you get | Use it for |
|---|---|---|
| [Synthetic quickstart](synthetic_quickstart.md) | Runnable generator script, reproducible TIFF + reference spectra, full step-by-step GUI walkthrough, demo GIF. | Testing installation, learning the workflow on safe data, screenshots, bug-report reproductions. |

The synthetic quickstart is the **canonical end-to-end check** for a fresh HS-MOSAIC install. If anything is wrong with your setup, it will show up here.

## Work in progress

The pages below are planning outlines. They describe what the finished example will eventually contain, but the datasets and step-by-step walkthroughs are not yet shipped. They are kept in the docs so the intended scope is visible and so cross-links to the relevant tutorial pages already work.

| Example | Status | Planned scope |
|---|---|---|
| [Stitching and preprocessing](stitching_and_preprocessing.md) | Workflow and decision guide drafted; needs a real tiled dataset and screenshots. | Tile parsing, overlap, scan direction, illumination correction. |
| [CARS/SRS label-free data](cars_srs_label_free.md) | Outline only; needs a representative CARS/SRS dataset. | Label-free chemical imaging, Raman-shift axis, ROI-derived seeds. |
| [SWIR reflection data](swir_reflection.md) | Outline only; needs a representative SWIR dataset. | Wavelength-axis (nm) workflows, custom channel labels, fixed-H NNLS. |
| [4D fluorescence unmixing](fluorescence_4d_unmixing.md) | Outline only; needs a representative 4D stack. | 4D axis selection, fast multislice NNMF, slice-by-slice result inspection. |

## What a finished example should include

This list defines the bar for promoting a WIP outline above into the "Available now" table.

| Item | Why it matters |
|---|---|
| Input data description | Lets users confirm dimensionality, axis order, and expected component count. |
| `wavelength.json` or axis instructions | Prevents silent channel-index analysis when a physical axis is expected. |
| Preset file | Makes seed setup, colours, solver settings, and histogram levels reproducible. |
| Step-by-step GUI actions | Makes the example usable without first reading the full reference. |
| Expected result images and H spectra | Gives users a way to tell whether their run is working. |
| Exported TIFF/CSV outputs | Documents what should be produced for downstream analysis or Fiji/ImageJ. |
| At least one screenshot or short GIF | Removes ambiguity about where to click. |
