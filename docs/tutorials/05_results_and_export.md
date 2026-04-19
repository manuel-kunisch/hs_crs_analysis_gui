# 05 Results And Export

The result viewer shows the output of PCA, NNMF, or fixed-H NNLS. It combines the spatial component maps, spectra, colormaps, labels, and export tools.

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

For 4D results, the result viewer can browse the outer z/time axis.

> GIF placeholder: browsing channels and changing component color.

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

## Saving Composite TIFFs

Use **Save Composite Image** to export a Fiji/ImageJ-compatible TIFF.

The exporter stores:

- component image data,
- LUT colors,
- display ranges,
- component labels,
- physical pixel size where available,
- hyperstack axes for 4D result series.

For 4D outputs, the full z/time result stack is exported rather than only the currently displayed slice.

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