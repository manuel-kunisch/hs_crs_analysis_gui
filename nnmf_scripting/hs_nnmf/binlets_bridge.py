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

The shot term is level-independent, which is the property of the summing Haar
that lets photon-counting data work with no level correction (``gain=1``,
``offset=0``). A **current-mode PMT** is different: its read/dark/digitisation
floor is a real constant per pixel, so it *accumulates* with the bin size and
must be carried through the levels. Ignoring it makes the test too strict at
high levels (it under-bins, and the denoising quietly stops working).

``gain`` is not the PMT high-voltage gain. With ``k`` the ADU per photoelectron
and ``F`` the excess-noise factor of the dynode chain (~1.2-2), the photoelectron
statistics give ``Var = F*k^2*lambda = (F*k)*mean``, so ``gain = F*k``: ADU per
*effective* photoelectron. Useful corollary: ``mean/gain`` is the effective
number of quanta behind a measurement (~15 per pixel and band on the CARS data).
:func:`estimate_noise_model` fits it from the data.

A code-next-to-physics walkthrough of the whole chain is in
``nnmf_scripting/docs/binlets_physics.md``.

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

# Conversion factors used by ``estimate_noise_model``.
#
# If zero-mean Gaussian noise has standard deviation sigma, its absolute value
# follows a half-normal distribution. The 25th percentile of that distribution
# is 0.3186 * sigma. Therefore:
#
#     sigma = percentile_25(abs(noise)) / 0.3186
#
# This lower percentile is used instead of the usual variance because edges and
# other real structures produce large spatial differences. A low percentile is
# less influenced by those large values.
_P25_TO_SIGMA = 1.0 / 0.3186

# For three independent pixels with equal noise variance sigma**2, the
# coefficients of the second difference are (1, -2, 1). Variances add with the
# squared coefficients:
#
#     var(x_left - 2*x_center + x_right)
#         = (1**2 + (-2)**2 + 1**2) * sigma**2
#         = 6 * sigma**2
#
# The standard deviation of the second difference is consequently
# sqrt(6) * sigma, so we divide by sqrt(6) to recover per-pixel sigma.
_SECOND_DIFF = np.sqrt(6.0)

# If two pixels contain the same true signal and differ only by independent
# Gaussian noise, their squared standardized difference follows a chi-square
# distribution with one degree of freedom. Its median is approximately 0.4549.
_CHI2_1_MEDIAN = 0.4549  # median of a chi-square with 1 degree of freedom


def binlets_available() -> bool:
    try:
        import binlets  # noqa: F401
    except Exception:
        return False
    return True


@dataclass(frozen=True)
class NoiseModel:
    """Per-pixel detector noise as ``variance = gain * mean + offset``.

    ``mean`` is the expected detector value in counts/ADU. ``variance`` is the
    expected squared fluctuation around that value.

    ``gain`` describes the signal-dependent part: brighter pixels have more
    photon/PMT shot noise. It is the increase in variance per additional count,
    not the voltage gain configured on the PMT.

    ``offset`` is the signal-independent noise floor, such as readout,
    electronic, dark-current, and digitisation noise. Its units are counts
    squared.
    """

    gain: float
    offset: float

    def sigma_at(self, mean: float) -> float:
        """Predicted per-pixel standard deviation at a given intensity.

        Reporting convenience only: sigma is what one can compare against image
        contrast by eye. The merge test itself consumes the *variance*, and
        never takes this square root.
        """
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

    # Average all spectral channels (and any additional leading dimensions)
    # into one 2-D overview image. Gaussian smoothing prevents random
    # pixel-to-pixel noise from being mistaken for anatomical/image structure
    # when the gradient is calculated below.
    projection = gaussian_filter(data.reshape(-1, *data.shape[-2:]).mean(axis=0), 2)
    gradient_y, gradient_x = np.gradient(projection)
    gradient = np.hypot(gradient_y, gradient_x)

    # The lowest-gradient 25% of the overview is treated as locally flat. Both
    # pixels of a horizontal pair must belong to that flat subset. In a truly
    # flat pair, x-y should contain detector noise but almost no real spatial
    # contrast.
    flat = gradient < np.percentile(gradient, 25)
    flat_pairs = flat[:, :-1] & flat[:, 1:]
    if flat_pairs.sum() < 100:
        logger.warning("Too few flat pixels to calibrate the noise model; using the raw fit.")
        return model

    x, y = data[..., :-1], data[..., 1:]

    # For two independent pixels, variances add when they are subtracted:
    #
    #   var(x-y)
    #       = (gain*x + offset) + (gain*y + offset)
    #       = gain*(x+y) + 2*offset
    #
    # The observed squared difference divided by this predicted variance is a
    # dimensionless chi-square statistic.
    variance = model.gain * (x + y) + 2.0 * model.offset
    variance = np.where(variance <= 0, np.inf, variance)
    median_chi2 = float(np.median(((x - y) ** 2 / variance)[..., flat_pairs]))
    if not np.isfinite(median_chi2) or median_chi2 <= 0:
        logger.warning("Noise-model calibration failed; using the raw fit.")
        return model

    # A median above 0.4549 means the observed differences are larger than the
    # model predicts, so both variance terms are increased. A median below the
    # target means the model is too large, so both terms are reduced. This
    # preserves the fitted gain-to-offset ratio; it only adjusts the overall
    # variance scale.
    scale = median_chi2 / _CHI2_1_MEDIAN
    logger.info(
        "Noise-model calibration: median chi2 on flat pixels %.3f (target %.4f) -> variance x%.3f",
        median_chi2, _CHI2_1_MEDIAN, scale,
    )
    return NoiseModel(gain=model.gain * scale, offset=model.offset * scale)


