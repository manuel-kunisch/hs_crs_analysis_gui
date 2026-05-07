# 03 Seeds, Spectra, And W Maps

Seeds are the main way to guide the analysis. The GUI supports both spectral seeds and spatial seeds.

## H Seeds: Spectral Information

`H` seeds describe what the component spectra should look like.

They can come from:

- ROIs drawn directly in the image,
- spectra loaded from files,
- Gaussian resonance models,
- previous NNMF results imported back into the ROI manager.

For spectra loaded from files, the imported spectrum is re-sampled to the current image spectral axis before analysis. The seed actually used by NNMF or NNLS is therefore the prepared spectrum on the active image axis, not the raw file sampling.

For seeded NNMF and NNLS-based seed generation, these spectra are kept on their physical amplitude scale. The GUI does not normalize each seed spectrum independently before building the spectral model. This keeps the relation between `W` and `H` consistent with the underlying factorization idea \(X \approx WH\).

If a component is missing an `H` seed entirely, the GUI now tries a special fallback before using the older random smooth spectrum. It first fits the already-seeded components to the data, forms a positive residual, averages a small set of strong residual spectra, and uses that residual-derived shape as the missing `H` seed. That fallback spectrum is then rescaled to match the existing `H` seed basis as closely as possible, so it starts on a comparable amplitude scale instead of on the smaller residual-data scale. If no stable residual candidate can be built, the legacy random smooth fallback is still used.

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

| Mode | When to use |
|---|---|
| `nnls` | Default. Gives a direct non-negative least-squares estimate of the spatial distribution. Best starting point for most datasets. |
| `selective_score` | Useful when NNLS mixes similar components. Weights the spatial estimate by how uniquely the target spectrum explains the signal compared with competing spectra. |
| `h_weighted` | Legacy channel-weighted heuristic. Rarely needed, but can help when NNLS is unstable. |
| `average` | Uses the mean image. A neutral starting point that lets NNMF build all spatial structure from scratch. |
| `empty` | Near-zero homogeneous map. Use this when a component should be discovered entirely from the data without a spatial prior. |

For the special case above where an `H` seed is missing, the residual spectrum is first derived from a fit against the already available `H` seeds. In the default case, strong residual pixels are ranked by residual strength. If the active `W`-seed mode is `selective_score`, those residual pixels are instead ranked by a novelty-weighted score that prefers strong unexplained signal over signal already well described by the existing seed basis.

Fixed W maps can also be attached to dummy ROIs. These fixed W seeds are useful for background components or for importing spatial maps from previous results.

## Seed Initialization Controls

The **Seed Initialization** controls in the **Analysis** panel decide how seed information is converted into starting matrices for NNMF or fixed spectra for NNLS.

| GUI control | What it affects | Practical default |
|---|---|---|
| **W map from H** | How the GUI estimates spatial W maps from available H spectra. | **NNLS abundance map (recommended)** |
| **H seed pixel metric** | How residual fallback pixels are ranked when a component is missing an H seed. | **Max Intensity** for ordinary use; **Score** when looking for spectrally novel residuals. |
| **Overwrite existing W with H-based map** | Whether H-based W estimation replaces existing W seeds or only fills missing W columns. | Enabled for a clean seeded run; disabled when you imported or generated fixed W maps that should stay dominant. |
| **Test seeds** | Builds the current seed matrices and opens the seed preview window without running the final analysis. | Use before long NNMF or 4D runs. |

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

![Suggest ROIs dialog](../assets/images/03_suggest_rois_dialog.png)

The dialog scans the current image stack without requiring resonance positions or reference spectra. It first collapses the stack into one 2D response image, enhances local bright structures, finds candidate regions, and then assigns suggested ROIs to available component numbers.

