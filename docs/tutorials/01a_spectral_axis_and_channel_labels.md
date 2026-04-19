# 01a Spectral Axis And Channel Labels

The spectral axis tells the GUI what each image channel represents. Depending on the experiment, this can be a Raman shift, a wavelength, a channel index, or a custom label such as a dye name.

## Calculated Pump/Stokes Axis

For CRS/CARS/SRS data, the GUI can calculate Raman shifts from pump and Stokes wavelengths.

Use the calculated mode when the spectral stack was acquired by scanning one beam while the other beam stayed fixed.

Inputs:

- tuned wavelength minimum,
- tuned wavelength maximum or step size,
- fixed wavelength,
- which beam was tuned.

The result is a Raman axis in:

```text
cm^-1
```

> GIF placeholder: changing pump/stokes settings and watching the spectral axis update.

## Wavelength Axis In nm

For hyperspectral fluorescence, SWIR, or other wavelength-resolved measurements, switch the unit to:

```text
nm
```

In this mode, the spectral axis is treated as wavelength rather than Raman shift.

## Manual / Custom Axis

Use the custom/manual mode when the channel positions are not described by a simple pump/Stokes calculation.

The custom axis can contain:

- numeric values, such as `720, 740, 760`;
- text labels, such as `DAPI, FITC, Cy5`.

Numeric values are used as the x-axis values in plots. Text labels are shown as channel labels, and the internal x-axis becomes a simple channel index.

> Screenshot placeholder: custom spectral axis dialog with numeric wavelength values.

## wavelength.json

If a file named `wavelength.json` is placed next to the loaded TIFF, the GUI tries to apply it automatically.

Accepted keys are:

- `spectral_unit` or `unit`.
- `custom_values` or `custom_points`.
- `custom_labels` or `labels`.

Example with numeric wavelengths:

```json
{
  "spectral_unit": "nm",
  "custom_values": [700, 750, 800]
}
```

Example with dye labels:

```json
{
  "custom_labels": ["DAPI", "FITC", "Cy5"]
}
```

Example with values and labels:

```json
{
  "spectral_unit": "nm",
  "custom_values": [405, 488, 640],
  "custom_labels": ["DAPI", "FITC", "Cy5"]
}
```

The number of values or labels should match the number of spectral channels in the loaded stack.

For Raman-shift data, use a wavenumber unit:

```json
{
  "spectral_unit": "cm^-1",
  "custom_values": [2850, 2900, 2950, 3000],
  "custom_labels": ["lipid CH2", "CH stretch", "protein CH3", "high CH"]
}
```

For label-only fluorescence or filter-channel data:

```json
{
  "labels": ["DAPI", "GFP", "mCherry"]
}
```

This creates a channel-index x-axis and uses the labels for display. If external spectra should be interpolated later, provide numerical `custom_values` as well.

> GIF placeholder: loading a TIFF folder with `wavelength.json` and custom labels appearing in the GUI.

## What Is Saved

The spectral-axis state is saved in the main JSON preset. This includes:

- calculated/custom source mode,
- unit,
- pump/Stokes settings,
- custom values,
- custom labels.

When a new dataset is loaded while a custom axis is active, the GUI warns that custom points are dataset-specific and switches back to calculated mode unless metadata are loaded again.
