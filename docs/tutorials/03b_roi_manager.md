# 03b ROI Manager in detail

The ROI Manager is the central place where spatial ROIs, spectral seeds, fixed W seeds, labels, colors, and component assignments are organized. It is not only a drawing tool. It defines how the analysis interprets user input.

> GIF placeholder: add a ROI, rename it, assign a component, plot the ROI spectrum, and run seeded NNMF.

## What the ROI Manager controls

The ROI Manager connects four things:

- The image view, where spatial ROIs are drawn.
- The ROI table, where each row stores seed settings.
- The ROI average plot, where ROI spectra and model spectra are displayed.
- The analysis setup, where rows are converted into H seeds, W seeds, labels, colors, and background settings.

The most important rule is:

```text
component number in ROI Manager -> component index in analysis/result viewer
```

If a row is assigned to component 3, its spectrum, color, label, and optional W seed are treated as information for analysis component 3.

## Top buttons

The top buttons create or load ROI Manager entries.

`Add ROI`

Creates a new spatial ROI in the image view. The app asks for a component number and suggests the smallest unused component where possible. The ROI is added to the table and its mean spectrum can be used as an H seed.

`Clear ROIs`

Removes all ROI Manager rows and image ROIs. Use this when starting a new seed setup.

`Suggest ROIs`

Runs automatic ROI suggestion. Suggested ROIs are normal spatial ROI rows after creation: they can be renamed, moved, removed, reassigned, plotted, or used as seeds.

`Load Spectrum from File`

Loads external spectra from CSV, TXT, or ASC files. Loaded spectra appear as dummy ROI rows because they carry spectral information without a drawn image ROI.

`Load Lookup Table and Spectra Preset`

Loads a result-viewer `.preset` file created from the result viewer.

When the preset is loaded, the GUI asks how it should be applied:

- `LUTs Only`: apply the saved component colors and histogram/LUT settings to the current result/component setup without importing new dummy ROI rows.
- `LUTs + ROIs`: also import the saved spectra as dummy ROI rows so they can be reused as H seeds.

Use `LUTs Only` when you already have the correct ROI/component setup and only want to reuse the visual style. Use `LUTs + ROIs` when the preset should also transfer spectral seeds into the ROI Manager.

## Row types

The table can contain several kinds of rows.

Spatial ROI row

A real ROI drawn on the image. Its H seed is the mean spectrum of pixels inside the ROI.

Dummy spectrum row

A row without a visible ROI shape. It stores a spectrum from a CSV/TXT/ASC file, a result import, or a preset. It behaves like an H seed.

Gaussian/model row

A generated spectral model row. It stores a Gaussian seed spectrum for a component. It is useful when a component is expected at a known resonance or wavelength.

W-only row

A row that stores a fixed W seed but does not provide an H spectrum. This is used for fixed spatial maps, background components, or result-derived W seeds. These rows do not plot a fake H spectrum.

H+W result row

A row imported from a previous result that stores both the spectral component H and the spatial map W. This can be used to refine or transfer a previous decomposition.

## Table columns

`Name`

The component/ROI label. This name is propagated to plots, result labels, and Fiji/ImageJ export labels where possible. Rename rows before final export.

`Color`

The component color. This controls ROI display, spectrum plot color, result component color, composite colors, and exported LUT colors.

`Resonance`

This column is the component assignment. The label is historical. Selecting `Component 3` means the row contributes to analysis component index 3.

`Background`

Marks the row as a background component. This is useful when a component should be interpreted or initialized as background rather than sample signal.

`Subtract`

Uses the row for background subtraction. Only use this intentionally, because subtraction changes the processed data passed to parts of the workflow.

`Scale`

Scales the displayed or prepared ROI spectrum. This is useful for matching seed amplitudes or visualizing spectra with different intensity ranges.

`Offset`

Adds an offset to the displayed or prepared ROI spectrum. This can help inspect spectra but should be used carefully for quantitative seed interpretation.

`Gaussian sigma`

Applies smoothing to the ROI spectrum. This can suppress noise in a seed spectrum, but excessive smoothing can remove real spectral structure.

`Export`

Exports the selected ROI/spectrum information where supported.

`ROI Shape`

Changes the shape of a real spatial ROI. Supported ROI shapes include line, rectangle, ellipse, and rotatable rectangle. Dummy rows do not have editable shapes.

`Live Update`

Controls whether the ROI spectrum updates while the ROI is moved/resized. Disable this for large data if interaction becomes slow.

`Plot`

