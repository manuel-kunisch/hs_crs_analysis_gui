# ROI manager and seed types

This reference summarizes the row types and table columns in the ROI Manager. For the guided tutorial, see [03b ROI Manager in detail](../tutorials/03b_roi_manager.md).

> Screenshot placeholder: ROI Manager reference screenshot with each row type and important table columns labeled.

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

## Background and Subtract columns

These two columns look similar but do different things.

**Background flag**

Use the Background flag mainly for hard-to-isolate backgrounds that should remain inside the NNMF/NNLS model and
if other components are disturbed by background contribution in combination with the background subtraction.

A component can carry a fixed W seed (e.g. from a mean-image projection) and be marked as Background at the same time. Together these tell the model where a difficult background is expected spatially and that it should be treated as a separate non-chemical contributor.

**Subtract flag**

Enables ROI-mean background subtraction. The data shown in the **Processed** view is computed by taking the mean spectrum from the active Subtract ROI and subtracting that spectrum from every pixel in the raw stack.

This changes what is *displayed* as processed data and what enters seed estimation or analysis steps that are configured to use processed/subtracted data. It does not overwrite the raw loaded image; removing the Subtract flag restores the raw-data path.

Use Subtract only when you have a clear rationale for removing a measured signal before inspecting the residual. When in doubt, leave subtraction off; use a background component only if the background is hard to isolate and should be represented explicitly in the model.

**Typical usage patterns**

| Goal | Recommended approach |
|---|---|
| Separate a hard-to-detect background from signal in NNMF | Mark the background row with Background only. |
| Visually inspect data with background removed | Mark the background row with Subtract. |
| Explicitly model a difficult background and inspect cleaned data | Mark the row with both Background and Subtract. |
| Flat background not in the model | Use rolling-ball preprocessing instead of a background row. |

## Seed priority

For spectral H seeds, spatial ROI spectra are preferred when present. Gaussian/model dummy rows are used when no plotted ROI spectrum is available for that component.

For spatial W seeds, fixed W maps are used when attached to a row. Otherwise W can be estimated from H using the selected W-seed mode.

## Presets

Application presets save ROI Manager state, including spatial ROIs, dummy spectra, fixed W seeds, labels, colors, component assignments, and table settings.
