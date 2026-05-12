# NNMF and NNLS modes

This page explains the multivariate modes used by the GUI from two angles at once:

- the intuitive picture needed to understand what the modes are doing,
- the mathematical model actually implemented by the software.

For the more workflow-oriented explanation, see [02 Analysis modes](../tutorials/02_analysis_modes.md).

## Why these modes are needed

Hyperspectral CRS, CARS, SRS, Raman, or fluorescence stacks are usually recorded as many grayscale slices across a spectral axis. Looking at dozens of slices one by one is slow and often misleading because the relevant information is spread across the whole stack.

The point of multivariate analysis in this project is therefore not only dimensionality reduction in the abstract. It is a practical reorganization of the stack into:

- a small set of spectral patterns,
- a matching set of spatial maps,
- and finally a false-color view that makes the dominant structures easier to inspect in one image.

This follows the same motivation described in the thesis: the raw stack contains a lot of information, but much of it is redundant, background-dominated, or difficult to interpret slice by slice. The analysis modes compress that information into a smaller number of components that can be inspected as spectra and maps.

## Data layout

The image stack is reshaped into a 2D data matrix

$$
X \in \mathbb{R}_{\ge 0}^{n_\mathrm{pixels} \times n_\mathrm{channels}}
$$

where each row is one pixel spectrum and each column is one spectral channel.

In the NNMF and NNLS-based modes, the target factorization is

$$
X \approx W H
$$

with

- \(W \in \mathbb{R}_{\ge 0}^{n_\mathrm{pixels} \times n_\mathrm{components}}\): spatial maps or abundances,
- \(H \in \mathbb{R}_{\ge 0}^{n_\mathrm{components} \times n_\mathrm{channels}}\): component spectra.

In the GUI:

- each row of `H` is shown as a spectrum,
- each column of `W` is reshaped back into an image,
- the result viewer combines selected `W` maps into false-color composite images.

That interpretation is the same physical picture emphasized in the thesis: `H` carries spectral behavior, `W` carries where that behavior occurs spatially.

There is a component-wise scale ambiguity in NNMF: for any positive constant \(a\), replacing one component by \(a W_i\) and \(H_i / a\) leaves that component's contribution unchanged. This is why normalized generated W seeds are valid for seeded NNMF: both `W` and `H` remain free during fitting, so the optimizer can adapt the matching `H` row to the normalized `W0` scale. The GUI uses this convention for seeded NNMF initialization: generated `W0` maps are normalized to a comparable unit maximum, while `H0` spectra keep the spectral/count scale from ROIs, files, Gaussian models, or seed pixels.

## PCA

### Intuition

PCA does not try to find chemically pure components. It asks a different question:

> Along which spectral directions does the dataset vary the most?

Geometrically, PCA can be understood as a rotation of the coordinate system. Instead of describing each pixel by the original spectral channels, it creates new orthogonal axes, the principal components, that point along the strongest variance directions in the data [1].

The first principal component explains the largest variance, the second explains the largest remaining variance under the constraint of being orthogonal to the first, and so on.

That makes PCA very useful for:

- fast inspection of an unknown dataset,
- detecting dominant gradients and correlations,
- estimating how many major patterns are present,
- spotting artifacts that affect many channels together.

### Model

Before PCA, the GUI standardizes each spectral channel:

$$
Z_{p,j} = \frac{X_{p,j} - \mu_j}{\sigma_j}
$$

It then estimates

$$
Z \approx T P
$$

where:

- `P` contains the principal component spectra or loadings,
- `T` contains the corresponding pixel scores.

### Interpretation in this project

PCA is often a very good first look, but it has important limitations for chemical interpretation:

- the components are orthogonal by construction, not chemically independent,
- negative values are allowed,
- one molecular signature can be split over several components,
- strong non-chemical correlations can dominate the leading components.

This matches the practical observations summarized in the thesis: PCA often reveals the important resonances, but it can mix chemistry with gradients, split one resonance across several components, and produce signed outputs that are awkward to interpret physically.

Use PCA when you want a diagnostic or an initial estimate, not when you need strictly non-negative abundance-like maps.

## Random NNMF

### Intuition

NNMF replaces the PCA rotation picture with an additive mixing picture:

> Each pixel spectrum is approximated as a non-negative sum of a few non-negative component spectra.

That is often much easier to interpret for imaging data because intensities and abundances are naturally non-negative. The decomposition is also often described as parts-based [3, 4]: instead of allowing positive and negative cancellation, the model builds each pixel from additive contributions only.

Historically, this class of methods was already used under the name positive factorization before the Lee and Seung NNMF papers made it widely known [2, 3].

### Model

Random NNMF solves

$$
W, H =
\arg\min_{W \ge 0,\; H \ge 0}
\left\| X - W H \right\|_F^2
$$

starting from unguided initial matrices.

The result is exploratory:

