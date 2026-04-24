# 02 Analysis modes

This page explains what the analysis modes do mathematically and how the results should be interpreted.

## The data matrix

The GUI starts from a spectral image stack (either 3D or 4D) and reshapes it into a 2D matrix:

```text
X = pixels x channels
```

Each row `x_p` is the spectrum of one pixel. Each column is one spectral channel, wavelength, Raman shift, or custom channel.

Most multivariate modes then try to describe `X` by a smaller number of components:

$$
X \approx W H
$$

where:

- `H` contains component spectra.
- `W` contains spatial component maps or abundances.

Implementation-shaped view:

```text
X.shape = (n_pixels, n_channels)
W.shape = (n_pixels, n_components)
H.shape = (n_components, n_channels)

X_reconstructed = W @ H
```

The result viewer shows `W` as component images and `H` as component spectra.

## PCA

PCA is an exploratory variance decomposition. It does not use seeds and it does not know anything about chemistry, labels, spectra, or ROIs.

Before PCA, the GUI standardizes every spectral image channel:

$$
Z_{p,j} =
\frac{X_{p,j} - \mu_j}{\sigma_j}
$$

Here, `j` is the channel index. This gives every channel approximately zero mean and unit standard deviation before PCA is applied.

Implementation-shaped view:

```text
for channel j:
    Z[:, j] = (X[:, j] - mean(X[:, j])) / std(X[:, j])
```

PCA then finds orthogonal directions in spectral space:

$$
Z \approx T P
$$

where:

- `P` contains the principal component spectra/loadings.
- `T` contains the pixel scores.

Implementation-shaped view:

```text
T = PCA.fit_transform(Z)
P = PCA.components_

score_images = reshape_pixels_to_images(T)
component_spectra = P
```

The first principal component explains the largest possible variance in the standardized data. The second explains the largest remaining variance under the constraint that it is orthogonal to the first, and so on.

In the GUI result:

- The PCA score columns `T` are reshaped back into images.
- The principal components `P` are shown as spectral components.
- Negative score images are shifted for display, so the displayed image is not a direct concentration map.

PCA is fully determined by the dataset and preprocessing, apart from the usual sign ambiguity of PCA components. It is therefore excellent as a diagnostic, but it is not a user-guided unmixing method.

Important limitation: PCA finds variance, not chemical truth. Strong non-chemical correlations can dominate the result, for example:

- tilted sample or focus gradient,
- illumination gradient,
- sample thickness variation,
- detector offset or stripe artifacts,
- motion or stitching artifacts,
- broad intensity changes shared by many channels.

This means a clean-looking PCA component can still describe an acquisition artifact or global intensity correlation rather than a molecular species.

Use PCA when:

- You want to inspect dominant variance patterns.
- You want a quick diagnostic.
- You do not yet know how many components are useful.
- You want to detect gradients, artifacts, or correlated intensity changes.

PCA is usually not the final mode for physically interpretable non-negative component maps.

## Random NNMF

Random NNMF estimates non-negative spectra and non-negative spatial maps:

$$
W, H =
\arg\min_{W \ge 0,\; H \ge 0}
\left\| X - W H \right\|_F^2
$$

Implementation-shaped view:

```text
W, H = fit_nmf(
    X,
    n_components=k,
    init="random",
    update_w=True,
    update_h=True,
)
```

Unlike PCA, NNMF is applied to the non-negative data matrix and constrains both `W` and `H` to be non-negative. This makes the result more similar to an abundance-map interpretation.

In random NNMF, the initial `W` and `H` are not taken from user seeds. The code uses fixed random seeds for reproducibility where supported, but the decomposition is still not guided by physical prior knowledge.

Use random NNMF when:

- No reliable prior spectra are available.
- You want an exploratory non-negative decomposition.
- You want to compare seeded and unseeded results.
- You want to generate a first candidate decomposition that can later be converted into seeds.

