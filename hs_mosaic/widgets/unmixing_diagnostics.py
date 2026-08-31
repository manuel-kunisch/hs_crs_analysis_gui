"""Diagnostics for spectral separability and unmixing quality.

Answers two practical questions that come up before and after a multivariate
analysis:

1. *How many components can this dataset support at all?*
   The data matrix ``X`` (pixels x channels) has at most ``C`` linearly
   independent directions, and noise erodes that further. Counting the
   singular values that rise above the noise floor gives an effective rank
   ``K_eff``, an upper bound for the number of components that carry real
   signal rather than fitted noise.

2. *Given a set of component spectra, can they actually be told apart?*
   For component ``k`` the decisive quantity is how much of its spectral
   fingerprint no combination of the other components can imitate:

       eta_k = sin( angle( s_k, span{s_j, j != k} ) )

   ``eta`` lies in ``[0, 1]``: 1 means orthogonal to everything else, 0 means
   the spectrum is a linear combination of the others and is not separable at
   all. Noise (and any error in the spectra themselves) is amplified by
   ``1 / eta`` when solving for abundances, so

       SNR_effective = eta * SNR_raw

   is the number that decides whether a component is recoverable in practice.
   A component needs roughly ``eta * SNR >~ 10`` for ~10 % abundance accuracy.

Both are pure NumPy and independent of the GUI, so they can be reused from
scripts.

Notes
-----
The counting rules (``K <= C`` for arbitrary mixtures, ``s <= floor(C/2)`` for
sparse pixels when ``K > C``) only decide whether a unique solution *exists*.
Whether it is *usable* is decided by ``eta``.

References
----------
J. Immerkaer, "Fast Noise Variance Estimation," Computer Vision and Image
Understanding, 64(2), 300-302, 1996. DOI: 10.1006/cviu.1996.0060.

V. A. Marchenko and L. A. Pastur, "Distribution of eigenvalues for some sets
of random matrices," Mat. Sb., 72(114):4, 507-536, 1967.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

_EPS = 1e-12

# ``eta`` at or above this is comfortable to unmix.
ETA_GOOD = 0.30
# ``eta`` below this is effectively not separable at realistic SNR.
ETA_CRITICAL = 0.10

# Relative abundance accuracy the ``required_snr`` default aims for.
DEFAULT_TARGET_PRECISION = 0.10

# Below this many pixels a ROI-based noise estimate is statistically shaky
# (relative error of a standard deviation is roughly ``1 / sqrt(2 N)``).
MIN_NOISE_PIXELS = 200


# ---------------------------------------------------------------------------
# Noise estimation
# ---------------------------------------------------------------------------

def _immerkaer_sigma(frame: np.ndarray) -> float:
    """Noise sigma of a single 2D frame via the Immerkaer Laplacian estimator.

    The 3x3 kernel ``[[1,-2,1],[-2,4,-2],[1,-2,1]]`` annihilates locally linear
    image content, so what survives is dominated by noise. Returns ``nan`` for
    frames too small to evaluate.
    """
    if frame.ndim != 2 or frame.shape[0] < 3 or frame.shape[1] < 3:
        return float("nan")
    f = np.asarray(frame, dtype=np.float64)
    conv = (
        f[:-2, :-2] - 2.0 * f[:-2, 1:-1] + f[:-2, 2:]
        - 2.0 * f[1:-1, :-2] + 4.0 * f[1:-1, 1:-1] - 2.0 * f[1:-1, 2:]
        + f[2:, :-2] - 2.0 * f[2:, 1:-1] + f[2:, 2:]
    )
    finite = np.isfinite(conv)
    if not finite.any():
        return float("nan")
    # sqrt(pi/2) corrects the mean absolute deviation to a standard deviation;
    # 6 is the kernel norm.
    return float(np.sqrt(np.pi / 2.0) * np.abs(conv[finite]).sum() / (6.0 * finite.sum()))


def estimate_noise_sigma(cube: np.ndarray) -> float:
    """Estimate the per-channel noise standard deviation of a spectral cube.

    Parameters
    ----------
    cube
        Array shaped ``(channels, height, width)``. A single 2D frame is also
        accepted.

    Returns
    -------
    float
        Median of the per-channel Immerkaer estimates, or ``nan`` if it cannot
        be evaluated (e.g. frames smaller than 3x3).

    Notes
    -----
    The estimator assumes the *signal* is locally smooth, so that the Laplacian
    kernel leaves only noise. Fine spatial texture leaks into the estimate and
    inflates it; on a synthetic cube with structured abundances it came out
    ~3x high. The bias is one-sided: an over-estimated sigma raises the noise
    threshold and therefore *under*-estimates the effective rank, which is the
    safe direction for a "how many components can I trust" number. Data that is
    heavily binned or dominated by shot noise at the pixel level will be
    estimated conservatively.
    """
    arr = np.asarray(cube)
    if arr.ndim == 2:
        return _immerkaer_sigma(arr)
    if arr.ndim != 3:
        raise ValueError(f"expected a 2D frame or a 3D (C, H, W) cube, got shape {arr.shape}")
    per_channel = np.array([_immerkaer_sigma(arr[i]) for i in range(arr.shape[0])])
    finite = per_channel[np.isfinite(per_channel)]
    if finite.size == 0:
        return float("nan")
    return float(np.median(finite))


def noise_sigma_from_pixels(pixels: np.ndarray) -> np.ndarray:
    """Per-channel noise sigma from pixels known to be signal-free.

    This is the estimator for a user-selected background/noise region: no
    smoothness assumption at all, just the standard deviation of what should
    be pure noise. Unlike the Immerkaer estimate it yields a *vector*, one
    sigma per channel, which allows whitening the data before the rank test.

    Parameters
    ----------
    pixels
        Array shaped ``(n_pixels, n_channels)`` of raw values from the
        signal-free region.

    Returns
    -------
    np.ndarray
        Per-channel sigma (``ddof=1``), ``nan`` where fewer than two finite
        values are available.

    Notes
    -----
    The estimate assumes the region really is empty. Structure in the region
    (autofluorescence, gradients) inflates it; conversely, for shot-noise
    limited data a dark region underestimates the noise present in bright
    areas. The Immerkaer estimate fails in the opposite direction, so showing
    both is itself a diagnostic.
    """
    arr = np.asarray(pixels, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError(f"expected (n_pixels, n_channels), got shape {arr.shape}")
    sigma = np.full(arr.shape[1], np.nan)
    for c in range(arr.shape[1]):
        col = arr[:, c]
        col = col[np.isfinite(col)]
        if col.size >= 2:
            sigma[c] = float(np.std(col, ddof=1))
    return sigma


def estimate_snr(cube: np.ndarray, noise_sigma: float | None = None) -> float:
    """Rough global SNR of a cube: median signal over noise sigma.

    Uses the median of the positive data as the signal level, which is far more
    robust for sparse fluorescence images than the mean or the maximum.
    """
    arr = np.asarray(cube, dtype=np.float64)
    if noise_sigma is None:
        noise_sigma = estimate_noise_sigma(arr)
    if not np.isfinite(noise_sigma) or noise_sigma <= _EPS:
        return float("nan")
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return float("nan")
    positive = finite[finite > 0]
    signal = float(np.median(positive)) if positive.size else float(np.median(finite))
    return signal / noise_sigma


# ---------------------------------------------------------------------------
# Effective rank
# ---------------------------------------------------------------------------

@dataclass
class RankEstimate:
    """Result of ``effective_rank``."""

    singular_values: np.ndarray
    explained_variance_ratio: np.ndarray
    cumulative_variance: np.ndarray
    n_pixels: int
    n_channels: int
    noise_sigma: float
    noise_threshold: float
    # Components whose singular value exceeds the random-matrix noise floor.
    k_noise: int
    # Components needed to reach each level in ``variance_levels``.
    k_variance: dict[float, int] = field(default_factory=dict)
    # Per-channel sigma when the estimate came from a noise region.
    noise_sigma_per_channel: np.ndarray | None = None
    # True when the singular values were computed on whitened data
    # (each channel divided by its own sigma; the threshold then uses sigma=1).
    whitened: bool = False

    @property
    def k_eff(self) -> int:
        """Best available estimate of the usable component count."""
        if self.k_noise > 0:
            return self.k_noise
        # Without a noise estimate fall back to the strictest variance level.
        if self.k_variance:
            return max(self.k_variance.values())
        return int(min(self.n_pixels, self.n_channels))

    @property
    def has_noise_estimate(self) -> bool:
        return bool(np.isfinite(self.noise_sigma) and self.noise_sigma > _EPS)


def effective_rank(
    data_2d: np.ndarray,
    noise_sigma: float | np.ndarray | None = None,
    variance_levels: tuple[float, ...] = (0.99, 0.999),
    noise_sigma_samples: int | None = None,
) -> RankEstimate:
    """Estimate how many components a dataset can support.

    Parameters
    ----------
    data_2d
        Data matrix shaped ``(n_pixels, n_channels)``. Not mean-centred: for a
        non-negative model the mean direction is itself a real component.
    noise_sigma
        Noise standard deviation. A scalar applies one level to all channels.
        A vector of length ``n_channels`` (e.g. from
        ``noise_sigma_from_pixels``) whitens the data first: each channel
        is divided by its own sigma, the noise becomes isotropic as the
        Marchenko-Pastur edge assumes, and the threshold is evaluated at
        ``sigma = 1``. This is the statistically correct variant when channels
        have different gains or exposure times. ``None`` skips the noise
        threshold and reports only the variance criteria.
    variance_levels
        Cumulative explained-variance fractions to report component counts for.
    noise_sigma_samples
        Number of pixels the sigma estimate is based on, when it came from a
        finite noise region. The standard error of a standard deviation is
        roughly ``sigma / sqrt(2 N)``, and the Marchenko-Pastur edge is sharp,
        so even a slightly underestimated sigma lets borderline noise singular
        values through. When given, the threshold is inflated by the two-sigma
        confidence factor ``1 + sqrt(2 / N)``.

    Returns
    -------
    RankEstimate

    Notes
    -----
    The noise threshold uses the Marchenko-Pastur edge for a ``P x C`` matrix of
    i.i.d. noise, whose largest singular value concentrates near
    ``sigma * (sqrt(P) + sqrt(C))``. Singular values above that edge cannot be
    explained by noise alone.
    """
    X = np.asarray(data_2d, dtype=np.float64)
    if X.ndim != 2:
        raise ValueError(f"expected a 2D (pixels, channels) matrix, got shape {X.shape}")
    if not np.isfinite(X).all():
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    n_pixels, n_channels = X.shape

    sigma_vector: np.ndarray | None = None
    whitened = False
    if noise_sigma is not None and np.ndim(noise_sigma) == 1:
        sigma_vector = np.asarray(noise_sigma, dtype=np.float64).copy()
        if sigma_vector.size != n_channels:
            raise ValueError(
                f"noise_sigma vector has {sigma_vector.size} entries for {n_channels} channels"
            )
        # Channels without a usable sigma get the median of the others, so one
        # degenerate channel cannot blow up the whitening.
        valid = np.isfinite(sigma_vector) & (sigma_vector > _EPS)
        if valid.any():
            sigma_vector[~valid] = float(np.median(sigma_vector[valid]))
            X = X / sigma_vector[None, :]
            whitened = True
            noise_sigma = 1.0
        else:
            sigma_vector = None
            noise_sigma = None

    sv = np.linalg.svd(X, compute_uv=False)

    total = float(np.sum(sv ** 2))
    if total > _EPS:
        ratio = (sv ** 2) / total
    else:
        ratio = np.zeros_like(sv)
    cumulative = np.cumsum(ratio)

    k_variance: dict[float, int] = {}
    for level in variance_levels:
        idx = int(np.searchsorted(cumulative, level) + 1)
        k_variance[float(level)] = int(min(idx, sv.size))

    if noise_sigma is not None and np.isfinite(noise_sigma) and noise_sigma > _EPS:
        threshold = float(noise_sigma) * (np.sqrt(n_pixels) + np.sqrt(n_channels))
        if noise_sigma_samples is not None and noise_sigma_samples > 1:
            threshold *= 1.0 + np.sqrt(2.0 / float(noise_sigma_samples))
        k_noise = int(np.count_nonzero(sv > threshold))
    else:
        noise_sigma = float("nan")
        threshold = float("nan")
        k_noise = 0

    # For display report the physical noise level, not the whitened 1.0.
    display_sigma = float(np.median(sigma_vector)) if whitened else float(noise_sigma)

    return RankEstimate(
        singular_values=sv,
        explained_variance_ratio=ratio,
        cumulative_variance=cumulative,
        n_pixels=int(n_pixels),
        n_channels=int(n_channels),
        noise_sigma=display_sigma,
        noise_threshold=threshold,
        k_noise=k_noise,
        k_variance=k_variance,
        noise_sigma_per_channel=sigma_vector,
        whitened=whitened,
    )


def effective_rank_from_cube(
    cube: np.ndarray,
    variance_levels: tuple[float, ...] = (0.99, 0.999),
) -> RankEstimate:
    """``effective_rank`` for a ``(channels, height, width)`` cube.

    Estimates the noise level from the spatial structure of the cube, so the
    noise threshold is available without the caller supplying a sigma.
    """
    arr = np.asarray(cube)
    if arr.ndim != 3:
        raise ValueError(f"expected a 3D (C, H, W) cube, got shape {arr.shape}")
    sigma = estimate_noise_sigma(arr)
    data_2d = np.moveaxis(arr, 0, -1).reshape(-1, arr.shape[0])
    return effective_rank(data_2d, noise_sigma=sigma, variance_levels=variance_levels)


# ---------------------------------------------------------------------------
# Separability of a set of spectra
# ---------------------------------------------------------------------------

@dataclass
class Separability:
    """Result of ``separability``."""

    # ``eta`` per component, in ``[0, 1]``.
    eta: np.ndarray
    # Noise/error amplification ``1 / eta`` per component.
    amplification: np.ndarray
    # Pairwise cosine similarity of the normalised spectra.
    cosine_matrix: np.ndarray
    # Largest off-diagonal cosine per component.
    max_cosine: np.ndarray
    # Index of the component responsible for ``max_cosine``.
    worst_partner: np.ndarray
    # Condition number of the spectral matrix.
    condition_number: float
    n_components: int
    n_channels: int
    labels: list[str]
    # Components whose spectrum is (numerically) all zero.
    empty: np.ndarray

    @property
    def eta_min(self) -> float:
        """Worst component, the one that limits the whole panel."""
        valid = self.eta[~self.empty]
        return float(np.min(valid)) if valid.size else float("nan")

    @property
    def overdetermined(self) -> bool:
        """True when there are more components than channels."""
        return self.n_components > self.n_channels

    def verdict(self, index: int) -> str:
        """Coarse grade for one component: ``good`` / ``marginal`` / ``critical``."""
        if self.empty[index]:
            return "empty"
        value = float(self.eta[index])
        if value >= ETA_GOOD:
            return "good"
        if value >= ETA_CRITICAL:
            return "marginal"
        return "critical"

    def summary_rows(self, snr: float | None = None) -> list[dict]:
        """Per-component rows ready for a table widget."""
        rows = []
        for i in range(self.n_components):
            row = {
                "index": i,
                "label": self.labels[i],
                "eta": float(self.eta[i]),
                "amplification": float(self.amplification[i]),
                "max_cosine": float(self.max_cosine[i]),
                "worst_partner": int(self.worst_partner[i]),
                "worst_partner_label": (
                    self.labels[int(self.worst_partner[i])]
                    if self.worst_partner[i] >= 0 else ""
                ),
                "required_snr": float(required_snr(self.eta[i])),
                "verdict": self.verdict(i),
            }
            if snr is not None and np.isfinite(snr):
                row["effective_snr"] = float(self.eta[i] * snr)
                row["predicted_precision"] = float(predicted_precision(self.eta[i], snr))
            rows.append(row)
        return rows


def separability(
    H: np.ndarray,
    labels: list[str] | None = None,
    rcond: float = 1e-10,
) -> Separability:
    """Measure how distinguishable a set of component spectra is.

    Parameters
    ----------
    H
        Spectral matrix shaped ``(n_components, n_channels)``, rows are
        spectra, matching the ``H`` convention of the NNMF code.
    labels
        Optional display names, defaults to ``Component 1 ...``.
    rcond
        Relative cutoff for treating a singular value of the "other" spectra as
        zero when building the projector.

    Returns
    -------
    Separability

    Notes
    -----
    ``eta_k`` is computed by projecting the normalized spectrum ``k`` onto the
    row space of all other normalized spectra and taking the length of the
    residual. This is done via an SVD of the remaining rows rather than a Gram
    inverse, so it stays well defined when the spectra are linearly dependent
    (``K > C``), where the correct answer is ``eta = 0``.
    """
    Hm = np.asarray(H, dtype=np.float64)
    if Hm.ndim != 2:
        raise ValueError(f"expected a 2D (components, channels) matrix, got shape {Hm.shape}")
    if not np.isfinite(Hm).all():
        Hm = np.nan_to_num(Hm, nan=0.0, posinf=0.0, neginf=0.0)

    n_components, n_channels = Hm.shape
    if labels is None:
        labels = [f"Component {i + 1}" for i in range(n_components)]
    elif len(labels) != n_components:
        raise ValueError(f"got {len(labels)} labels for {n_components} components")

    norms = np.linalg.norm(Hm, axis=1)
    empty = norms <= _EPS
    unit = np.zeros_like(Hm)
    valid = ~empty
    unit[valid] = Hm[valid] / norms[valid, None]

    # Pairwise cosine similarity of the normalized spectra.
    cosine = unit @ unit.T
    np.clip(cosine, -1.0, 1.0, out=cosine)

    eta = np.zeros(n_components, dtype=np.float64)
    max_cosine = np.zeros(n_components, dtype=np.float64)
    worst_partner = np.full(n_components, -1, dtype=int)

    for k in range(n_components):
        if empty[k]:
            continue
        others = unit[[j for j in range(n_components) if j != k and not empty[j]]]
        if others.size == 0:
            eta[k] = 1.0
        else:
            # Row space of the other spectra via SVD; project and keep the residual.
            _, s, Vt = np.linalg.svd(others, full_matrices=False)
            rank = int(np.count_nonzero(s > (s[0] * rcond if s.size else 0.0)))
            if rank == 0:
                eta[k] = 1.0
            else:
                basis = Vt[:rank]
                residual = unit[k] - basis.T @ (basis @ unit[k])
                eta[k] = float(np.clip(np.linalg.norm(residual), 0.0, 1.0))

        off = np.abs(cosine[k]).copy()
        off[k] = -np.inf
        off[empty] = -np.inf
        if np.isfinite(off).any():
            partner = int(np.argmax(off))
            max_cosine[k] = float(off[partner])
            worst_partner[k] = partner

    with np.errstate(divide="ignore"):
        amplification = np.where(eta > _EPS, 1.0 / np.maximum(eta, _EPS), np.inf)

    if valid.any():
        sv = np.linalg.svd(Hm[valid], compute_uv=False)
        if sv.size and sv[-1] > _EPS:
            condition_number = float(sv[0] / sv[-1])
        else:
            condition_number = float("inf")
    else:
        condition_number = float("nan")

    return Separability(
        eta=eta,
        amplification=amplification,
        cosine_matrix=cosine,
        max_cosine=max_cosine,
        worst_partner=worst_partner,
        condition_number=condition_number,
        n_components=int(n_components),
        n_channels=int(n_channels),
        labels=list(labels),
        empty=empty,
    )


# ---------------------------------------------------------------------------
# Seed purification
# ---------------------------------------------------------------------------

@dataclass
class PurificationResult:
    """Result of ``purify_spectrum``."""

    # The purified spectrum, clipped at zero. Never contains negatives, so it
    # is safe for the seed pipeline (negative seeds would be baseline-shifted
    # downstream, which distorts the spectral shape).
    spectrum: np.ndarray
    # Full extrapolation coefficient: the largest multiple of the reference
    # that can be subtracted before some channel goes negative.
    b_star: float
    # The multiple actually removed (``fraction * b_star``).
    subtracted: float
    # Channel index that pinned ``b_star`` (the anchor channel where the
    # target is assumed to vanish).
    anchor_channel: int
    # Number of channels the ratio was evaluated on.
    n_channels_used: int
    # ``||spectrum|| / ||mixed||``; near zero means the two inputs were
    # proportional and nothing remains after subtraction.
    residual_fraction: float


def purify_spectrum(
    mixed: np.ndarray,
    reference: np.ndarray,
    fraction: float = 1.0,
    ratio_quantile: float = 0.05,
    ref_threshold: float = 0.05,
) -> PurificationResult:
    """Remove a reference component from a mixed spectrum by extrapolation.

    In samples without pure pixels every measured seed is a mixture
    ``s_mixed = s_target + b * s_ref``. Since both spectra are non-negative,
    the largest admissible ``b`` is the one at which some channel of the
    difference reaches zero:

        b* = min_c  s_mixed[c] / s_ref[c]     (over channels where s_ref emits)

    Subtracting ``b* * s_ref`` extrapolates the seed to the non-negativity
    boundary: the pure target spectrum, provided the target genuinely has a
    (near-)zero channel where the reference emits (e.g. the CH2 2850 band for
    lipid against protein/DNA). Without such a channel the true answer lies
    between the mixed spectrum and this boundary; ``fraction`` walks that
    interval.

    Parameters
    ----------
    mixed
        The contaminated seed spectrum, shape ``(n_channels,)``.
    reference
        The spectrum of the component to remove, same shape.
    fraction
        How far along the extrapolation to go: the returned spectrum is
        ``mixed - fraction * b_star * reference`` (clipped at zero).
        1.0 goes to the boundary; smaller values are conservative.
    ratio_quantile
        Quantile of the channel ratios used as ``b_star``. The minimum is
        exact for noise-free data but a single noisy low channel caps the
        subtraction too early; the 5th percentile is nearly the minimum yet
        robust on many-channel data, and degrades to the minimum when only a
        few channels qualify.
    ref_threshold
        Channels where ``reference < ref_threshold * max(reference)`` are
        excluded from the ratio; there the ratio is dominated by noise.

    Raises
    ------
    ValueError
        If the shapes differ or the reference carries no signal.
    """
    m = np.nan_to_num(np.asarray(mixed, dtype=np.float64).ravel(), nan=0.0, posinf=0.0, neginf=0.0)
    r = np.nan_to_num(np.asarray(reference, dtype=np.float64).ravel(), nan=0.0, posinf=0.0, neginf=0.0)
    if m.shape != r.shape:
        raise ValueError(f"shape mismatch: mixed {m.shape} vs reference {r.shape}")
    m = np.maximum(m, 0.0)
    r = np.maximum(r, 0.0)

    r_max = float(np.max(r)) if r.size else 0.0
    if r_max <= _EPS:
        raise ValueError("reference spectrum carries no signal")

    usable = r > ref_threshold * r_max
    ratios = m[usable] / r[usable]
    n_used = int(np.count_nonzero(usable))
    # method="lower" returns an actually observed ratio: on few channels the
    # quantile degrades to the exact minimum instead of interpolating above it,
    # which would overshoot the non-negativity boundary.
    b_star = float(max(np.quantile(ratios, ratio_quantile, method="lower"), 0.0))

    # The witness channel: the usable channel whose ratio is closest to b_star
    # from above: the channel where the target is assumed to vanish.
    usable_idx = np.flatnonzero(usable)
    anchor_channel = int(usable_idx[np.argmin(np.abs(ratios - b_star))])

    subtracted = float(fraction) * b_star
    purified = np.maximum(m - subtracted * r, 0.0)

    mixed_norm = float(np.linalg.norm(m))
    residual_fraction = float(np.linalg.norm(purified) / mixed_norm) if mixed_norm > _EPS else 0.0

    return PurificationResult(
        spectrum=purified,
        b_star=b_star,
        subtracted=subtracted,
        anchor_channel=anchor_channel,
        n_channels_used=n_used,
        residual_fraction=residual_fraction,
    )


# ---------------------------------------------------------------------------
# SNR relations
# ---------------------------------------------------------------------------

def required_snr(eta, target_precision: float = DEFAULT_TARGET_PRECISION):
    """Raw SNR needed to reach ``target_precision`` relative abundance accuracy.

    From ``SNR_effective = eta * SNR_raw`` and ``precision ~ 1 / SNR_effective``.
    """
    eta_arr = np.asarray(eta, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(eta_arr > _EPS, 1.0 / (np.maximum(eta_arr, _EPS) * target_precision), np.inf)
    return out if out.ndim else float(out)


def predicted_precision(eta, snr):
    """Expected relative abundance error at a given raw SNR.

    Returns ``inf`` where the component is not separable at all.
    """
    eta_arr = np.asarray(eta, dtype=np.float64)
    snr_val = np.asarray(snr, dtype=np.float64)
    denom = eta_arr * snr_val
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(denom > _EPS, 1.0 / np.maximum(denom, _EPS), np.inf)
    return out if out.ndim else float(out)


def calibration_error_amplification(eta, relative_h_error: float):
    """Abundance error caused by an error in the spectra themselves.

    ``H`` is never known exactly (it is measured or estimated), and that
    error is amplified by the same ``1 / eta``::

        delta_a / a  ~  (1 / eta) * (delta_H / H)

    So a 2 % error on a component with ``eta = 0.05`` already means a ~40 %
    abundance error, independent of how good the SNR is.
    """
    eta_arr = np.asarray(eta, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(
            eta_arr > _EPS,
            float(relative_h_error) / np.maximum(eta_arr, _EPS),
            np.inf,
        )
    return out if out.ndim else float(out)


def max_sparse_components(n_channels: int, known_support: bool = False) -> int:
    """Largest number of components per pixel that stays uniquely unmixable.

    Only relevant when the panel is over-complete (``K > C``). With ``K <= C``
    and full column rank every pixel is uniquely solvable regardless of how
    many components overlap in it.

    ``known_support`` reflects whether it is known *which* components are
    present in the pixel (e.g. from the staining protocol). Not knowing costs a
    factor of two, because the difference of two ``s``-sparse solutions is
    ``2s``-sparse and must be excluded from the null space.
    """
    c = int(n_channels)
    return c if known_support else c // 2
