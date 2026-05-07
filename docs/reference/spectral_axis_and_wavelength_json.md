# Spectral Axis and wavelength.json

The spectral axis tells the GUI what each image channel represents. This page is the complete reference for all axis modes and for the `wavelength.json` metadata file.

For a workflow-oriented introduction, see [Spectral axis and channel labels](../tutorials/01a_spectral_axis_and_channel_labels.md).

> Screenshot placeholder: spectral-axis widget with calculated Raman axis, wavelength axis, and manual/custom axis controls labeled.

## Axis Modes

### Calculated Pump/Stokes Raman axis

Available when the data is a CRS/CARS/SRS scan acquired by tuning one laser beam while the other stays fixed.

Inputs:

- tuned wavelength minimum (nm),
- tuned wavelength maximum or step size (nm),
- fixed wavelength (nm),
- which beam was tuned (pump or Stokes).

The GUI computes the Raman shift axis in cm⁻¹ from these values. The number of points is determined by the number of image channels.

This mode is appropriate for most coherent Raman datasets recorded with a standard hyperspectral scan.

### Wavelength axis in nm

Switch the unit to `nm` when the data is wavelength-resolved (fluorescence emission, SWIR, broadband spectroscopy).

In this mode, enter the wavelength values directly rather than pump/Stokes laser settings.

### Manual / Custom axis

Use this mode when the channel positions are not described by a pump/Stokes calculation.

The custom axis accepts either:

- **numeric values**, such as `720, 740, 760` — used as the x-axis in spectral plots,
- **text labels**, such as `DAPI, FITC, Cy5` — used as channel labels; the internal axis becomes channel index.

Numeric and text information can be combined: providing both `custom_values` and `custom_labels` shows text labels in the plot while still using numeric positions for spectral interpolation (important when loading external reference spectra).

---

## wavelength.json

Place a file named exactly `wavelength.json` in the **same folder** as the TIFF file. When the GUI loads the TIFF, it automatically reads this file and applies the spectral axis.

### Accepted keys

| Key | Alias | Type | Description |
|---|---|---|---|
| `spectral_unit` | `unit` | string | Spectral unit. Accepted values: `"nm"`, `"nanometer"`, `"nanometers"`, `"wavelength"` → treated as `nm`; `"cm-1"`, `"cm^-1"`, `"1/cm"`, `"cm⁻¹"`, `"wavenumber"`, `"raman"` → treated as `cm⁻¹`. |
| `custom_values` | `custom_points` | list of numbers | Numeric axis positions, one per channel. |
| `custom_labels` | `labels` | list of strings | Text labels, one per channel. |

All keys are optional, but at least one of `custom_values` or `custom_labels` should be present for the file to have any effect.

The number of values or labels must match the number of spectral channels in the loaded image. A mismatch generates a warning and the axis falls back to channel indices.

> Screenshot placeholder: file browser or folder view showing a TIFF stack and matching `wavelength.json` side by side.

### Example: numeric wavelength axis

```json
{
  "spectral_unit": "nm",
  "custom_values": [700, 750, 800, 850]
}
```

### Example: dye labels only (channel-index axis)

```json
{
  "custom_labels": ["DAPI", "FITC", "Cy5"]
}
```

This creates a channel-index x-axis and uses the labels for display. If external reference spectra need to be loaded and resampled later, also provide numeric `custom_values`.

### Example: values and labels combined

```json
{
  "spectral_unit": "nm",
  "custom_values": [405, 488, 640],
  "custom_labels": ["DAPI", "FITC", "Cy5"]
}
```

### Example: Raman wavenumber axis with peak labels

```json
{
  "spectral_unit": "cm^-1",
  "custom_values": [2850, 2930, 3000, 3060],
  "custom_labels": ["CH2 sym.", "CH3 asym.", "=CH2", "Phe ring"]
}
```

### Example: labels-only with the `labels` alias

```json
{
  "labels": ["DAPI", "GFP", "mCherry"]
}
```

---

## Spectral Axis and Preset Interaction

The spectral axis state is saved in the main JSON preset. When a preset is loaded, it restores:

- the source mode (calculated / custom),
- the unit,
- pump/Stokes settings,
- custom values and labels.

If the loaded preset was saved for a different dataset with a different channel count, the GUI warns that the spectral axis may not match the current image. In that case, update the axis manually or reload from `wavelength.json`.

---

## Interpolation for Loaded Spectra

When reference spectra are loaded from `.txt`, `.asc`, or `.csv` files, the loader re-samples them onto the current image spectral axis by linear interpolation. This means:

- the loaded file can have any sampling; the GUI handles axis conversion,
- if the file axis is shorter than the image axis, the loader extrapolates at the edges and logs a warning,
- providing numeric `custom_values` (not just labels) is important if external spectra will be loaded and resampled.

---

## Common Mistakes

**File not detected**: the file must be named `wavelength.json` (lowercase, exact spelling) and placed directly next to the TIFF, not in a subdirectory or parent folder.

**Wrong channel count**: if the JSON has 10 values but the TIFF has 12 channels, the GUI logs a warning and falls back to channel indices.

**Invalid JSON**: trailing commas and unquoted keys are not valid JSON. Use a JSON validator before placing the file.

**Labels-only axis with external spectra**: if only text labels are given and no numeric values, the GUI cannot interpolate loaded reference spectra onto the axis. Provide `custom_values` as well.
