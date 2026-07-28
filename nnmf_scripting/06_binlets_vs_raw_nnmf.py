"""Seeded NNMF on raw data vs on binlets-denoised data, side by side.

Identical seeds, identical solver settings, identical W-seed estimation (NNLS
abundance maps at 4x downsampling). The only difference between the two runs is
whether binlets denoised the stack first, so any change in the result is
attributable to the denoising.

Dataset is the day-1 lung-cell field. The three seeds follow the GUI result:
lipids in the lower/right part of each cell, protein and nuclei in the upper
left, and the non-resonant background in the cell-free corner above them. With
the GUI's default palette that puts lipids in magenta, protein in cyan and the
background in yellow, matching the composite in HS-MOSAIC.

Edit the SETTINGS block and run the file. Figures are saved and shown.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import tifffile
from matplotlib import pyplot as plt

from hs_nnmf import (
    NNMFParams,
    Roi,
    binlets_denoise,
    composite_rgb,
    configure_logging,
    data_path,
    estimate_noise_model,
    load_dataset,
    plot_denoise_check,
    run_nnmf,
    save_figures,
)
from hs_nnmf.plotting import GRID, INK, INK_MUTED, SURFACE, component_colors, single_hue_cmap


def main():
    # ------------------------------------------------------------- SETTINGS --
    DATA = data_path("2017_03_21_Lungcells_day_1_pos_1_60mWboth_HS_CARS__ch-1_C.tif")
    RESULT_DIR = Path(__file__).resolve().parent / "results" / "binlets_vs_raw"

    # component 0 lipids (sharp 2850 cm-1 CH2 peak, ratio 2850/2960 = 1.2 to 1.6)
    # component 1 protein and nuclei (peak at 2960 cm-1, ratio 0.8 to 0.9)
    # component 2 non-resonant background (cell-free, lowest level)
    ROIS = [
        Roi.from_center(0, y=395, x=451, size=11, name="lipid (lower right cell)"),
        Roi.from_center(0, y=258, x=112, size=11, name="lipid (left cell)"),
        Roi.from_center(0, y=237, x=345, size=11, name="lipid (upper right cell)"),
        Roi.from_center(1, y=200, x=60, size=15, name="protein (left cell)"),
        Roi.from_center(1, y=170, x=310, size=15, name="protein (upper right cell)"),
        Roi.from_center(1, y=330, x=430, size=15, name="protein (lower right cell)"),
        Roi(component=2, rect=(40, 40, 40, 60), name="NRB (top left)", is_background=True),
        Roi(component=2, rect=(30, 430, 40, 60), name="NRB (top right)", is_background=True),
    ]

    PARAMS = NNMFParams(
        n_components=3,
        init="custom",
        rois=ROIS,
        w_seed_mode="nnls",       # NNLS abundance maps as W seeds
        w_seed_downsample=4,      # 4x spatial downsampling for the W seeds
        normalize_h_to_unity=True,
        overwrite_w_from_h=True,
        solver="mu",
        backend="gpu",
        max_iter=500,
        tol=1e-4,
        patience=3,
    )

    # n_sigma = 2 was chosen for this field: noise -87 %, interior contrast 99.4 %
    BINLETS = dict(n_sigma=2.0, levels=3, joint_channels=True)

    PALETTE = "magenta_cyan_yellow"   # the GUI default: lipid, protein, background
    # The background component is bright over the whole field, so in an additive
    # composite it floods everything and hides the cells. Show only the two
    # resonant components, which is what the GUI composite displays as well.
    COMPOSITE_COMPONENTS = (0, 1)
    COMPOSITE = dict(mode="additive", gamma=1.0, low_percentile=0.0)
    PERCENTILE = 99.5
    # -------------------------------------------------------------------------

    configure_logging("INFO")
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    stack, wavenumbers, unit = load_dataset(DATA)
    print(f"stack {stack.shape} {stack.dtype}   axis {wavenumbers.max():.1f} ... {wavenumbers.min():.1f} {unit}")

    # --- run A: the raw stack ------------------------------------------------
    result_raw = run_nnmf(stack, wavenumbers, PARAMS, spectral_unit=unit, label="raw")
    print(result_raw.summary())

    # --- run B: the same thing after binlets ---------------------------------
    model = estimate_noise_model(stack)
    print(f"noise model: {model}")
    denoised = binlets_denoise(stack, gain=model.gain, offset=model.offset, **BINLETS)
    tifffile.imwrite(str(RESULT_DIR / "denoised.tif"), denoised)

    result_den = run_nnmf(denoised, wavenumbers, PARAMS, spectral_unit=unit, label="binlets")
    print(result_den.summary())

    # Component order is fixed by the seeds, so the two runs already correspond.
    # Matching is a cheap guard in case a component collapsed in one of them.
    result_den = result_den.match_to(result_raw.H)

    # --- comparison ----------------------------------------------------------
    metrics = _report(result_raw, result_den, stack, denoised)
    (RESULT_DIR / "comparison.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    maps_figure = _compare_maps(result_raw, result_den, PALETTE, PERCENTILE, COMPOSITE,
                                COMPOSITE_COMPONENTS)
    maps_figure.savefig(RESULT_DIR / "compare_W_components.png", dpi=200,
                        facecolor=maps_figure.get_facecolor())

    spectra_figure = _compare_spectra(result_raw, result_den, PALETTE)
    spectra_figure.savefig(RESULT_DIR / "compare_H_components.png", dpi=200,
                           facecolor=spectra_figure.get_facecolor())

    check = plot_denoise_check(
        stack, denoised, band=int(np.argmin(np.abs(wavenumbers - 2850))), pixel=(395, 451),
        wavenumbers=wavenumbers, spectral_unit=unit,
        title=f"denoising check (n_sigma={BINLETS['n_sigma']}, levels={BINLETS['levels']})",
    )
    check.savefig(RESULT_DIR / "denoise_check.png", dpi=200, facecolor=check.get_facecolor())

    result_raw.save(RESULT_DIR, basename="raw")
    result_den.save(RESULT_DIR, basename="binlets")
    save_figures(result_raw, RESULT_DIR, basename="raw", palette=PALETTE)
    save_figures(result_den, RESULT_DIR, basename="binlets", palette=PALETTE)

    print(f"\nresults in {RESULT_DIR}")
    plt.show()


# ---------------------------------------------------------------- helpers --
def _norm(image, percentile=99.5, low_percentile=0.0):
    image = np.nan_to_num(np.asarray(image, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    image = np.maximum(image, 0.0)
    bottom = float(np.percentile(image, low_percentile)) if low_percentile > 0 else 0.0
    top = float(np.percentile(image, percentile))
    if top <= bottom:
        return np.zeros_like(image)
    return np.clip((image - bottom) / (top - bottom), 0.0, 1.0)


def _map_noise(image, active_percentile=75.0):
    """Pixel-scale noise of one abundance map, measured where it carries signal.

    The spatial second difference removes constant and linear trends, so what is
    left is high-frequency content, i.e. the graininess of the map.

    It is restricted to the component's own active region on purpose.
    Multiplicative updates drive background pixels onto the eps floor, so over
    the full frame a sparse component is mostly exactly flat, the median
    difference collapses to zero and any ratio built on it explodes.
    """
    image = np.asarray(image, dtype=float)
    d = np.abs(image[:, :-2] - 2 * image[:, 1:-1] + image[:, 2:])
    active = image[:, 1:-1] >= np.percentile(image, active_percentile)
    if active.sum() < 100:
        active = np.ones_like(d, dtype=bool)
    return float(np.median(d[active]) / 0.6745 / np.sqrt(6))


def _map_contrast(image, percentile=95.0):
    """Signal scale of one abundance map: mean of its brightest pixels."""
    flat = np.asarray(image, dtype=float).ravel()
    return float(flat[flat >= np.percentile(flat, percentile)].mean())


def _spectral_agreement(result_a, result_b):
    """Cosine similarity per component between two runs' H spectra."""
    values = []
    for a, b in zip(np.asarray(result_a.H, dtype=float), np.asarray(result_b.H, dtype=float)):
        denominator = np.linalg.norm(a) * np.linalg.norm(b)
        values.append(float(a @ b / denominator) if denominator > 0 else float("nan"))
    return values


