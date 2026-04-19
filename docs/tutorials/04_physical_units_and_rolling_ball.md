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
