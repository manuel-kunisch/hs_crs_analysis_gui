# ROI manager and seed types

This reference summarizes the row types and table columns in the ROI Manager. For the guided tutorial, see [03b ROI Manager in detail](../tutorials/03b_roi_manager.md).

## Row types

| Row type | Spatial ROI? | H seed? | W seed? | Typical source |
|---|---:|---:|---:|---|
| Spatial ROI | yes | yes | optional | User-drawn or suggested ROI |
| Dummy spectrum | no | yes | optional | CSV/TXT/ASC spectrum, preset spectrum, imported H |
| Gaussian/model row | no | yes | no | Resonance/Gaussian seed model |
| W-only row | no | no | yes | Imported W, background W |
| H+W result row | no | yes | yes | Imported result component |

## Table columns

| Column | Meaning |
|---|---|
| Name | Label used for plots, result channels, and exports. |
| Color | Component color and exported LUT color. |
| Resonance | Component assignment. `Component 1` means analysis component 1. |
| Background | Marks the row as a background component. |
| Subtract | Uses the row for background subtraction. |
| Scale | Multiplies the row spectrum. |
| Offset | Adds an offset to the row spectrum. |
| Gaussian sigma | Smooths the row spectrum. |
| Export | Exports row information where supported. |
| ROI Shape | Shape of a spatial ROI. Disabled for dummy rows. |
| Live Update | Updates spectra while the ROI is moved/resized. |
| Plot | Shows or hides the row in the ROI average plot. |
| Show | Centers on the ROI or shows the fixed W map. |
| Remove | Deletes the row and associated seed information. |

## Seed priority

For spectral H seeds, spatial ROI spectra are preferred when present. Gaussian/model dummy rows are used when no plotted ROI spectrum is available for that component.

For spatial W seeds, fixed W maps are used when attached to a row. Otherwise W can be estimated from H using the selected W-seed mode.

## Presets

Application presets save ROI Manager state, including spatial ROIs, dummy spectra, fixed W seeds, labels, colors, component assignments, and table settings.