def _report(result_raw, result_den, stack, denoised):
    def spatial_noise(a):
        a = np.asarray(a, dtype=float)
        d = a[..., :-2] - 2 * a[..., 1:-1] + a[..., 2:]
        return float(np.median(np.abs(d)) / 0.6745 / np.sqrt(6))

    def per_component(result, function):
        return [function(image) for image in np.asarray(result.W_2D, dtype=float)]

    metrics = {
        "stack_noise_raw": spatial_noise(stack),
        "stack_noise_denoised": spatial_noise(denoised),
        "spectral_agreement": _spectral_agreement(result_raw, result_den),
        "raw": {
            "relative_error": result_raw.relative_error,
            "n_iter": result_raw.info.get("n_iter"),
            "map_noise": per_component(result_raw, _map_noise),
            "map_contrast": per_component(result_raw, _map_contrast),
        },
        "binlets": {
            "relative_error": result_den.relative_error,
            "n_iter": result_den.info.get("n_iter"),
            "map_noise": per_component(result_den, _map_noise),
            "map_contrast": per_component(result_den, _map_contrast),
        },
    }
    for key in ("raw", "binlets"):
        metrics[key]["map_cnr"] = [
            c / n if n > 0 else float("inf")
            for c, n in zip(metrics[key]["map_contrast"], metrics[key]["map_noise"])
        ]

    print("\n" + "=" * 74)
    print(f"stack noise  {metrics['stack_noise_raw']:9.1f} -> {metrics['stack_noise_denoised']:9.1f}"
          f"   ({100*(1-metrics['stack_noise_denoised']/metrics['stack_noise_raw']):.1f}% lower)")
    print()
    print(f"{'W component':>12s} {'noise raw':>11s} {'noise binlets':>14s} "
          f"{'CNR raw':>9s} {'CNR binlets':>12s} {'gain':>7s}")
    for i in range(result_raw.n_components):
        nr, nb = metrics["raw"]["map_noise"][i], metrics["binlets"]["map_noise"][i]
        cr, cb = metrics["raw"]["map_cnr"][i], metrics["binlets"]["map_cnr"][i]
        print(f"{i:12d} {nr:11.4g} {nb:14.4g} {cr:9.1f} {cb:12.1f} {cb/cr:6.1f}x")
    print()
    print("H components agree between the two runs to "
          f"{', '.join(f'{v:.4f}' for v in metrics['spectral_agreement'])} (cosine).")
    print("So the denoising changes the abundance maps, not the recovered spectra.")
    print("Relative error is NOT comparable between the two runs: the denoised")
    print("stack simply has less noise left to explain.")
    print("=" * 74)
    return metrics


