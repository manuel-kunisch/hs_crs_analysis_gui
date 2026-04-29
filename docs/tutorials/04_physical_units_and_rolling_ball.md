# 04 Physical units and rolling-ball correction

This page covers physical pixel sizes, scale bars, TIFF metadata, and rolling-ball/background correction.

## Physical units

The physical units panel stores:

- Unit.
- Pixel size.
- Field of view.
- Image shape.
- Scale-bar options.

Supported display units are:

- `nm`
- `um`
- `mm`

When a TIFF contains Fiji/ImageJ pixel-size metadata, the GUI can read it and update the physical-unit fields automatically.

> Screenshot placeholder: physical-units panel after loading a TIFF with pixel-size metadata.

## Scale bars and Fiji export

The physical pixel size is used for scale bars in the GUI and for Fiji/ImageJ-compatible export metadata.

Check the pixel size before exporting publication images, especially after:

- Binning.
- Stitching.
- Loading a preset.
- Loading data from a different microscope.

## Rolling-ball / illumination correction

Rolling-ball correction is available as a preprocessing step for 2D and 3D data. It is intended to remove smooth background or illumination variation.

The correction can be configured in the rolling-ball correction tab. For stitching, reference-mode correction is preferred because it avoids estimating a different correction field for every tile.

> GIF placeholder: loading a reference image and applying rolling-ball correction.

## What the rolling-ball settings mean

### Enable illumination correction

This is the master on/off switch. Leave it off unless you clearly see smooth shading, vignetting, or broad multiplicative illumination variation.

### Mode

- `reference`: uses one stored reference model for all images. This is the recommended mode for stitching and for consistent preprocessing across a dataset.
- `blur`: estimates a smooth correction field separately for each image by heavy smoothing. Use this when no stable reference image exists and the illumination pattern changes from image to image.
- `gaussfit`: estimates a per-image smooth field and then fits a Gaussian-like model. Use this when a simple blur is not stable enough but you still do not want to build a dedicated reference first.

### Normalize to

- `center`: keeps the correction normalized to the image center. Good when the center is the natural reference region.
- `median`: more robust when the center is not representative.
- `mean`: useful when you want global average intensity to stay as stable as possible.

### Max gain clamp

This limits how strongly dark regions may be amplified by the correction. Increase it only when under-corrected edges remain visible. If noisy image corners become too bright, reduce it.

### Fit-input smoothing

These settings are used when fitting a reference TIFF:

- `Blur sigma X [px]`
- `Blur sigma Y [px]`
- `Downsample`

They do not directly define the final correction. They define how aggressively the reference image is simplified before estimating the smooth illumination field.

Use larger blur sigmas when:

- the reference contains strong sample structure,
- only the large-scale illumination profile should remain,
- or the fitted model is following fine image details too much.

Use more downsampling when:

- the reference is very large,
- fitting is slow,
- and only the broad illumination envelope matters.

### Reference / Model parameters

These describe the smooth model itself:

- `dx`, `dy`: center offset of the illumination pattern relative to the image center.
- `sigma_x`, `sigma_y`: spatial width of the illumination profile along x and y.
- `strength`: how strongly the correction is applied. `1` is the normal case, smaller values weaken the correction, larger values strengthen it.
- `floor`: mixes in a constant baseline to avoid extreme gains in dark regions.

In most workflows, load a representative reference TIFF first, preview it, and then only fine-tune `strength` and `floor` manually.

### Reference TIFF buttons

- `Load reference TIFF...`: fit a stable model from one representative image.
- `Preview model...`: inspect the current correction model before applying it broadly.
- `Clear reference TIFF`: remove the loaded TIFF payload while keeping the current model parameters available.

This makes `reference` mode practical for batch-like workflows: you can learn the model once and reuse it on similar images.

## When to use preprocessing vs a background component

Use rolling-ball / illumination correction as preprocessing when:

- the background is mainly an imaging artifact,
- the same artifact affects all channels broadly,
- and you want cleaner images before ROI work or stitching.

Use a background component seed in the analysis model when:

- the broad background is part of the sample mixture,
- you want the background represented explicitly in NNMF/NNLS,
- or you want to compare corrected vs uncorrected modeling strategies.

These are different choices. Preprocessing removes a signal before analysis. A background component keeps that signal inside the factorization model.

## Background component seeds

The analysis panel can also generate a background component from a projection image. The reference image can be based on:

- Mean projection.
- Maximum projection.
- Minimum projection.

The generated W background map can be previewed and added as a dummy ROI carrying a fixed W seed.

Use this when a slowly varying background should be represented as a separate component in the unmixing model.

> GIF placeholder: previewing a rolling-ball background component and adding it as a W seed.

## Practical checks

Before analysis or export, check:

- Whether the image is binned.
- Whether physical units still match the displayed image.
- Whether rolling-ball correction should be applied before or after stitching.
- Whether background correction is part of preprocessing or modeled as a component.

Good default order for tiled hyperspectral data:

1. confirm tile parsing and stitch geometry,
2. decide whether a shared reference-mode correction should be applied to all tiles,
3. stitch the data,
4. verify physical units and scale bars,
5. then continue with ROI definition and multivariate analysis.
