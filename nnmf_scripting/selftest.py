"""Quick self-test: exercises every seeding path on small synthetic data.

Run this first in a new environment -- it needs no measurement data and
finishes in a few seconds::

    python selftest.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import matplotlib

matplotlib.use("Agg")

from hs_nnmf import (
    NNMFParams,
    Roi,
    SpectralSeed,
    VcaParams,
    binlets_available,
    composite_rgb,
    configure_logging,
    run_nnmf,
    save_composite_image,
    save_figures,
    wavenumbers_from_beams,
)


def synthetic_stack(bands: int = 40, size: int = 64, seed: int = 0):
    """A 3-component phantom: lipid blob, protein blob, flat background."""
    rng = np.random.default_rng(seed)
    wavenumbers = wavenumbers_from_beams(
        bands, tuned_min_nm=801.2, tuned_max_nm=831.2, fixed_beam_nm=1064.0
    )

    def gaussian(center, width):
        return np.exp(-0.5 * ((wavenumbers - center) / width) ** 2)

    H_true = np.stack([gaussian(2850, 25), gaussian(2930, 30), np.full(bands, 0.4)])
    maps = np.zeros((3, size, size))
    maps[0, 10:20, 10:20] = 1.0
    maps[1, 35:50, 30:45] = 1.0
    maps[2] = 0.6
    clean = maps.reshape(3, -1).T @ H_true * 8000.0
    noisy = rng.poisson(np.maximum(clean, 1.0)).astype(np.uint16)
    stack = np.moveaxis(noisy.reshape(size, size, bands), -1, 0)
    return stack, wavenumbers, H_true


def main() -> int:
    configure_logging("WARNING", hs_mosaic_level="ERROR")
    stack, wavenumbers, H_true = synthetic_stack()
    size = stack.shape[1]
    common = dict(n_components=3, max_iter=200, w_seed_downsample=2)
    checks: list[tuple[str, bool, str]] = []

    def check(name, condition, detail=""):
        checks.append((name, bool(condition), detail))
        print(f"  [{'ok ' if condition else 'FAIL'}] {name} {detail}")

    print("hs_nnmf self-test")
    print(f"  stack {stack.shape} {stack.dtype}\n")

    # 1. random init
    result = run_nnmf(stack, wavenumbers, NNMFParams(init="random", **common), label="random")
    check("random init", result.W_2D.shape == (3, size, size), result.summary())

    # 2. VCA seeds
    result = run_nnmf(
        stack, wavenumbers,
        NNMFParams(init="custom", vca=VcaParams(enabled=True), **common), label="vca",
    )
    check("VCA seeds", result.seed_H is not None and np.all(result.seed_H >= 0))

    # 3. ROI seeds: rectangle, centre, explicit pixel list, mask
    mask = np.zeros((size, size), dtype=bool)
    mask[36:48, 31:44] = True
    rois = [
        Roi.from_center(0, y=15, x=15, size=5, name="lipid"),
        Roi(component=1, mask=mask, name="protein", sigma=1.0),
        Roi(component=2, pixels=[(2, 2), (2, 60), (60, 2), (61, 61)], name="bgd", is_background=True),
    ]
    roi_result = run_nnmf(stack, wavenumbers, NNMFParams(init="custom", rois=rois, **common), label="rois")
    check("ROI seeds (rect/centre/pixels/mask)", roi_result.seed_W_2D is not None)

    # recovered spectra should resemble the truth they were seeded from
    matched = roi_result.match_to(H_true)
    similarity = [
        float(np.corrcoef(matched.H[i], H_true[i])[0, 1]) for i in range(2)
    ]
    check("ROI run recovers the seeded H components", min(similarity) > 0.8,
          f"correlations {np.round(similarity, 3).tolist()}")

    # 4. every W seed mode
    for mode in ("nnls", "selective_score", "h_weighted", "average", "empty"):
        params = NNMFParams(init="custom", rois=rois, w_seed_mode=mode, **common)
        mode_result = run_nnmf(stack, wavenumbers, params, label=f"w_seed={mode}")
        check(f"W seed mode '{mode}'", np.isfinite(mode_result.H).all())

    # 5. downsample factors
    for factor in (1, 2, 4):
        params = dict(common)
        params["w_seed_downsample"] = factor
        ds_result = run_nnmf(stack, wavenumbers, NNMFParams(init="custom", rois=rois, **params),
                             label=f"ds={factor}")
        check(f"W seed downsample {factor}", ds_result.W_2D.shape == (3, size, size))

    # 6. spectral seeds, background subtraction, fixed W, no unity scaling
    params = NNMFParams(
        init="custom",
        rois=[rois[0]],
        spectral_seeds=[SpectralSeed(component=1, wavenumber=2930, width=40)],
        background_roi=Roi(component=2, rect=(0, 0, 4, 4), name="bg", is_background=True),
        background_components=(2,),
        fixed_w_seeds={2: np.full(size * size, 0.5)},
        normalize_h_to_unity=False,
        **common,
    )
    mixed = run_nnmf(stack, wavenumbers, params, label="mixed")
    check("spectral seed + subtraction + fixed W", mixed.H.shape == (3, stack.shape[0]))

    # 7. composites: true RGB, both blend modes, per-channel levels
    additive = composite_rgb(roi_result.W_2D, mode="additive")
    multiply = composite_rgb(roi_result.W_2D, mode="multiply")
    levelled = composite_rgb(roi_result.W_2D, mode="additive",
                             low_percentile=(0, 0, 70), gamma=0.8)
    check("composite additive is RGB in [0,1]",
          additive.shape == (size, size, 3) and 0.0 <= additive.min() and additive.max() <= 1.0)
    check("composite multiply differs from additive", not np.allclose(additive, multiply))
    check("per-channel levels change the composite", not np.allclose(additive, levelled))
    check("additive background is dark", float(additive.min()) < 0.05)

    # 8. saving
    with tempfile.TemporaryDirectory() as tmp:
        files = roi_result.save(tmp)
        figures = save_figures(roi_result, tmp)
        composite_png = save_composite_image(roi_result, Path(tmp) / "composite.png")
        check("save() writes tif/csv/json", all(p.exists() for p in files.values()))
        check("save_figures() writes png/pdf", len(figures) == 6 and all(p.exists() for p in figures))
        check("save_composite_image() writes a pixel-exact png", composite_png.exists())

    # 9. binlets, only if it is installed
    if binlets_available():
        from hs_nnmf import binlets_denoise, estimate_noise_model

        model = estimate_noise_model(stack)
        check("noise model fits var = gain*mean + offset",
              model.gain > 0 and model.offset >= 0, str(model))
        denoised = binlets_denoise(stack, gain=model.gain, offset=model.offset,
                                   n_sigma=3.0, levels=2)
        raw_f, den_f = stack.astype(float), denoised.astype(float)
        mean_shift = abs(den_f.mean() - raw_f.mean()) / raw_f.mean()

        def spatial_noise(a):
            d = a[:, :, :-2] - 2 * a[:, :, 1:-1] + a[:, :, 2:]
            return float(np.median(np.abs(d)) / 0.6745 / np.sqrt(6))

        check("binlets preserves shape and dtype",
              denoised.shape == stack.shape and denoised.dtype == stack.dtype)
        check("binlets preserves the mean", mean_shift < 0.01, f"shift {mean_shift*100:.2f}%")
        check("binlets reduces spatial noise",
              spatial_noise(den_f) < spatial_noise(raw_f),
              f"{spatial_noise(raw_f):.0f} -> {spatial_noise(den_f):.0f}")
    else:
        print(f"\n  binlets not installed -- skipping its checks (optional)")
    failed = [name for name, ok, _ in checks if not ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("self-test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