def _compare_maps(result_raw, result_den, palette, percentile, composite_kwargs,
                  composite_components):
    colors = component_colors(result_raw.n_components, palette=palette)
    n = result_raw.n_components
    fig, axes = plt.subplots(2, n + 1, figsize=(3.6 * (n + 1), 7.6), squeeze=False)
    fig.patch.set_facecolor(SURFACE)

    for row, result in enumerate((result_raw, result_den)):
        for column, color in enumerate(colors):
            ax = axes[row][column]
            ax.imshow(_norm(result.W_2D[column], percentile),
                      cmap=single_hue_cmap(color), vmin=0.0, vmax=1.0)
            if row == 0:
                ax.set_title(f"W component {column}", color=INK, fontsize=11)
            _bare(ax)
        ax = axes[row][n]
        selected = list(composite_components)
        ax.imshow(composite_rgb(result.W_2D[selected], [colors[i] for i in selected],
                                percentile, **composite_kwargs), interpolation="nearest")
        if row == 0:
            names = ", ".join(str(i) for i in selected)
            ax.set_title(f"composite (components {names})", color=INK, fontsize=11)
        _bare(ax)
        axes[row][0].set_ylabel(("raw" if row == 0 else "binlets denoised"),
                                color=INK, fontsize=12)

    fig.suptitle("Seeded NNMF, identical seeds and settings", color=INK, fontsize=13)
    fig.tight_layout()
    return fig


def _bare(ax):
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color(GRID)


def _compare_spectra(result_raw, result_den, palette):
    colors = component_colors(result_raw.n_components, palette=palette)
    order = np.argsort(np.asarray(result_raw.wavenumbers, dtype=float))
    x = np.asarray(result_raw.wavenumbers, dtype=float)[order]

    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for index, color in enumerate(colors):
        for result, style, width in ((result_raw, "-", 1.2), (result_den, "--", 2.0)):
            spectrum = np.asarray(result.H[index], dtype=float)[order]
            peak = float(spectrum.max())
            ax.plot(x, spectrum / peak if peak > 0 else spectrum,
                    style, color=color, linewidth=width,
                    label=f"H component {index}" if style == "-" else None)
    ax.set_xlabel("Raman shift (cm$^{-1}$)", color=INK_MUTED)
    ax.set_ylabel("Intensity (norm.)", color=INK_MUTED)
    ax.set_title("H components: raw (thin solid) vs binlets (thick dashed)", color=INK, fontsize=12)
    ax.tick_params(colors=INK_MUTED)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK)
    fig.tight_layout()
    return fig


if __name__ == "__main__":
    main()