- spectra and maps are both discovered from the data,
- no seed information is enforced,
- different initializations can lead to different local optima.

### Interpretation in this project

Random NNMF is useful when no reliable prior spectra exist yet. It is usually more physically intuitive than PCA because the result is additive and non-negative, but it is still not guaranteed to find the chemically preferred decomposition.

In practice it works best as:

- a first non-negative exploratory pass,
- a source of candidate result components that can later be imported back as seeds,
- a comparison point against seeded NNMF.

## Seeded NNMF

### Intuition

Seeded NNMF keeps the same non-negative matrix factorization model but starts from prior knowledge instead of random guesses.

Conceptually, the question becomes:

> If I already have a rough idea what some spectra or maps should look like, can the algorithm refine them while still adapting to the data?

This is the mode closest to the custom NNMF logic described in the thesis. The thesis repeatedly shows why this matters for difficult CRS data: if resonances overlap strongly or the signal-to-background ratio is poor, unguided methods can mix components, but a seeded decomposition can be steered toward the desired clustering.

### Model

The optimization target stays the same:

$$
W, H =
\arg\min_{W \ge 0,\; H \ge 0}
\left\| X - W H \right\|_F^2
$$

but the solver starts from user-guided seeds

$$
W \leftarrow W_0,\qquad H \leftarrow H_0
$$

and then updates both matrices.

That means the seeds are not hard constraints. They are informed initial conditions:

$$
X \approx W_0 H_0
\quad \longrightarrow \quad
X \approx W^* H^*
$$

### What can become a seed

`H0` can come from:

- ROI average spectra,
- imported spectra,
- Gaussian resonance models,
- previous result spectra,
- spectral information entered in the GUI.

`W0` can come from:

- fixed W seeds,
- imported result maps,
- background maps,
- or from one of the H-driven W-seed estimation modes.

### W-seed modes

If only a spectral seed is available, the GUI estimates `W0` from the data and the current `H0`. The active W-seed mode decides how:

- `nnls`: coefficient maps from a non-negative least-squares fit,
- `selective_score`: a heuristic map based on target projection and competition against other seeded spectra,
- `h_weighted`: a legacy channel-weighted image heuristic,
- `average`: average image fallback,
- `empty`: almost neutral homogeneous fallback.

The important separation is:

- missing or incomplete `H` is discovered from the current basis through the residual-based seed logic,
- once a usable `H` exists, the final `W` seed for that component is built with the selected W-seed mode.

So the basis finding and the W-map construction are related, but they are not the same step.

### Residual-based H seed fallback

When a component has no usable `H0` spectrum, the GUI tries to estimate one from the residual that is not explained by the already seeded components:

1. Build a basis from the existing non-empty `H0` rows.
2. Choose the component's working data. Background components use raw data. Other components use processed/background-subtracted data unless their **Use subtracted data** setting says to use raw data.
3. Solve a non-negative least-squares fit of the existing basis against each pixel spectrum.
4. Subtract that fitted signal from the working data and keep the positive residual.
5. Select strong residual pixels, optionally using the score-based metric to prefer spectra that are not already well described by the current basis.
6. Normalize candidate residual spectra by their own maxima, average them, smooth the average, and clamp it positive.
7. Rescale the new spectrum to the amplitude scale of the existing `H0` basis where possible.

If this residual estimate is not usable, the older random smooth fallback is used. In fixed-H NNLS, this residual-filled `H` becomes part of the locked spectral basis, so it should be treated as an emergency fallback rather than as a trusted reference spectrum.

### Spectral information and W overwrite

The **Overwrite existing W with H-based map** option controls whether W maps that came from spectral information are kept or replaced.

When overwrite is enabled and a component already has a valid `H0`, the spectral-info W image is not used as the final `W0`. The GUI rebuilds that component's spatial map from `H0` with the selected W-seed mode. With the NNLS W-seed mode, this is an abundance map fitted from the fixed seed basis.

In that situation, spectral-info parameters such as resonance center, width, amplitude, and seed-pixel count usually do not shape the final W map. The main exception is the **Use subtracted data** flag, which can still choose raw versus processed/background-subtracted data for H-based W estimation and residual H-seed estimation. Spectral information can also still matter when it is used to create a missing H seed before the H-based W map is rebuilt.

Disable overwrite when the W image gathered from spectral information should remain the actual spatial seed.

Generated `W0` maps are normalized per component before seeded NNMF starts. This includes NNLS abundance-map seeds and image-derived fallback seeds. The normalization is only an initialization convention: the NNMF solver can still rescale each W/H component pair during fitting because it updates both matrices.

### Why seeded NNMF is often the most practical mode

Seeded NNMF is usually the most useful mode when you already know something about the sample, but do not want to freeze the spectral basis completely.

This is especially valuable when:

- two resonances overlap spectrally,
- background needs one or more dedicated components,
- some components are weak,
- you want the decomposition to follow known labels or ROIs,
- PCA or random NNMF gave only a rough first estimate.