Shows or hides the row in the ROI average plot. For W-only rows this can be disabled because no H spectrum should be plotted.

`Show`

Centers the image view on a spatial ROI. If the row stores a fixed W seed, this button becomes `Show W` and opens the W seed image.

`Remove`

Deletes the row and its associated ROI or dummy seed.

## H seeds from spatial ROIs

For a spatial ROI, the H seed is the average spectrum of the pixels inside the ROI:

$$
H_0[i, :] =
\frac{1}{|R_i|}
\sum_{p \in R_i} x_p
$$

where \(R_i\) is the set of pixels inside the ROI assigned to component \(i\).

Implementation-shaped view:

```text
pixels = pixels_inside_roi(row)
H0[component, :] = mean(X[pixels, :], axis=0)
```

Use this when the ROI contains a region that is visually dominated by one component.

## Multiple rows for one component

Several rows can point to the same component. This is useful when several regions represent the same material or when multiple seed sources should describe one component.

Practical interpretation:

- Multiple spatial ROIs for one component represent repeated observations of the same spectral class.
- Multiple fixed W rows for one component are averaged before analysis.
- Multiple labels/colors for the same component should be avoided; keep the final row names and colors consistent.

If two rows assigned to one component are actually different materials, increase the component number and separate them.

## Dummy rows and loaded spectra

Loaded spectra and imported result spectra are stored as dummy ROIs. A dummy row has no spatial rectangle in the image, but it still appears in the table so it can be named, colored, assigned to a component, plotted, saved, and reused.

Dummy rows are the correct representation for:

- External spectra from CSV/TXT/ASC files.
- Spectra loaded from `.preset` files when `LUTs + ROIs` is selected.
- Gaussian/model spectra.
- Result spectra imported back from the result viewer.

## Fixed W seeds

A fixed W seed is a spatial map attached to a row. It defines where a component is expected spatially.

Fixed W seeds can come from:

- Imported result W maps.
- Rolling-ball/background components.
- H+W result imports.

If a row has a fixed W seed, the `Show` button becomes `Show W`.

Important limitation:

```text
fixed W seed shape must match the current image shape
```

If new data are loaded or binning changes, old fixed W seeds may no longer match the image dimensions. The GUI removes incompatible fixed W seeds and warns the user.

## ROI average plot

The ROI average plot shows spectra from plotted ROI Manager rows. It uses the current spectral axis:

- Wavenumber axis for Raman/CARS/SRS data.
- Wavelength axis for nm data.
- Channel labels for custom labeled data.

Gaussian/model curves can be shown as fallback curves for a component. If an ROI spectrum for that component is plotted, the model curve is hidden so the plot does not show two competing seed curves for the same component.

## Background and subtraction

Background rows have two different meanings depending on the settings:

- `Background` marks the row as a background-like component.
- `Subtract` uses the selected row for background subtraction.

These are not the same operation. A background component can be modeled during analysis, while subtraction changes the data before or during seed estimation.

Use subtraction only when you intentionally want to remove a measured background spectrum. Use a background component when you want the decomposition to explicitly model background structure.

## Interaction with result viewer

The result viewer can import components back into the ROI Manager. The import can be:

- H only: stores the result spectrum as a dummy H seed.
- W only: stores the result map as a fixed W seed.
- H+W: stores both spectrum and map.

This enables iterative workflows:

```text
run random NNMF
inspect result
import useful component into ROI Manager
rename/color/assign component
rerun seeded NNMF or fixed-H NNLS
```

## What presets save

The main application preset saves ROI Manager state, including:

- Spatial ROI positions and sizes.
- Dummy spectra.
- Fixed W seeds.
- Component assignments.
- Names.
- Colors.
- Background/subtraction flags.
- Scale, offset, and smoothing settings.
- Plot/live-update state.

Gaussian model rows are regenerated from the resonance/spectral settings instead of being stored as normal ROI rows.

The result-viewer `.preset` is different:

- it stores result-viewer spectra, component colors, and histogram/LUT settings,
- it can be loaded as `LUTs Only` or `LUTs + ROIs`,
- it is useful for transferring a visual style or a seed spectrum set,
- it is not a full substitute for the main JSON application preset.

## Recommended workflow

1. Load data and set the spectral axis.
2. Add or load seed rows.
3. Assign component numbers.
4. Rename rows with final biological/chemical labels.
5. Set colors.
6. Plot and inspect spectra.
7. Check background/subtraction settings.
8. Run analysis.
9. Save the application preset.

> GIF placeholder: complete ROI Manager workflow from seed creation to preset save.
