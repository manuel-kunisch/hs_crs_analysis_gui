# 04 Physical units and rolling-ball correction

This page covers physical pixel sizes, scale bars, TIFF metadata, and rolling-ball illumination correction.

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

## Illumination correction

The rolling-ball correction tab is used as an illumination-correction preprocessor for 2D and 3D data. Use it when the image has smooth shading, vignetting, or a broad multiplicative illumination pattern that should be corrected before ROI work, stitching, analysis, or export.

![Rolling-ball illumination correction panel](../assets/images/04_rolling_ball_illumination_correction.png)

The correction can be configured in two main ways:

- **Reference/manual model**: use `reference` mode. The model can be fitted from a reference TIFF, but it can also be edited manually without loading a reference image. This is useful when you want to tune `dx`, `dy`, `sigma_x`, `sigma_y`, `strength`, and `floor` from the preview.
- **Per-image estimation**: use `blur` or `gaussfit`. These modes estimate a smooth correction field from each image separately.

> **Stitching compatibility:** for stitching, use `reference` mode. The same stored/manual correction model is applied to every tile individually before stitching. If you change illumination-correction settings after a stitch has already been generated, rerun the stitch so the updated correction is applied to the tiles.

## What the illumination-correction settings mean

### Enable illumination correction

This is the master on/off switch. Leave it off unless you clearly see smooth shading, vignetting, or broad multiplicative illumination variation.

### Mode

- `reference`: uses one stored model for all images. The model can come from a reference TIFF or from manual/synthetic settings. This is the recommended mode for stitching and for consistent preprocessing across a dataset.
- `blur`: estimates a smooth correction field separately for each image by heavy smoothing. Use this when no stable reference image exists and the illumination pattern changes from image to image.
- `gaussfit`: estimates a per-image smooth field and then fits a Gaussian-like model. Use this when a simple blur is not stable enough but you still do not want to build a dedicated reference first.

### Normalize to

- `center`: keeps the correction normalized to the image center. Good when the center is the natural reference region.
- `median`: more robust when the center is not representative.
- `mean`: useful when you want global average intensity to stay as stable as possible.

### Max gain clamp

This limits how strongly dark regions may be amplified by the correction. Increase it only when under-corrected edges remain visible. If noisy image corners become too bright, reduce it.

### Fit-input smoothing

These settings are used only when fitting a reference TIFF or when a per-image fit needs a smoothed input:

- `Blur sigma X [px]`
- `Blur sigma Y [px]`
- `Downsample`

They do not directly define the final manual/reference correction model. They define how aggressively the image is simplified before estimating a smooth illumination field.

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

In reference mode, these parameters are active even without a loaded reference TIFF. Use **Preview model...** to inspect the current synthetic/manual correction field, tune the parameters, and enable correction once the field looks reasonable. If a representative reference TIFF is available, load it first and then fine-tune `strength` and `floor`.

### Reference TIFF buttons

- `Load reference TIFF...`: fit a stable model from one representative image.
- `Preview model...`: inspect the current correction model. This also works without a reference TIFF by using the synthetic preview size.
- `Clear reference TIFF`: remove the loaded TIFF payload while keeping the current model parameters available.

This makes `reference` mode practical for batch-like workflows: you can learn or manually tune the model once and reuse it on similar images.

## Practical checks

Before analysis or export, check:

- Whether the image is binned.
- Whether physical units still match the displayed image.
- Whether illumination correction should be applied to tiles before stitching.

Good default order for tiled hyperspectral data:

1. confirm tile parsing and stitch geometry,
2. decide whether a shared reference/manual illumination correction should be applied to all tiles,
3. stitch the data,
4. verify physical units and scale bars,
5. then continue with ROI definition and multivariate analysis.
