# 4D fluorescence unmixing example

This example will show fluorescence or labeled multispectral data with an additional z or time axis.

## Planned workflow

1. Load a 4D TIFF stack.
2. Select the spectral channel axis.
3. Select the z or time axis.
4. Load custom labels such as dye or fluorophore names.
5. Define or load spectral seeds.
6. Run fixed-H NNLS or seeded NNMF across the stack.
7. Inspect the result with the 4D result slice selector.
8. Export a Fiji/ImageJ-compatible hyperstack.

## Points to highlight

- 4D input handling.
- Custom labels instead of only numerical wavelengths.
- Fast fixed-H NNLS when spectra are known.
- Hyperstack export with channel labels and LUTs.
- Time or z-dependent abundance maps.

> Placeholder: insert representative fluorescence 4D dataset.

> GIF placeholder: load 4D fluorescence data and scroll through result slices.
