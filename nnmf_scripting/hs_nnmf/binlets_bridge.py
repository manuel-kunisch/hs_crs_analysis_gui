"""Optional binlets denoising in front of the NNMF (experimental).

binlets (https://github.com/maurosilber/binlets) bins *adaptively*: neighbouring
pixels are merged only while a statistical test says they are consistent, so
flat regions get large bins while droplets and edges keep full resolution.

Why bin spatially, and why before the unmixing
----------------------------------------------
Binning commutes with the mixing model on either axis -- spatially
``B(W H) = (B W) H`` (H untouched), spectrally ``(W H) P = W (H P)`` (W
untouched) -- so "which axis commutes" does *not* select a domain. What selects
it is where the redundancy is and what you can afford to lose. In CRS images
the structures of interest (lipid droplets) sit at the spatial sampling limit
while the spectrum is only ~2x oversampled relative to its linewidth, so the
spectral axis is better used as *evidence* for the spatial merge decision
(``joint_channels=True``, every decision backed by all channels at once) than
as an axis to average away.

Do the denoising on raw counts, before any nonlinear preprocessing (ratios,
normalization, background division).

Noise model
-----------
binlets uses an *unnormalized* Haar wavelet, so at decomposition ``level`` the
two coefficients handed to the test are **sums of N = 2**level raw pixels**.
For a detector with per-pixel variance ``var = gain * mu + offset``:

    var(x) = gain * x + N * offset          (x is a sum of N pixels)
    var(x - y) = gain * (x + y) + 2 * N * offset

The shot term is level-independent -- that is the elegant property of summing
Haar, and why photon-counting data needs no level correction (``gain=1``,
``offset=0``). A **current-mode PMT** is different: its read/dark/digitisation
floor is a real constant per pixel, so it *accumulates* with the bin size and
must be carried through the levels. Ignoring it makes the test too strict at
high levels (it under-bins, and the denoising quietly stops working).

``gain`` is not the physical PMT gain: it is ``F * g`` in ADU per photoelectron,
with F the excess-noise factor of the dynode chain (~1.2-2). Measure it with
:func:`estimate_noise_model`, never assume it.

Install with ``pip install binlets``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "binlets is not installed in this environment. Install it with "
    "`pip install binlets` (see https://github.com/maurosilber/binlets)."
)

# half-normal: P(|Z| < 0.3186 s) = 0.25  ->  s = p25(|d|) / 0.3186
_P25_TO_SIGMA = 1.0 / 0.3186
_SECOND_DIFF = np.sqrt(6.0)  # var(x[i-1] - 2x[i] + x[i+1]) = 6 sigma^2
_CHI2_1_MEDIAN = 0.4549  # median of a chi-square with 1 degree of freedom


def binlets_available() -> bool:
    try:
        import binlets  # noqa: F401
    except Exception:
        return False
    return True


@dataclass(frozen=True)
class NoiseModel:
    """Per-pixel detector noise as ``var = gain * mean + offset``."""

    gain: float
    offset: float

    def sigma_at(self, mean: float) -> float:
        return float(np.sqrt(max(self.gain * float(mean) + self.offset, 0.0)))

    def __str__(self) -> str:
        return (f"var = {self.gain:.2f}*mean + {self.offset:.4g} "
                f"(sigma at 5000 counts: {self.sigma_at(5000):.0f})")


def _calibrate_on_flat_pixels(stack: np.ndarray, model: NoiseModel) -> NoiseModel:
    """Rescale a fitted model so it matches the null the merge test assumes.

    The transfer-curve fit is biased high: real image structure leaks into the
    per-bin noise floor, more so in structured images. Left uncorrected the test
    sees an inflated variance, calls every pair consistent, and bins everything
    (``n_sigma`` then has no effect at all -- the tell-tale symptom).

    Fix: on pixels that lie in *flat* parts of the image, the pairwise statistic
    ``(x-y)^2 / var`` must follow chi-square with 1 dof, whose median is 0.4549.
    One multiplicative factor on the variance makes that true.
    """
    from scipy.ndimage import gaussian_filter

    data = np.asarray(stack, dtype=np.float64)
    projection = gaussian_filter(data.reshape(-1, *data.shape[-2:]).mean(axis=0), 2)
    gradient_y, gradient_x = np.gradient(projection)
    gradient = np.hypot(gradient_y, gradient_x)
    flat = gradient < np.percentile(gradient, 25)
    flat_pairs = flat[:, :-1] & flat[:, 1:]
    if flat_pairs.sum() < 100:
        logger.warning("Too few flat pixels to calibrate the noise model; using the raw fit.")
        return model

    x, y = data[..., :-1], data[..., 1:]
    variance = model.gain * (x + y) + 2.0 * model.offset
    variance = np.where(variance <= 0, np.inf, variance)
    median_chi2 = float(np.median(((x - y) ** 2 / variance)[..., flat_pairs]))
    if not np.isfinite(median_chi2) or median_chi2 <= 0:
        logger.warning("Noise-model calibration failed; using the raw fit.")
        return model

    scale = median_chi2 / _CHI2_1_MEDIAN
    logger.info(
        "Noise-model calibration: median chi2 on flat pixels %.3f (target %.4f) -> variance x%.3f",
        median_chi2, _CHI2_1_MEDIAN, scale,
    )
    return NoiseModel(gain=model.gain * scale, offset=model.offset * scale)


def estimate_noise_model(
    stack: np.ndarray, *, n_bins: int = 20, calibrate: bool = True
) -> NoiseModel:
    """Fit ``var = gain * mean + offset`` from the data (photon-transfer curve).

    Uses the second spatial difference along x, which cancels local linear
    trends, and takes the *25th percentile* of its magnitude inside each
    intensity bin: real image structure only ever adds to a second difference,
    so a low percentile approximates the pure-noise floor.

    This replaces the naive ``var/mean`` estimate, which folds the read-noise
    floor into the gain and overestimates it badly for a current-mode PMT.
    """
    data = np.asarray(stack, dtype=np.float64)
    if data.ndim < 3:
        raise ValueError(f"Expected at least (bands, Y, X), got shape {data.shape}.")

    diff = np.abs(data[..., :-2] - 2 * data[..., 1:-1] + data[..., 2:]).ravel()
    mean = ((data[..., :-2] + data[..., 1:-1] + data[..., 2:]) / 3.0).ravel()

    # Quantile edges, not linear ones: intensity histograms are clumpy (most
    # pixels sit in a narrow range), so linear bins leave most of them empty.
    edges = np.unique(np.quantile(mean, np.linspace(0.02, 0.98, n_bins + 1)))
    index = np.digitize(mean, edges) - 1
    min_per_bin = max(50, mean.size // (max(len(edges) - 1, 1) * 50))

    means, variances = [], []
    for bin_index in range(len(edges) - 1):
        selected = index == bin_index
        if selected.sum() < min_per_bin:
            continue
        sigma = np.percentile(diff[selected], 25) * _P25_TO_SIGMA / _SECOND_DIFF
        means.append(np.median(mean[selected]))
        variances.append(sigma ** 2)

    if len(means) < 3 or np.ptp(means) <= 0:
        raise ValueError(
            "Not enough intensity range to fit a noise model from this data. "
            "Pass gain and offset explicitly instead."
        )

    gain, offset = np.polyfit(np.asarray(means), np.asarray(variances), 1)
    model = NoiseModel(gain=float(max(gain, 1e-6)), offset=float(max(offset, 0.0)))
    if calibrate:
        model = _calibrate_on_flat_pixels(stack, model)
    logger.info("Estimated noise model: %s", model)
    return model


def binlets_denoise(
    stack: np.ndarray,
    *,
    n_sigma: float = 1.0,
    levels: int | None = 3,
    gain: float = 1.0,
    offset: float = 0.0,
    joint_channels: bool = True,
) -> np.ndarray:
    """Adaptively bin a ``(bands, Y, X)`` stack, preserving the spectral axis.

    Parameters
    ----------
    stack
        ``(bands, Y, X)``. binlets treats the first axis as channels and bins
        only the spatial ones, which is already the HS-MOSAIC layout.
    n_sigma
        Merge threshold. Larger bins more aggressively (smoother, more
        resolution loss); 1.0 is the plain chi-square test.
    levels
        Maximum bin size is ``2**levels`` per axis. ``None`` lets binlets pick
        the maximum for the image size, which is usually far too aggressive --
        3 (up to 8x8) is a sane starting point.
    gain, offset
        Detector noise model, ``var = gain * mean + offset``. Defaults describe
        photon counting; for a current-mode PMT get them from
        :func:`estimate_noise_model`.
    joint_channels
        Decide each merge on the whole spectrum at once (recommended): the
        chi-square is pooled over all channels, so one decision is backed by
        every band and the spectral axis stays coherent. ``False`` tests each
        band independently, which can bin bands differently and distort spectra.

    Returns
    -------
    Denoised stack, same shape and dtype as the input.
    """
    try:
        from binlets import binlets
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError(_INSTALL_HINT) from exc

    source = np.asarray(stack)
    if source.ndim < 3:
        raise ValueError(
            f"Expected at least (channels, Y, X), got shape {source.shape}. "
            "Axis 0 carries the channels; every remaining axis is binned."
        )
    data = source.astype(np.float64)
    gain = float(gain)
    if gain <= 0:
        raise ValueError("gain must be > 0.")
    offset = float(max(offset, 0.0))
    n_bands = data.shape[0]
    threshold = float(n_sigma) ** 2

    # Pooling over k channels turns the test into a chi-square with k degrees of
    # freedom, whose mean is k and standard deviation sqrt(2k) -- NOT k times the
    # single-channel threshold. Comparing the sum against n_sigma**2 * k would
    # put the cut at the *mean* of the null for n_sigma=1, i.e. a coin flip.
    # Use the Gaussian approximation to the upper tail instead, so n_sigma means
    # the same thing in both branches.
    joint_threshold = n_bands + float(n_sigma) * np.sqrt(2.0 * n_bands)

    def chi2_test(x: np.ndarray, y: np.ndarray, *, level: int) -> np.ndarray:
        """True where two candidate bins are statistically indistinguishable.

        ``x`` and ``y`` are sums of ``2**level`` raw pixels (unnormalized Haar),
        so the constant noise floor scales with the number of pooled pixels.
        """
        pooled = 2.0 ** int(level)
        difference = x - y
        variance = gain * (x + y) + 2.0 * pooled * offset
        variance = np.where(variance <= 0, np.inf, variance)
        chi2 = difference ** 2 / variance
        if joint_channels:
            # one decision per pixel, pooled over every spectral channel
            return chi2.sum(axis=0) <= joint_threshold
        return chi2 <= threshold

    logger.info(
        "binlets: %s channels, binning %s, n_sigma=%.2f, levels=%s, gain=%.3f, offset=%.4g, joint=%s",
        n_bands, "x".join(str(n) for n in data.shape[1:]), n_sigma, levels, gain, offset, joint_channels,
    )
    result = binlets(data, test=chi2_test, levels=levels, linear=True)
    # the signature advertises a tuple; the implementation returns the array
    if isinstance(result, tuple):
        result = result[0]
    denoised = np.maximum(np.asarray(result, dtype=np.float64), 0.0)

    logger.info(
        "binlets done: mean preserved %.6g -> %.6g, std %.1f -> %.1f",
        float(data.mean()), float(denoised.mean()),
        float(data.std()), float(denoised.std()),
    )

    if np.issubdtype(source.dtype, np.integer):
        info = np.iinfo(source.dtype)
        return np.clip(np.round(denoised), info.min, info.max).astype(source.dtype)
    return denoised.astype(source.dtype, copy=False)


# Alias kept so `poisson_binlets` keeps working; the noise model is affine,
# not strictly Poisson, so `binlets_denoise` is the accurate name.
poisson_binlets = binlets_denoise


def estimate_gain(stack: np.ndarray, region: tuple[int, int, int, int] | None = None) -> float:
    """Effective gain only, from :func:`estimate_noise_model`.

    ``region`` is accepted for backwards compatibility and restricts the fit to
    a ``(y0, x0, height, width)`` box.
    """
    data = np.asarray(stack)
    if region is not None:
        y0, x0, height, width = (int(v) for v in region)
        data = data[:, y0:y0 + height, x0:x0 + width]
    return estimate_noise_model(data).gain