Because NNMF is not a convex problem in `W` and `H` together, the result can depend on initialization, component number, solver, preprocessing, and data scaling. Component order is also not physically meaningful by itself.

Random NNMF can therefore be used as a starting point for an iterative workflow. A useful component from the random result can be imported back into the ROI manager as an `H` seed, a `W` seed, or both. This can be done for only selected components. The next analysis can then be run as seeded NNMF or fixed-H NNLS using the imported result components as prior information.

Typical workflow:

```text
run random NNMF
inspect W maps and H spectra
import useful result component(s) into ROI manager
rename and assign component numbers
rerun as seeded NNMF or fixed-H NNLS
```

This is useful when no clean ROI seed is obvious at the beginning, but the first random decomposition separates at least one meaningful structure.

## Seeded NNMF

Seeded NNMF solves the same NNMF problem as random NNMF:

$$
W, H =
\arg\min_{W \ge 0,\; H \ge 0}
\left\| X - W H \right\|_F^2
$$

The difference is the initialization. Instead of starting from random matrices, the GUI builds initial estimates:

$$
W_0 = \text{initial spatial maps}
$$

$$
H_0 = \text{initial component spectra}
$$

Then the solver starts from:

$$
W \leftarrow W_0
$$

$$
H \leftarrow H_0
$$

and iteratively updates both `W` and `H` to reduce the reconstruction error.

Implementation-shaped view:

```text
seed_W = W0
seed_H = H0

W, H = fit_nmf(
    X,
    n_components=k,
    init="custom",
    W=seed_W,
    H=seed_H,
    update_w=True,
    update_h=True,
)
```

This means seeded NNMF is not the same as fixing the seeds. The seeds guide the solution, but the final spectra and maps are still allowed to change:

$$
\text{initial:}\quad X \approx W_0 H_0
$$

$$
\text{final:}\quad X \approx W^* H^*
$$

where `W*` and `H*` are the fitted result after NNMF iterations.

## How H seeds are built

`H0` contains one seed spectrum per component. These spectra can come from:

- ROI average spectra.
- Loaded CSV/TXT/ASC spectra.
- Gaussian resonance models.
- Previous result spectra imported back into the ROI manager.
- Spectral information entered in the GUI.

If several spectral seeds are assigned to the same component, they are combined before analysis so that the component has one initial spectrum.

Conceptually:

$$
H_0[i, :] =
\text{seed spectrum for component } i
$$

Implementation-shaped view:

```text
for component i:
    H0[i, :] = spectrum_from_roi_or_file_or_gaussian(i)
```

## How W seeds are built

`W0` contains one spatial map per component:

$$
W_0[:, i] =
\text{seed abundance map for component } i
$$

Implementation-shaped view:

```text
for component i:
    if fixed_W_seed_exists(i):
        W0[:, i] = fixed_W_seed[i]
    else:
        W0[:, i] = estimate_W_from_H(X, H0, component=i)
```

If a fixed W seed exists, for example from an imported result or a background map, that W map is used as spatial prior for the component.

If only an H seed is available, the GUI estimates a W seed from the data and the seeded spectrum. The selected W-seed mode controls this estimate:

- NNLS abundance map: fit all available H seeds to each pixel and use the fitted coefficient.
- Selective score map: project the pixel spectrum onto the target H seed and down-weight pixels that also match competing H seeds.
- H-weighted average: emphasize image channels where the H seed is strong.
- Average image: use a broad intensity-based spatial guess.
- Homogeneous: use an almost neutral spatial guess.

For these seeded modes, the component spectra in `H0` keep their physical amplitude scale. The GUI does not normalize each seed spectrum independently before constructing NNLS-based W seeds. This keeps the seeded model closer to the same `X \approx WH` convention used by NNMF and fixed-H NNLS.

The **Selective score map** can produce a seed map with an arbitrary overall magnitude because it is a heuristic projection-and-competition score rather than a strict abundance solve. For that mode, the GUI rescales the resulting W seed map afterward to unit maximum. The other seed modes keep their natural numeric scale.

