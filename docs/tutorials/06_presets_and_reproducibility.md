# 06 Presets And Reproducibility

Presets are used to save analysis state and make workflows reproducible. They are important when the same seed set, lookup tables, labels, and settings should be applied to another field of view or included with a publication.

## Main JSON Preset

The main GUI preset stores the analysis session state.

It includes:

- image path,
- binning factor,
- current 4D slice index,
- physical field of view and unit,
- spectral-axis widget state,
- derived wavenumbers/wavelengths,
- number of components,
- analysis method,
- custom initialization setting,
- NNMF solver and backend choice,
- NNMF and NNLS iteration limits,
- seed initialization settings,
- resonance/spectral settings,
- ROI manager state,
- histogram and LUT state,
- component labels.

This preset is the best option for reproducing a full GUI analysis.

> GIF placeholder: saving and loading a main JSON preset.

## Example Preset Structure

Preset files are meant to be written by the GUI. They can be inspected in a text editor, but manual editing should be limited to simple, intentional changes.

A shortened preset looks like this:

```json
{
  "image_path": "C:/data/example_stack.tif",
  "binning_factor": 1,
  "current_slice_index": 0,
  "fov": [512.0, 512.0],
  "unit": "um",
  "wavenumber_widget": {
    "source_index": 1,
    "spectral_unit": "nm",
    "custom_values": [500.0, 550.0, 600.0],
    "custom_labels": ["Dye A", "Dye B", "Dye C"]
  },
  "wavenumbers": [500.0, 550.0, 600.0],
  "num_components": 3,
  "analysis_method": "Fixed-H NNLS",
  "nnmf_solver": "mu",
  "nnmf_backend": "Automatic",
  "roi_manager": {
    "rois": []
  },
  "labels": {
    "0": "Dye A",
    "1": "Dye B",
    "2": "Dye C"
  }
}
```

The real preset usually contains more ROI, color, histogram, seed, and solver state. The exact content depends on the current GUI state when the preset is saved.

## ROI And Seed State

Presets can include:

- drawn ROIs,
- dummy ROIs,
- loaded spectra,
- Gaussian seed rows,
- fixed W seeds,
- imported result seeds,
- component assignments.

This is important because the seed setup is often the scientific decision that defines the analysis.

## LUTs And Display Settings

The preset also stores display information such as LUT colors, histogram ranges, and labels. This helps reproduce the same visual output after reopening the data.

For figure preparation, save the preset after finalizing:

- labels,
- colors,
- black/white levels,
- component count,
- seed choices,
- analysis mode.

## Result-Viewer Presets

The result viewer can also save `.preset` files for seeds or results. These are useful for transferring H spectra, colors, and display ranges, but the main JSON preset is more complete for reproducing a whole analysis session.

The `.preset` workflow is designed for two use cases:

- transfer result spectra into the ROI Manager as dummy seed rows,
- reuse the same LUT colors and histogram settings on another result without changing the ROI list.

When a `.preset` is loaded from the ROI Manager, the GUI asks how it should be applied:

- `LUTs Only`: reuse the saved component colors and histogram/LUT settings for the current components.
- `LUTs + ROIs`: also import the saved spectra as dummy ROI rows.

This is useful when a representative field of view has already been styled carefully for figure preparation and the same display settings should be reused elsewhere.

The `.preset` file stores:

- component colors,
- histogram/contrast settings for each component,
- saved H spectra,
- spectral axis values stored with the preset.

It does not replace the full JSON application preset because it does not capture the entire GUI state, ROI geometry, physical units, 4D slice selection, solver settings, or all preprocessing choices.

> GIF placeholder: loading a result-viewer `.preset` as `LUTs Only` and as `LUTs + ROIs`.

## Reusing A Preset On Another Field Of View

A typical reuse workflow is:

1. Analyze a representative field of view.
2. Save the preset.
3. Load a related field of view.
4. Load the preset.
5. Check component count and spectral-axis compatibility.
6. Run fixed-H NNLS or seeded NNMF.
7. Save the new result.

If the new dataset has a different number of spectral channels, check the spectral-axis warning carefully before continuing.

## Publication Recommendation

For a paper, provide:

- the input data or representative cropped data,
- the preset file,
- the expected exported result,
- a short tutorial showing how to reproduce the result.

This makes the analysis inspectable and repeatable.
