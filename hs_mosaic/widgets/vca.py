"""Vertex Component Analysis (VCA) for unsupervised endmember (spectral seed)
extraction based on orthogonal directions in data sets.

The algorithm is a step-wise implementation adapted from the initial paper
of J. M. P. Nascimento and J. M. B. Dias.

VCA is a geometric endmember-extraction method for the linear mixing model:
under that model every pixel spectrum is a non-negative combination of a few
"pure" component spectra (endmembers), so all pixels lie inside a simplex whose
vertices are the endmembers. VCA finds those vertices by repeatedly projecting
the data onto a direction orthogonal to the endmembers found so far and taking
the most extreme pixel as the next endmember.

It is unsupervised (only the number of endmembers ``p`` (in NNMF sense components)
is required) and fast (the cost is dominated by an ``L x L`` SVD, where ``L`` is
the number of spectral channels, not the number of pixels). Its main assumption is
the *pure-pixel* assumption: at least one near-pure pixel exists per endmember.
When that does not hold (heavily mixed pixels), VCA still returns the
most extreme pixels, but they may be less pure.

Reference
---------
J. M. P. Nascimento and J. M. B. Dias, "Vertex Component Analysis: A Fast
Algorithm to Unmix Hyperspectral Data," IEEE Transactions on Geoscience and
Remote Sensing, 43(4), 898-910, 2005. DOI: 10.1109/TGRS.2005.844293.
"""

from __future__ import annotations

import numpy as np

_EPS = 1e-12


def _estimate_snr(Y: np.ndarray, y_mean: np.ndarray, x: np.ndarray) -> float:
    """Estimate the signal-to-noise ratio (dB) used to choose the projection."""
    L, N = Y.shape
    p, _ = x.shape

    p_y = np.sum(Y ** 2) / N
    p_x = np.sum(x ** 2) / N + float(y_mean.T @ y_mean)
    denom = p_y - p_x
    if abs(denom) < _EPS:
        return 0.0
    return 10.0 * np.log10((p_x - p / L * p_y) / denom)


def vca(
    Y: np.ndarray,
    p: int,
    snr_input: float | None = None,
    seed: int | None = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Run Vertex Component Analysis.

    Parameters
    ----------
    Y : np.ndarray
        Data matrix of shape ``(L, N)`` -- ``L`` spectral channels (bands) in
        rows, ``N`` pixels in columns. Each column is one pixel spectrum.
    p : int
        Number of endmembers to extract.
    snr_input : float or None
        If given, the SNR (in dB) to use; otherwise it is estimated from the data.
    seed : int or None
        Seed for the random projection, for reproducible results. ``None`` uses
        fresh randomness.

    Returns
    -------
    endmembers : np.ndarray
        ``(L, p)`` endmember spectra in the original band space (columns are
        endmembers). May contain small negative values; clip to >= 0 before
        using as non-negative seeds.
    indices : np.ndarray
        ``(p,)`` indices of the pixels chosen as endmembers.
    Yp : np.ndarray
        ``(L, N)`` data projected onto the estimated p-dimensional subspace.
    """
    Y = np.asarray(Y, dtype=np.float64)
    if Y.ndim != 2:
        raise ValueError("VCA expects a 2D (bands, pixels) array.")
    L, N = Y.shape
    p = int(p)
    if not (1 <= p <= L):
        raise ValueError(f"Number of endmembers p={p} must satisfy 1 <= p <= bands ({L}).")

    rng = np.random.default_rng(seed)

    # --- choose the projection based on SNR (paper section IV) ---------------
    y_mean = Y.mean(axis=1, keepdims=True)
    Y_o = Y - y_mean                       # mean-centered
    # Subspace from the centered data (L x L SVD is cheap: L = #channels).
    Ud = np.linalg.svd(Y_o @ Y_o.T / N)[0][:, :p]
    x_p = Ud.T @ Y_o

    snr = _estimate_snr(Y, y_mean, x_p) if snr_input is None else float(snr_input)
    snr_threshold = 15.0 + 10.0 * np.log10(p) if p > 0 else 15.0

    if snr < snr_threshold:
        # Low SNR: project onto a (p-1) subspace and append a constant row.
        d = p - 1
        Ud = Ud[:, :d]
        x_p = x_p[:d, :]
        Yp = Ud @ x_p + y_mean             # back to band space
        x = x_p
        c = float(np.max(np.sqrt(np.sum(x ** 2, axis=0))))
        y = np.vstack((x, c * np.ones((1, N))))
    else:
        # High SNR: project onto the p-dimensional subspace of the raw data.
        d = p
        Ud = np.linalg.svd(Y @ Y.T / N)[0][:, :d]
        x_p = Ud.T @ Y
        Yp = Ud @ x_p                      # band space
        u = x_p.mean(axis=1, keepdims=True)
        denom = np.sum(x_p * u, axis=0, keepdims=True)
        denom = np.where(np.abs(denom) < _EPS, _EPS, denom)
        y = x_p / denom

    # --- iterative vertex finding (from line 14 pseudo code) --------------------------
    indices = np.zeros(p, dtype=int)
    A = np.zeros((p, p), dtype=np.float64)
    A[-1, 0] = 1.0
    for i in range(p):
        # Zero-mean Gaussian random vector (paper line 16: w := randn(0, I_p)),
        # giving an isotropic random search direction after the projection below.
        w = rng.standard_normal((p, 1))
        # component of w orthogonal to the span of the chosen vertices
        f = w - A @ (np.linalg.pinv(A) @ w)
        norm = np.linalg.norm(f)
        if norm < _EPS:
            f = w
            norm = np.linalg.norm(f) + _EPS
        f = f / norm
        v = f.T @ y
        idx = int(np.argmax(np.abs(v)))
        indices[i] = idx
        A[:, i] = y[:, idx]

    endmembers = Yp[:, indices]
    return endmembers, indices, Yp


def extract_endmember_spectra(
    stack_bands_yx: np.ndarray,
    n_endmembers: int,
    seed: int | None = 0,
    clip_negative: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Convenience wrapper: run VCA on a ``(bands, Y, X)`` image stack.

    Parameters
    ----------
    stack_bands_yx : np.ndarray
        Hyperspectral stack of shape ``(bands, height, width)``.
    n_endmembers : int
        Number of endmember spectra to extract.
    seed : int or None
        RNG seed for the VCA random projection (reproducibility).
    clip_negative : bool
        Clip the extracted spectra to >= 0 so they are valid non-negative seeds.

    Returns
    -------
    spectra : np.ndarray
        ``(n_endmembers, bands)`` endmember spectra, one per row, aligned to the
        stack's spectral axis. Ready to use as H seeds.
    pixel_indices : np.ndarray
        ``(n_endmembers,)`` flat pixel indices (row-major over Y, X) of the
        chosen endmember pixels.
    """
    stack = np.asarray(stack_bands_yx)
    if stack.ndim != 3:
        raise ValueError("Expected a 3D (bands, height, width) stack.")
    bands, height, width = stack.shape
    Y = stack.reshape(bands, height * width).astype(np.float64)
    Y = np.nan_to_num(Y, nan=0.0, posinf=0.0, neginf=0.0)

    endmembers, indices, _ = vca(Y, n_endmembers, seed=seed)
    spectra = endmembers.T  # (p, bands), same shape as H
    if clip_negative:
        spectra = np.maximum(spectra, 0.0)
    return spectra.astype(np.float32), indices
