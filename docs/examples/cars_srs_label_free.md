# CARS/SRS label-free example

This example will show label-free chemical imaging with CARS or SRS data.

## Planned workflow

1. Load a CARS/SRS TIFF stack.
2. Define the Raman shift axis from pump and Stokes settings or from metadata.
3. Draw ROIs on chemically distinct regions.
4. Optionally add Gaussian resonance seeds.
5. Run seeded NNMF.
6. Compare with fixed-H NNLS if stable spectra are available.
7. Export component maps and spectra.

## Points to highlight

- Raman shift units in `1/cm`.
- ROI-derived spectral seeds.
- NNMF interpretation as abundance maps and spectra.
- Label-free tissue contrast.
- Exported Fiji-compatible result maps.

> Placeholder: insert representative liver or tissue dataset.

> GIF placeholder: create ROI seeds and run seeded NNMF on CARS/SRS data.
