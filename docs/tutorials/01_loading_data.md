# 01 Loading Data

This page explains what kind of image data the GUI expects and how to inspect it after loading.

## Supported Input Types

The main input format is TIFF. The GUI currently expects spectral image data as either a 3D stack or a 4D stack.

For a standard 3D hyperspectral or multispectral stack, the expected array order is:

```text
channel, y, x
```

The first axis is interpreted as the spectral/channel axis. Each frame along this axis is one spectral image.

For 4D data, the TIFF contains one spectral/channel axis and one outer z/time axis. When a 4D stack is loaded, the GUI asks which axis is the spectral axis and which axis is the outer z/time axis. Internally, the data are converted to:

```text
z_or_time, channel, y, x
```

The remaining two axes are treated as spatial dimensions.

> GIF placeholder: drag-and-drop loading of a 3D TIFF stack.

## Concrete TIFF Layout Examples

The TIFF file is binary, so the most important "format" detail is the array shape saved inside the file.

Minimal 3D example:

```python
import numpy as np
import tifffile

channels = 5
height = 256
width = 256

data = np.zeros((channels, height, width), dtype=np.uint16)
data[0] = 100
data[1] = 500

tifffile.imwrite("example_3d_cyx.tif", data)
```

The GUI reads this as:

```text
channel 0 -> first spectral image
channel 1 -> second spectral image
...
```

Minimal 4D example:

```python
import numpy as np
import tifffile

z_slices = 10
channels = 4
height = 256
width = 256

data = np.zeros((z_slices, channels, height, width), dtype=np.uint16)

tifffile.imwrite("example_4d_zcyx.tif", data)
```

When this file is loaded, choose the channel axis as the spectral axis and the z axis as the outer axis.

Alternative 4D layouts are allowed, but the user must select the correct axes in the loading dialog. If the data are stored as `(channel, z, y, x)`, choose the first axis as spectral and the second axis as outer z/time.

## Loading A Single TIFF Stack

Use the **Single HS Image** tab to load a TIFF file. A file can be opened from the file dialog or dragged onto the drop area.

After loading, the app will:

- read the TIFF data,
- apply optional rolling-ball correction if enabled,
- normalize the image if normalization is active,
- validate the stack shape,
- apply the current binning factor,
- update the spectral-axis widget to the number of channels,
- update the physical image dimensions.

If a `wavelength.json` file is present in the same folder as the TIFF, the GUI tries to use it for the spectral axis.

> Screenshot placeholder: loaded 3D stack with channel slider, LUT controls, and spectral-axis widget.

## Loading 4D TIFF / Hyperstack Data

When the loaded TIFF is 4D, an axis selection dialog appears. Choose:

- the **spectral axis**: the axis containing wavelengths, Raman shifts, channels, or dye channels;
- the **outer axis**: the axis containing z slices or time points;
- the **outer axis meaning**: z or time.

For common microscopy hyperstacks, the shape is often similar to:

```text
z, channel, y, x
```

or:

```text
time, channel, y, x
```

After loading, the GUI shows a z/time selector below the raw image controls. Changing this selector updates the displayed slice and the analysis input.

> GIF placeholder: loading a 4D stack and choosing spectral and z/time axes.

## Stitching A Tile Folder

Use the **HS Image Stitching** tab when the dataset is stored as multiple tiled TIFFs. The stitching tool expects filenames that contain x/y tile indices. These indices are extracted with a regular expression.

For the full stitching workflow, regex examples, scan-direction settings, overlap handling, and stitch presets, see [01b Stitching tile folders](01b_stitching_tile_folders.md).

The stitching workflow is:

1. Choose or drop the folder with tiles.
2. Set the filename pattern, for example `*.tif`.
3. Check whether the table preview correctly detects the tile grid.
4. Set overlap in raw pixels.
5. Set scan direction in x and y.
6. Choose whether to estimate shifts by correlation or use grid/linear blending.
7. Click **Stitch now**.

The result is loaded back into the same data workflow.

> GIF placeholder: tile folder selection, filename parsing, and stitched-image loading.

## Viewing Loaded Data

The raw data viewer provides:

- LUT selection,
- autoscale,
- autoplay through spectral channels,
- playback speed control,
- display of an average image,
- display of processed/subtracted data,
- binning control,
- line-scan view,
- ROI table and ROI average plot.

For 4D data, the z/time selector changes the current outer slice. The spectral channel navigation remains inside the image viewer.

> Screenshot placeholder: raw image viewer controls annotated with LUT, autoplay, average image, and binning.

## Common Loading Problems

If the TIFF has the wrong dimensionality, the GUI rejects it. Only 3D and 4D stacks are supported in the main spectral workflow.

If the spectral axis appears wrong, check:

- whether the stack order is really `channel, y, x` for 3D data,
- whether the correct spectral axis was selected for 4D data,
- whether `wavelength.json` has the same number of entries as image channels,
- whether a preset from a different dataset was loaded.

If the image is very large, use binning before analysis to reduce memory and runtime.
