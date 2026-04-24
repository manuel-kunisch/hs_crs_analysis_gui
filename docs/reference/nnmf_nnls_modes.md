# NNMF and NNLS modes

This reference summarizes the multivariate modes used by the GUI. For the guided tutorial, see [02 Analysis modes](../tutorials/02_analysis_modes.md).

## Data layout

The image stack is reshaped into:

$$
X \in \mathbb{R}_{\ge 0}^{n_\mathrm{pixels} \times n_\mathrm{channels}}
$$

Each row is one pixel spectrum. Each column is one spectral channel.

## PCA

PCA is run on channel-standardized data:

$$
Z_{p,j} =
\frac{X_{p,j} - \mu_j}{\sigma_j}
$$

It then estimates scores and loadings:

$$
Z \approx T P
$$

PCA is deterministic for a given dataset and preprocessing, apart from sign ambiguity. It is useful for variance inspection but not constrained to non-negative or chemically pure components.

## Random NNMF

Random NNMF estimates non-negative maps and spectra:

$$
W, H =
\arg\min_{W \ge 0,\; H \ge 0}
\left\| X - W H \right\|_F^2
$$

The result is initialized without user-provided spectra or maps.

## Seeded NNMF

Seeded NNMF solves the same objective, but starts from user-guided initial matrices:

$$
W \leftarrow W_0,\qquad H \leftarrow H_0
$$

The seeds are initialization, not hard constraints. During NNMF, both matrices can change:

$$
X \approx W_0 H_0
\quad \longrightarrow \quad
X \approx W^* H^*
$$

Sources for `H0` include ROI spectra, loaded spectra, Gaussian resonances, and imported result spectra.

Sources for `W0` include NNLS abundance maps, selective score maps, H-weighted maps, average images, homogeneous maps, imported result maps, and fixed W/background seeds.

The seeded spectra are kept on their physical amplitude scale. The GUI does not renormalize each component spectrum independently before seeded NNMF or NNLS abundance seeding. The selective-score W seed may still be rescaled afterward to unit maximum so that heuristic map remains numerically well behaved without changing `H`.

## Fixed-H NNLS

Fixed-H NNLS keeps the spectra fixed and solves only the abundance maps:

$$
W =
\arg\min_{W \ge 0}
\left\| X - W H_{\mathrm{seed}} \right\|_F^2
$$

For each pixel:

$$
w_p =
\arg\min_{w_p \ge 0}
\left\| x_p - w_p H_{\mathrm{seed}} \right\|_2^2
$$

This is the strictest seeded mode because `H` is not updated.

## Solver paths

Available paths depend on the selected mode and installed packages:

- PCA uses the scikit-learn PCA path.
- NNMF can use scikit-learn coordinate descent or multiplicative updates.
- NNMF multiplicative updates can use the optional PyTorch backend.
- Fixed-H NNLS can use SciPy or the optional PyTorch CUDA NNLS backend.

If an optional GPU path is unavailable, the GUI falls back to the CPU path where possible.

## Practical choice

Use PCA for diagnostics, random NNMF for unguided non-negative exploration, seeded NNMF for physically guided fitting with adaptable spectra, and fixed-H NNLS when all spectra should remain fixed.
