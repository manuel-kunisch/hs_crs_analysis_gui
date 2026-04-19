# 02 Analysis Modes

This page summarizes the analysis modes and the basic mathematical idea behind them.

## The Unmixing Model

The GUI treats a spectral image stack as a data matrix:

```text
X = pixels x channels
```

The goal is to describe the data as:

```text
X ~= W H
```

where:

- `H` contains the spectral signatures of the components;
- `W` contains the spatial maps or abundances of those components.

The result viewer shows `W` as component images and `H` as component spectra.

## PCA

PCA is available as an exploratory mode. It decomposes the data into orthogonal components, but these components are not constrained to be non-negative.

Use PCA when:

- you want to inspect dominant variance patterns,
- you want a quick diagnostic,
- you do not yet know how many components are useful.

PCA is not usually the final mode for physically interpretable non-negative component maps.

## Random NNMF

Random NNMF estimates both `W` and `H` without user-defined seed spectra.

Use this when:

- no reliable prior spectra are available,
- you want a fast exploratory decomposition,
- you want to compare seeded and unseeded results.

Because the initialization is not constrained by user knowledge, component order and interpretation may change between datasets.

## Seeded NNMF

Seeded NNMF uses user-provided spectral and/or spatial information to initialize the decomposition.

Seeded NNMF still updates both:

```text
W and H
```

during the fit.

Use this when:

- ROI spectra are available,
- spectral peaks or external spectra are known,
- the decomposition should be guided but still allowed to adapt to the data.

## Fixed-H NNLS

Fixed-H NNLS keeps the component spectra fixed and solves only the non-negative abundance maps.

The optimization problem is:

```text
W = argmin_{W >= 0} ||X - W H||_F^2
```

Use this when:

- all component spectra are known or intentionally fixed,
- spectral interpretability is more important than adapting H,
- comparing the same spectra across fields of view, z slices, or time points.

In 3D data, fixed-H NNLS directly uses the NNLS seed result as the output. In 4D data, the same H basis can be reused while W maps are recomputed for each z/time slice.

> GIF placeholder: switching between NNMF and fixed-H NNLS mode.

## Choosing A Mode

Typical choices:

- CARS/SRS with useful ROIs: seeded NNMF.
- Known spectra or dye channels: fixed-H NNLS.
- First inspection of unknown data: PCA or random NNMF.
- 4D fluorescence with stable spectra: fixed-H NNLS across z/time.

The best mode depends on whether the spectra are expected to change during the analysis.
