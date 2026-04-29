# 02 Analysis modes

This page is the practical companion to the deeper reference page [NNMF and NNLS modes](../reference/nnmf_nnls_modes.md).

Use the two pages for different purposes:

- this page: choosing the right mode in the GUI and understanding what kind of result to expect,
- the reference page: understanding the algorithmic idea, matrix model, and the more theory-oriented explanation.

## Why different modes exist

Hyperspectral data is usually recorded as many grayscale slices over a spectral axis. Looking at all slices separately is often too slow and too ambiguous, especially when resonant signal, non-resonant background, and general intensity changes overlap.

All multivariate modes in this project try to reorganize that stack into a smaller number of component spectra and matching spatial maps that can be shown as false-color images. The main difference between the modes is how much prior knowledge they use and how strictly they enforce it.

## Common output convention

In the GUI, the result is always interpreted in the same broad way:

- spectral curves describe the component behavior across the spectral axis,
- component maps describe where that behavior appears in the image,
- false-color composites merge several component maps into one interpretable view.

In the thesis language:

- the spectral matrix contains the spectral response or fingerprint-like behavior,
- the spatial matrix contains the contribution of that behavior at each pixel.

## PCA

### What it means

PCA is the least guided mode. It looks for the strongest variance patterns in the dataset, not for chemically pure or non-negative components.

In practice, PCA is best understood as a diagnostic or exploratory tool:

- it shows the dominant correlations in the data,
- it often reveals the strongest resonances quickly,
- it can also highlight gradients, background trends, tilt, or acquisition artifacts.

### What the GUI result means

- the spectral plots are principal components or loadings,
- the images are score maps,
- negative values are allowed internally, so the result is not a direct abundance interpretation.

### When to use PCA

- first look at a completely unknown dataset,
- checking whether strong gradients or artifacts dominate the data,
- estimating how many major patterns may be present,
- identifying approximate resonances before switching to a seeded method.

### Main limitation

PCA can split one chemical contribution over several components and can mix chemistry with unrelated variance. This is one of the central reasons why the thesis treats PCA as useful for orientation, but not usually as the final physically interpretable result.

## Random NNMF

### What it means

Random NNMF assumes the data can be described as an additive combination of non-negative component spectra and non-negative spatial maps. Unlike PCA, it does not allow positive and negative cancellation.

That makes the result often easier to interpret as a composition of physically meaningful parts.

### What the GUI result means

- the component spectra are discovered from the data,
- the spatial maps are also discovered from the data,
- neither one is guided by user seeds at the start.

### When to use random NNMF

- when no reliable seed spectra are available yet,
- when you want an unguided non-negative first pass,
- when you want to generate candidate components that can later be imported back as seeds.

### Main limitation

Random NNMF can depend strongly on initialization and data quality. In difficult low-SNR data, it may drift into less meaningful decompositions. In the thesis, this was one of the main reasons to prefer custom or seeded NNMF once reasonable prior information exists.

## Seeded NNMF

### What it means

Seeded NNMF uses the same non-negative decomposition model as random NNMF, but starts from user-provided prior information.

This prior information can include:

- spectral seeds,
- ROI-derived spectra,
- Gaussian resonance models,
- fixed W maps,
- imported result components,
- background-related seed information.

The seeds are initial conditions, not hard constraints. The algorithm is still allowed to adapt both spectra and maps during fitting.

### What the GUI result means

- the output still comes from a fitted NNMF result,
- but the clustering is guided toward the seeded interpretation,
- component names, colors, and expected meaning usually follow the seed setup much better than in random NNMF.

### When to use seeded NNMF

- when approximate resonances are already known,
- when ROI spectra exist,
- when background needs dedicated handling,
- when spectral overlap is strong,
- when random NNMF or PCA gave only a rough initial guess.

### Why this is often the main workflow

This is the mode that best matches the custom workflow developed in the thesis. It is usually the most flexible compromise:

- more stable and interpretable than PCA or random NNMF,
- but less rigid than fixed-H NNLS,
- and still able to adapt if the initial seeds are only approximate.

### Important practical note about W seeds

If only spectral seeds are given, the GUI still has to build spatial starting maps. Different W-seed modes exist for that step, such as:

- NNLS abundance map,
- selective score map,
- H-weighted average,
- average image,
- homogeneous fallback.

These are initialization choices inside seeded NNMF. They do not change the fact that seeded NNMF itself still updates both `W` and `H` afterwards.

For the exact difference between these W-seed modes, see:

- [Seeds, spectra, and W maps](03_seeds_spectral_and_spatial.md)
- [NNMF and NNLS modes](../reference/nnmf_nnls_modes.md)

## Fixed-H NNLS

### What it means

Fixed-H NNLS is the strictest seeded mode. Here the spectra are treated as trusted and kept fixed. Only the spatial abundances are fitted.

This turns the problem into:

- the spectral basis is known,
- find how much of each basis spectrum is present in each pixel.

### What the GUI result means

- the spectra are not allowed to drift,
- the maps are abundance-like coefficient maps with respect to the fixed spectra,
- results are easier to compare across slices or time points because the basis stays constant.

### When to use fixed-H NNLS

- when the seed spectra are already reliable,
- when you want strict comparability across z or time,
- when 4D data should be fitted efficiently with a stable spectral basis,
- when adaptation of the spectra would be undesirable.

### Main limitation

If the fixed spectra are wrong or incomplete, the spatial maps can still be mathematically consistent but scientifically misleading. This mode is only as good as the supplied spectra.

There is also a display-side tradeoff: fixed-H NNLS can be numerically more faithful once the spectra are trusted, but the resulting abundance maps and false-color composites may look grainier or more pixelated than NNMF results. This is not automatically a worse fit. It often reflects the fact that NNLS solves pixelwise coefficients very strictly and does not enforce the same visually smooth component adaptation that NNMF can produce.

## Recommended workflow

For many real datasets, the most practical sequence is:

1. Inspect the raw stack and ROIs.
2. Run PCA for a first overview of major variance and possible resonances.
3. If useful, run random NNMF to get an initial non-negative decomposition.
4. Import good result components or ROI spectra as seeds.
5. Run seeded NNMF for the main user-guided decomposition.
6. Once the spectral basis is stable, use fixed-H NNLS for strict comparison across slices, fields of view, or time series.

This also reflects the thesis conclusion well: PCA and random NNMF are strong exploratory tools, but seeded NNMF and fixed-H NNLS are the modes that become most valuable once the user has gained meaningful prior knowledge of the sample.

## Which page should I read next?

- If you want the mathematical and conceptual explanation:
  [NNMF and NNLS modes](../reference/nnmf_nnls_modes.md)
- If you want to understand seeds and W-seed generation:
  [Seeds, spectra, and W maps](03_seeds_spectral_and_spatial.md)
- If you want to start using the GUI immediately:
  [Quickstart](../quickstart.md)