### NNLS abundance map as W seed

The NNLS abundance map is the most constrained W-seed mode. It asks a direct question for every pixel:

> If the current seeded spectra `H0` were already correct, how much of each seeded component would be needed to reconstruct this pixel spectrum?

Mathematically, this is the same non-negative least-squares subproblem used in [Fixed-H NNLS](#fixed-h-nnls), but here it is used only to create the initial spatial seed `W0` for seeded NNMF.

For each pixel spectrum \(x_p\), the GUI solves:

$$
w_p =
\arg\min_{w_p \ge 0}
\left\| x_p - w_p H_0 \right\|_2^2
$$

where:

- \(x_p\) is the measured spectrum of pixel `p`.
- \(H_0\) is the matrix of seeded component spectra on their original cleaned amplitude scale.
- \(w_p\) is the non-negative abundance vector for pixel `p`.

The entries of \(w_p\) become one row of the W seed matrix:

$$
W_0[p, :] = w_p
$$

Implementation-shaped view:

```text
for pixel p:
    w_p = nnls(H0.T, x_p)
    W0[p, :] = w_p
```

This produces one abundance image per component. A pixel receives a high value for component `i` only if the seeded spectrum of component `i` helps reconstruct the pixel spectrum under the non-negativity constraint.

The important distinction is:

- In **seeded NNMF**, the NNLS abundance map is only the starting `W0`. Afterwards, NNMF can still update both `W` and `H`.
- In **fixed-H NNLS**, the same type of NNLS solve is the final analysis result, because `H` stays fixed and only `W` is solved.

This gives a physically stricter initial W map than a simple average image because it uses the full seeded spectral model instead of only image brightness.

## Interpreting seeded NNMF

Seeded NNMF is useful when the seeds are plausible but not perfect. It lets the data refine the component spectra and maps.

Use seeded NNMF when:

- ROI spectra are available.
- Spectral peaks or external spectra are known approximately.
- You want component labels and colors to follow the ROI manager.
- You want a physically guided result, but still allow spectral adaptation.

Be careful when:

- Seed ROIs contain mixtures.
- Two components have very similar spectra.
- One component is much brighter than the others.
- Background or illumination variation is not modeled.
- The number of components is too small.

In these cases, NNMF can still move spectral intensity between components to reduce the reconstruction error.

## Fixed-H NNLS

Fixed-H NNLS keeps the component spectra fixed and solves only the non-negative abundance maps:

$$
W =
\arg\min_{W \ge 0}
\left\| X - W H_{\mathrm{seed}} \right\|_F^2
$$

For each pixel spectrum `x_p`, this becomes:

$$
w_p =
\arg\min_{w_p \ge 0}
\left\| x_p - w_p H_{\mathrm{seed}} \right\|_2^2
$$

Implementation-shaped view:

```text
H = H_seed

for pixel p:
    W[p, :] = nnls(H.T, X[p, :])

X_reconstructed = W @ H
```

This is the strictest seeded mode. The spectra do not adapt to the data. Only the W maps are estimated.

Use fixed-H NNLS when:

- All component spectra are known or intentionally fixed.
- Spectral interpretability is more important than adapting H.
- The same spectra should be compared across fields of view, z slices, or time points.
- 4D data should be analyzed efficiently with stable spectra.

In 3D data, fixed-H NNLS directly uses the NNLS seed result as the output. In 4D data, the same H basis can be reused while W maps are recomputed for each z/time slice.

> GIF placeholder: switching between PCA, seeded NNMF, and fixed-H NNLS mode.

## Choosing a mode

Typical choices:

- First inspection of unknown data: PCA.
- Non-negative exploratory decomposition without prior knowledge: random NNMF.
- CARS/SRS with useful ROIs: seeded NNMF.
- Known spectra, dye channels, or reference spectra: fixed-H NNLS.
- 4D fluorescence with stable spectra: fixed-H NNLS across z/time.

The key question is whether the spectra should be discovered, guided, or fixed.
