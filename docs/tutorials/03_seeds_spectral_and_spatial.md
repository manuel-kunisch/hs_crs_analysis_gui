# 03 Seeds, Spectra, And W Maps

Seeds are the main way to guide the analysis. The GUI supports both spectral seeds and spatial seeds.

## H Seeds: Spectral Information

`H` seeds describe what the component spectra should look like.

They can come from:

- ROIs drawn directly in the image,
- spectra loaded from files,
- Gaussian resonance models,
- previous NNMF results imported back into the ROI manager.

For seeded NNMF and NNLS-based seed generation, these spectra are kept on their physical amplitude scale. The GUI does not normalize each seed spectrum independently before building the spectral model. This keeps the relation between `W` and `H` consistent with the underlying factorization idea \(X \approx WH\).

In the ROI table, these appear as normal ROI rows or dummy ROI rows. A dummy ROI does not need to correspond to a drawn spatial region; it can carry a spectrum or a fixed W map.

> GIF placeholder: drawing a ROI and seeing its spectrum appear in the ROI average plot.

## W Seeds: Spatial Information

`W` seeds describe where a component is expected to be present spatially.

The GUI can estimate W maps from H seeds using different modes:

- NNLS abundance map,
- selective score map,
- H-weighted average,
- average image fallback,
- homogeneous empty map.

The modes do not all have the same meaning. The NNLS abundance map is a direct coefficient estimate from the seeded spectra. The selective score map is a heuristic spatial guess based on spectral projection and competition. For that score-map mode, the GUI leaves `H` unchanged and rescales the resulting `W` seed map afterward to unit maximum. The other seed modes keep their natural numeric scale.

Fixed W maps can also be attached to dummy ROIs. These fixed W seeds are useful for background components or for importing spatial maps from previous results.

## ROI-Derived Seeds

For normal spatial ROIs, the mean spectrum inside the ROI can be used as an H seed. Multiple ROIs assigned to the same component can be averaged.

Use ROI-derived seeds when a visible region is representative for a component.

## Gaussian Resonance Seeds

Gaussian models can be generated from manually defined resonance settings. This is useful when the approximate spectral position and width of a component are known.

The Gaussian model creates a dummy ROI row for the relevant component. The row behaves like a spectral seed without requiring a spatial ROI.

> GIF placeholder: adding a resonance setting and seeing a Gaussian dummy ROI appear.

## Auto-Suggested ROIs

The ROI suggestion tool searches for bright or structured image regions that can be useful seed candidates.

The method first looks for spatial candidate regions and then optionally groups or filters them by spectral similarity. This helps avoid collecting many ROIs with nearly identical spectra when the user wants several distinct component groups.

Important settings include:

- projection mode,
- local background subtraction scale,
- smoothing,
- threshold ratio,
- minimum area,
- minimum ROI diagonal,
- number of groups,
- ROIs per group,
- spectral similarity threshold.

> GIF placeholder: running Suggest ROIs and accepting suggested ROI boxes.

## Display In The ROI Table

The ROI table stores component assignment, color, label, scaling, offset, background/subtraction flags, plotting options, and remove/show actions.

For a detailed explanation of every ROI Manager button, row type, and table column, see [ROI Manager in detail](03b_roi_manager.md).

Rows can represent:

- drawn spatial ROIs,
- loaded spectra,
- Gaussian model spectra,
- imported result spectra,
- W-only result/background seeds.

Rows with fixed W seeds can show their W map without plotting a fake H spectrum.

## Exporting Seeds

Seeds and ROI state can be saved through presets. Spectral components can also be exported as CSV from the result viewer. For reproducible workflows, save the preset together with the input data and expected output.