This is also the mode where the GUI's custom seed logic matters most. It can take spectral priors, ROI averages, background information, and W-map hints and turn them into an initialization that is much more stable than random NNMF on difficult data.

## Fixed-H NNLS

### Intuition

Fixed-H NNLS is the strictest seeded mode. Once you trust the spectra, you stop asking the algorithm to discover new spectral shapes and ask only:

> How much of each fixed spectrum is present in each pixel?

That is a pure abundance-fit problem. It is especially useful when you want stable spectra across slices, time points, or different fields of view.

### Model

Fixed-H NNLS solves only for `W`:

$$
W =
\arg\min_{W \ge 0}
\left\| X - W H_{\mathrm{seed}} \right\|_F^2
$$

For each pixel spectrum \(x_p\):

$$
w_p =
\arg\min_{w_p \ge 0}
\left\| x_p - w_p H_{\mathrm{seed}} \right\|_2^2
$$

Here the seeded spectra stay fixed. Only the spatial coefficients are fitted.

Because `H_seed` is fixed, the fitted `W` in fixed-H NNLS is not just a seed scale convention. The NNMF scale ambiguity is only harmless when both sides of a component pair can be rescaled together. In fixed-H NNLS, rescaling W alone changes \(W H_{\mathrm{seed}}\) and therefore changes the fit. Internally, these fixed-H NNLS coefficients should therefore remain on their fitted scale rather than being normalized to unit maximum. Display and export scaling can still be applied afterward for visualization.

### Interpretation in this project

This mode is ideal when:

- the reference spectra are already trusted,
- you want comparable abundance maps across z or time,
- you do not want the spectral basis to drift between slices,
- you want the most controlled seeded analysis.

In 4D workflows this is often the cleanest way to reuse one spectral basis and solve only for the changing spatial maps.

One practical consequence is important for image interpretation: fixed-H NNLS can be more accurate in the sense that each pixel is fitted very strictly against the trusted basis, but the displayed maps can look grainier or more speckled than NNMF maps. The false-color composite may therefore look less smooth even when the coefficient estimates are scientifically the more defensible result. In this project, visual smoothness and numerical faithfulness should not be confused automatically.

## Practical choice

The modes are best viewed as a progression of prior knowledge:

- `PCA`: discover variance directions.
- `Random NNMF`: discover non-negative additive components.
- `Seeded NNMF`: guide the decomposition but still let spectra adapt.
- `Fixed-H NNLS`: keep spectra fixed and solve only abundances.

For difficult CARS data, the practical conclusion from the thesis still holds up well:

- PCA and random NNMF are very useful first passes,
- seeded NNMF is usually the strongest general-purpose mode when prior information exists,
- fixed-H NNLS is the most stable mode once the spectral basis is considered trustworthy.

## References

1. Ali Cinar, Ahmet Palazoglu, and Ferhan Kyihan, *Chemical Process Performance Evaluation*, CRC Press, 2019. Useful for the geometric and covariance-based interpretation of PCA.
2. Pentti Paatero, Unto Tapper, Pasi Aalto, and Markku Kulmala, "Matrix factorization methods for analysing diffusion battery data," *Journal of Aerosol Science* 22, S273-S276, 1991. Historical positive factorization background.
3. Daniel D. Lee and H. Sebastian Seung, "Algorithms for Non-negative Matrix Factorization," *Advances in Neural Information Processing Systems* 13, 2001. Canonical NNMF algorithms.
4. Jean-Philippe Brunet, Pablo Tamayo, Todd R. Golub, and Jill P. Mesirov, "Metagenes and molecular pattern discovery using matrix factorization," *PNAS* 101(12), 4164-4169, 2004. Classic parts-based and clustering-oriented interpretation of NMF.
5. Christian Pilger, *Development of novel Optics and Analysis Tools for enhancing Biomedical Imaging by Coherent Raman Scattering*, PhD thesis, University of Bielefeld, 2019. Group-specific CRS and analysis context.
6. Paul Greife, *Implementation of a Hyper-Spectral Image Scan Capability in a Coherent Anti-Stokes Raman Scattering (CARS) Microscope*, Master's thesis, University of Bielefeld, 2017. Project-specific image-stack reshaping and acquisition context.
7. Branko Vukosavljevic et al., "Vibrational spectroscopic imaging and live cell video microscopy for studying differentiation of primary human alveolar epithelial cells," *Journal of Biophotonics* 12(6), e201800052, 2019. Example application of CRS imaging with biologically meaningful spectral separation.
8. Chaoyang Zhang, Delong Zhang, and Ji-Xin Cheng, "Coherent Raman Scattering Microscopy in Biology and Medicine," *Annual Review of Biomedical Engineering* 17, 415-445, 2015. Broader motivation for CRS imaging in biological and clinical settings.
