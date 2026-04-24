# 05 Results And Export

The result viewer shows the output of PCA, NNMF, or fixed-H NNLS. It combines the spatial component maps, spectra, colormaps, labels, and export tools.

For general pyqtgraph interaction, histogram/LUT adjustment, zooming, and plot export behavior, see [GUI and pyqtgraph basics](00_gui_and_pyqtgraph_basics.md).

## Composite Overview

The composite image fuses component maps into a false-color overview. This is usually the most important result for visual interpretation.

Each component uses a color shared with the ROI manager. Changing the component color updates the composite and the corresponding spectral line.

> Screenshot placeholder: result viewer composite overview with labeled components.

## Channel Preview

The channel preview shows one component map at a time. Use it to inspect individual W maps, adjust color, and check whether a component is spatially meaningful.

Controls include:

- component/channel selector,
- color selector,
- autoscale,
- histogram/level controls,
- z/time result selector for 4D outputs.

Histogram levels control display contrast only. For exact reproducible min/max display values, save or edit the histogram state in a preset as described in [GUI and pyqtgraph basics](00_gui_and_pyqtgraph_basics.md).

For 4D results, the result viewer can browse the outer z/time axis.

> GIF placeholder: browsing channels and changing component color.

## Result Data Types And W Scaling

The result viewer is primarily a visualization layer. It does not assume that every analysis result already fits into `uint16`.

### Why W can exceed 16-bit values

For NNMF and fixed-H NNLS, the spatial maps `W` are abundance coefficients. They are fitted numbers, not copies of the raw detector counts. Because of that, a valid `W` map can easily contain values above `65535` even if the original input TIFF was 16-bit.

This is especially common when:

- spectra are scaled in a particular way,
- one component carries much of the signal energy,
- fixed-H NNLS is used with strong or narrow spectral bases.

### Optional display scaling

Next to **Analyze**, the GUI provides the checkbox:

```text
Scale results to 16-bit
```

If this option is enabled, NNMF/NNLS result maps are scaled for display with one global factor over the full result array:

$$
a = \frac{65535}{\max(W)}
$$

and the result viewer shows:

$$
W' = aW
$$

This keeps all displayed components in a common 16-bit display range and preserves relative brightness between components inside that result.

If the option is disabled, the channel preview uses the raw floating-point `W` values instead.

### Important scope of this scaling

The `Scale results to 16-bit` option affects the displayed result maps in the result viewer. It is there to make viewing, histogram control, and export behavior more predictable.

The underlying analysis is still carried out in floating point. The fitted spectra `H` remain unchanged, and the GUI fit summary reports the display scale factor so you can see when a displayed `W` map is not in raw units anymore.

### Histograms and display levels

Histogram and LUT settings act on the data currently shown in the result viewer:

- if `Scale results to 16-bit` is enabled, they act on the scaled display map,
- if it is disabled, they act on the raw floating-point map.

Changing histogram levels changes only the visualization unless you explicitly export a rendered image.

## Spectral Components

The spectral plot shows the H spectra or PCA components. If seed spectra are available, they can be overlaid for comparison.

Use this plot to check:

- whether NNMF components remain similar to the seeds,
- whether fixed-H NNLS used the expected spectra,
- whether component labels and colors match the intended interpretation.

## Saving Spectra

Use **Save H as CSV** to export spectral components. The CSV export uses the current spectral axis or custom labels.

This is useful for:

- plotting spectra externally,
- comparing components between datasets,
- documenting the final H matrix used in a paper.

Example output with a numerical spectral axis:

```csv
Wavenumber (1/cm),Component 0,Component 1,Component 2
2800.0,0.02,0.10,0.00
2850.0,1.00,0.25,0.05
2900.0,0.40,0.90,0.12
2950.0,0.10,1.00,0.20
```

Example output with custom channel labels:

```csv
Channel Label,Component 0,Component 1,Component 2
DAPI,1.00,0.10,0.00
GFP,0.05,0.95,0.20
mCherry,0.00,0.25,1.00
```

The component columns follow the component order in the result. Rename components in the ROI manager before export if the exported files should carry publication-ready labels elsewhere in the workflow.

Use **Export Spectra** to export the visible spectral plot as PNG or PDF. PNG export can use a transparent background. The export keeps the plot aspect ratio to avoid distorted text.

## Saving Composite TIFFs

Use **Export Composite** to export a Fiji/ImageJ-compatible TIFF or a rendered PNG.

The exporter stores:

- component image data,
- LUT colors,
- display ranges,
- component labels,
- physical pixel size where available,
- hyperstack axes for 4D result series.

For 4D outputs, the full z/time result stack is exported rather than only the currently displayed slice.

PNG export saves the currently rendered composite image at the result image resolution and can optionally add a scale bar.

### Data type notes for export

- Spectral CSV export writes numerical text values and does not quantize the spectra to `uint16`.
- Rendered PNG export writes the displayed RGB composite, not the raw component stack.
- Fiji/ImageJ TIFF export writes integer image data together with LUTs, ranges, labels, and pixel-size metadata.

If the exported result stack is already in the viewer's `uint16` working range, it is written as such. If a floating-point result stack is passed to the Fiji exporter, it is normalized to the saver dtype before writing. In other words, TIFF export is a visualization/export format step, not a guarantee that the saved TIFF preserves raw floating-point abundance values one-to-one.

For publication workflows, it is therefore useful to save:

- the preset,
- the exported TIFF,
- the exported H spectra CSV,
- and, if relevant, a short note on whether `Scale results to 16-bit` was enabled.

> GIF placeholder: exporting a composite TIFF and opening it in Fiji.

## Component Labels

Component labels from the ROI manager are propagated to the result viewer and to Fiji/ImageJ export metadata. This makes exported files easier to interpret later.

Before exporting, check that:

- component labels are meaningful,
- colors are final,
- histogram ranges are set,
- scale bars/physical units are correct.

## Importing Results Back As Seeds

NNMF result components can be imported back into the ROI manager as H, W, or H+W seed rows. This supports iterative workflows where a first analysis provides seeds for a later run.
This can be useful for refining random NNMF results to refine later NNLS or NNMF iterations.
