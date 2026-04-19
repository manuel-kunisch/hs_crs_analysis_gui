# Reproduce Figure 1

This example will describe how to recreate the main overview figure for the paper. It should connect the GUI concept, seed definition, analysis modes, 4D support, preprocessing, and export.

## Goal

Create one figure that shows how the GUI turns hyperspectral or multispectral image stacks into interpretable component maps and spectra.

The figure should emphasize:

- Raw image stacks become physically interpretable component images.
- Seeds can be defined from ROIs, spectra, Gaussian resonances, previous results, or fixed W maps.
- NNMF can update both spectra and abundance maps.
- Fixed-H NNLS can apply known spectra efficiently.
- 4D data can be analyzed slice by slice or time point by time point.
- Result exports preserve labels, LUTs, physical units, and Fiji/ImageJ compatibility.

## Suggested panel structure

Panel A: GUI workflow concept.

Show data loading, spectral axis definition, seed table, solver selection, result viewer, and export.

> Placeholder: insert annotated GUI screenshot or schematic.

Panel B: Seed definition.

Show spectral seeds, spatial seeds, ROI seeds, Gaussian seeds, CSV-loaded spectra, and fixed W/background seeds.

> Placeholder: insert ROI manager screenshot with labeled seed types.

Panel C: CARS/SRS label-free example.

Show a label-free dataset such as liver or tissue imaging. Include raw spectral channels, NNMF or NNLS result maps, and recovered spectra.

> Placeholder: insert CARS/SRS result composite and H spectra.

Panel D: SWIR or multispectral reflection example.

Show decomposition of reflection or multispectral data, for example mouse or cholesteatoma data. Highlight custom labels or wavelength units if relevant.

> Placeholder: insert SWIR or multispectral result composite.

Panel E: 4D fluorescence example.

Show a stack with dimensions `(x, y, channel, z)` or `(x, y, channel, time)`. Include the result slice selector concept and a montage over z/time.

> Placeholder: insert 4D fluorescence result montage.

Panel F: Reproducibility and export.

Show saved presets, Fiji/ImageJ export with LUTs and labels, and exported spectral CSV files.

> Placeholder: insert Fiji screenshot and preset/export files.

## Files to provide

Replace these placeholders with real files before publication:

- `data/figure_1/cars_srs/`
- `data/figure_1/swir/`
- `data/figure_1/fluorescence_4d/`
- `presets/figure_1_cars_srs.json`
- `presets/figure_1_swir.json`
- `presets/figure_1_fluorescence_4d.json`
- `exports/figure_1_composites/`
- `exports/figure_1_spectra/`

## Workflow

1. Load the dataset for the panel.
2. Load or define the spectral axis.
3. Load the matching preset.
4. Verify ROI names, component numbers, and colors.
5. Run the selected analysis mode.
6. Inspect result maps and spectra.
7. Export the Fiji-compatible TIFF.
8. Export H spectra as CSV.
9. Save final application and result presets.
10. Assemble the figure panels in the external figure editor.

> GIF placeholder: complete Figure 1 panel generation from preset to Fiji export.