def estimate_noise_model(
    stack: np.ndarray, *, n_bins: int = 20, calibrate: bool = True
) -> NoiseModel:
    """Estimate detector noise from one image stack.

    The fitted relationship is:

    ``noise variance = gain * local mean intensity + offset``

    In practical terms:

    * ``gain * mean`` represents noise that grows with signal intensity,
      principally photon/PMT shot noise.
    * ``offset`` represents an approximately constant electronic/readout noise
      floor.
    * the returned standard deviation at an intensity is
      ``sqrt(gain * mean + offset)``.

    Uses the second spatial difference along x, which cancels local linear
    trends, and takes the *25th percentile* of its magnitude inside each
    intensity bin. Curved edges and texture generally produce large second
    differences, so a low percentile reduces their influence and approximates
    the noise floor. It cannot remove structural contamination completely.

    This replaces the naive ``var/mean`` estimate, which folds the read-noise
    floor into the gain and overestimates it badly for a current-mode PMT.

    This is a pragmatic estimate from a single structured image, not a formal
    detector calibration. A laboratory photon-transfer measurement would use
    repeated, uniformly illuminated frames at several intensities plus dark
    frames.

    Parameters
    ----------
    stack
        Raw detector values with shape ``(..., Y, X)``. For a hyperspectral
        stack this is normally ``(bands, Y, X)``. The last dimension is treated
        as the x direction.
    n_bins
        Number of intensity ranges used to construct the variance-versus-mean
        curve. Quantile bins contain roughly equal numbers of pixel triplets.
    calibrate
        If True, rescale the fitted variance so neighboring pixels in the
        flattest image regions have the expected Gaussian-noise statistic.

    Returns
    -------
    NoiseModel
        ``gain`` and ``offset`` for predicting per-pixel noise variance.
    """
    data = np.asarray(stack, dtype=np.float64)
    if data.ndim < 3:
        raise ValueError(f"Expected at least (bands, Y, X), got shape {data.shape}.")

    # Examine every horizontal group of three pixels:
    #
    #     left, center, right
    #
    # ``left - 2*center + right`` is a discrete second derivative. It is zero
    # for a perfectly constant region and also for a linear intensity ramp. Its
    # remaining value is therefore used as a proxy for high-frequency detector
    # noise. Absolute values are used because only the magnitude matters.
    diff = np.abs(data[..., :-2] - 2 * data[..., 1:-1] + data[..., 2:]).ravel()

    # Associate each second difference with the mean brightness of the same
    # three pixels. This supplies the x-coordinate of the photon-transfer
    # curve: "how much noise is present at this signal intensity?"
    mean = ((data[..., :-2] + data[..., 1:-1] + data[..., 2:]) / 3.0).ravel()

    # Quantile edges, not linear ones: intensity histograms are clumpy (most
    # pixels sit in a narrow range), so linear bins leave most of them empty.
    # The lowest and highest 2% are omitted to reduce the influence of extreme
    # dark values, bright outliers, and possible detector clipping.
    edges = np.unique(np.quantile(mean, np.linspace(0.02, 0.98, n_bins + 1)))
    index = np.digitize(mean, edges) - 1

    # Do not fit an intensity bin unless it contains enough triplets for a
    # reasonably stable percentile. On large images this requires about 2% of
    # the expected samples per equal-population bin, with an absolute minimum
    # of 50.
    min_per_bin = max(50, mean.size // (max(len(edges) - 1, 1) * 50))

    means, variances = [], []
    for bin_index in range(len(edges) - 1):
        selected = index == bin_index
        if selected.sum() < min_per_bin:
            continue

        # Step 1: take the lower quartile of absolute second differences so
        # large edges/structures have less influence.
        #
        # Step 2: convert that half-normal percentile to the standard deviation
        # of the second differences.
        #
        # Step 3: divide by sqrt(6) to obtain the estimated standard deviation
        # of one pixel.
        #
        # Step 4: square sigma because the photon-transfer relationship is
        # linear in *variance*, not in standard deviation.
        sigma = np.percentile(diff[selected], 25) * _P25_TO_SIGMA / _SECOND_DIFF
        means.append(np.median(mean[selected]))
        variances.append(sigma ** 2)

    if len(means) < 3 or np.ptp(means) <= 0:
        raise ValueError(
            "Not enough intensity range to fit a noise model from this data. "
            "Pass gain and offset explicitly instead."
        )

    # Fit a straight line through the representative points:
    #
    #       y = gain*x + offset
    #       y = estimated noise variance
    #       x = median intensity of the bin
    #
    # ``np.polyfit(..., 1)`` returns the slope first and the intercept second.
    gain, offset = np.polyfit(np.asarray(means), np.asarray(variances), 1)

    # The downstream binlets variance calculation requires a positive gain and
    # a non-negative constant noise floor, so the current implementation clips
    # smaller fitted values to those usable limits. This clipping is a software
    # safeguard, not proof that the detector model is correct: a negative raw
    # fit can indicate an unremoved detector baseline or a poor affine fit and
    # should be investigated when the values are used quantitatively.
    model = NoiseModel(gain=float(max(gain, 1e-6)), offset=float(max(offset, 0.0)))

    # The optional second stage checks the model against neighboring pixels in
    # flat regions. It adjusts the overall variance scale but does not change
    # the gain-to-offset ratio determined by the line fit.
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