| Setting | What it controls | Practical effect |
|---|---|---|
| **Projection** | How the spectral stack is collapsed into one 2D response image. | **Balanced stack scan** rescales channels before combining them, so weak resonances are less likely to be hidden by one dominant channel. **Average image** favors structures that are bright across many channels. **Maximum projection** favors the brightest response in any channel. **Current frame** suggests ROIs only from the currently displayed channel. |
| **Processed data** | Whether the processed/background-subtracted stack is used when available. | Enable this if subtraction or preprocessing reveals the structures you want to seed better than the raw stack. It is disabled when no processed data are available. |
| **Local background sigma** | Size of the blurred background estimate subtracted from the projection. | Increase it to remove broad illumination gradients. Lower it if real broad structures are being suppressed. |
| **Spatial binning** | Downsampling before peak finding. | Higher binning is faster and more robust against pixel noise, but it can miss very small structures. |
| **Peak smoothing** | Spatial smoothing before candidate detection. | Increase it to suppress noisy speckles. Decrease it to keep sharp or small structures. |
| **Peak threshold** | Required brightness relative to the response map. | Lower values find more and weaker regions. Higher values keep only stronger candidates. |
| **Min group area** | Smallest connected bright region accepted as a candidate. | Increase it to reject tiny speckles or detector noise. |
| **Min ROI diagonal** | Minimum size of the final ROI box in pixels. | Use this to prefer larger structures. `0 px` effectively disables this size filter. |
| **Max suggested groups** | Maximum number of distinct spectral groups/components created in one run. | Increase it when several different components should be proposed at once. |
| **Max ROIs per group** | Maximum number of spatial ROIs kept for each spectral group. | Increase it when multiple examples of the same component are useful for averaging. |
| **Merge duplicates** | Whether regions with very similar mean spectra should be merged into one component group. | Usually keep this enabled so the suggester does not fill the ROI table with several copies of the same spectral class. |
| **Similarity threshold** | Spectral similarity required for duplicate merging. | Higher values merge fewer regions. Lower values merge more aggressively. |
| **Replace previous auto ROI suggestions** | Removes only earlier auto-suggested ROIs before creating new suggestions. | Keep it enabled while tuning settings. Disable it if you want to add another batch without removing earlier suggestions. |

After suggestions are created, treat them like normal ROIs: move or resize them if needed, rename the rows, assign colors, check the ROI average spectra, and remove suggestions that are not useful seeds.

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

## Background Components and Background Subtraction

### Background as a model component

The ROI Manager supports marking one or more rows as background components. To do this, enable the **Background** flag in the ROI table for that row. A component marked as background is included in the NNMF/NNLS model but is treated as the background contribution rather than a signal of interest.

This is different from preprocessing: a background component keeps the background signal inside the factorization model and explicitly assigns spatial variation to it, rather than removing it before analysis.

Use this approach when:

- the background varies spatially across the image,
- you want an explicit map of the background,
- you need the model to account for background during unmixing rather than hoping NNMF will separate it automatically.

A background W map can also be generated from the analysis panel using a projection image (mean, max, or min). This creates a dummy ROI carrying a fixed W seed derived from the projection.

### Subtraction of background components

The row marked with the **Subtract** flag defines a background ROI. The GUI averages the spectrum inside that ROI and subtracts that mean spectrum from every pixel in the raw stack. The result is shown in the **Processed** view in the raw image viewer.

The raw loaded image is not overwritten. However, processed/subtracted data can be used by seed estimation or analysis steps that explicitly request processed data, so check the Subtract state before running a final analysis.

> GIF placeholder: marking a component as background, generating a background W map, and viewing the subtracted result.

## Dummy ROIs and Fixed W Seeds

A dummy ROI is a row in the ROI Manager that carries seed information without being tied to a drawn spatial region. Dummy ROIs are used for:

- **Loaded spectra**: a file-based H seed without a spatial ROI.
- **Gaussian resonance models**: a Gaussian-shaped H seed for a known resonance position.
- **Fixed W seeds**: a spatial abundance map provided from outside the current analysis (for example, from a previous result or from a background projection image).
- **Imported result components**: a full H + W seed imported from a previous analysis run.

A dummy ROI carrying a fixed W map does not display a spectral plot for H; instead it shows the fixed W map directly. The W map stays fixed during NNMF if the row is configured as a fixed W seed.

This is useful when a reliable spatial reference exists (e.g., a clean background illumination map) and you do not want the model to re-estimate it from scratch.

## Importing Result Components as Seeds

After a PCA or NNMF run, result components can be imported back into the ROI Manager as seed rows. Import options:

- **H only**: the fitted spectrum becomes an H seed for a new run.
- **W only**: the fitted map becomes a fixed W seed.
- **H + W**: both are imported as a combined seed.

This is the standard iterative workflow:

1. Run random NNMF to get an initial non-negative decomposition.
2. Import the best result components as H seeds.
3. Adjust ROIs or add missing components.
4. Run seeded NNMF or fixed-H NNLS.

Imported result components appear as dummy ROI rows in the ROI Manager.

## Exporting Seeds

Seeds and ROI state can be saved through presets. Spectral components can also be exported as CSV from the result viewer. For reproducible workflows, save the preset together with the input data and expected output.
