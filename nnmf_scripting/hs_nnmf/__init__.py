"""Scripted access to HS-MOSAIC's custom (seeded) NNMF.

Minimal use::

    from hs_nnmf import load_dataset, NNMFParams, run_nnmf, save_figures

    stack, wavenumbers, unit = load_dataset("stack.tif")
    params = NNMFParams(n_components=3, init="random")
    result = run_nnmf(stack, wavenumbers, params, spectral_unit=unit)
    result.save("out")
    save_figures(result, "out")

The HS-MOSAIC package itself is imported read-only; nothing here modifies or
patches it.
"""

from ._bootstrap import ensure_hs_mosaic_importable

ensure_hs_mosaic_importable()

from .config import NNMFParams, Roi, SpectralSeed, VcaParams, W_SEED_MODES
from .data_io import (
    band_index,
    data_path,
    load_dataset,
    load_stack,
    wavenumbers_from_beams,
    wavenumbers_from_json,
)
from .plotting import (
    CLASSIC_COLORS,
    DEFAULT_COLORS,
    composite_rgb,
    composite_rgb_uint8,
    plot_component_maps,
    plot_composite,
    plot_denoise_check,
    plot_roi_overview,
    plot_spectra,
    save_composite_image,
    save_figures,
)
from .runner import NNMFResult, run_nnmf
from .binlets_bridge import (
    NoiseModel,
    binlets_available,
    binlets_denoise,
    estimate_gain,
    estimate_noise_model,
    poisson_binlets,
)

__all__ = [
    "NNMFParams",
    "NNMFResult",
    "Roi",
    "SpectralSeed",
    "VcaParams",
    "W_SEED_MODES",
    "run_nnmf",
    "data_path",
    "load_dataset",
    "load_stack",
    "wavenumbers_from_beams",
    "wavenumbers_from_json",
    "band_index",
    "plot_component_maps",
    "plot_composite",
    "plot_roi_overview",
    "plot_spectra",
    "composite_rgb",
    "composite_rgb_uint8",
    "save_composite_image",
    "save_figures",
    "DEFAULT_COLORS",
    "CLASSIC_COLORS",
    "binlets_available",
    "binlets_denoise",
    "estimate_noise_model",
    "NoiseModel",
    "estimate_gain",
    "poisson_binlets",
    "plot_denoise_check",
]


def configure_logging(level: int | str = "INFO", hs_mosaic_level: int | str = "WARNING") -> None:
    """Console logging for scripts.

    HS-MOSAIC's own loggers are very chatty per seed component; they are kept at
    WARNING by default. Pass ``hs_mosaic_level="INFO"`` to see the full seeding
    trace the GUI writes to its log.
    """
    import logging

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("hs_mosaic").setLevel(hs_mosaic_level)
    logging.getLogger("hs_nnmf").setLevel(level)
