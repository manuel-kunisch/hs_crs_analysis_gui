# SWIR or multispectral reflection example

This example will show decomposition of multispectral reflection data, such as SWIR imaging.

## Planned workflow

1. Load a multispectral TIFF stack.
2. Load wavelength values or channel labels from `wavelength.json`.
3. Define spectral seeds or import reference spectra.
4. Run fixed-H NNLS or seeded NNMF.
5. Inspect component maps.
6. Export Fiji-compatible TIFF and spectral CSV files.

## Points to highlight

- Wavelength units in `nm`.
- Custom channel labels.
- Fixed-H NNLS with known spectra.
- Reuse of presets across fields of view.
- Application to mouse or cholesteatoma data.

> Placeholder: insert representative SWIR or reflection dataset.

> GIF placeholder: load wavelength metadata and run fixed-H NNLS.
