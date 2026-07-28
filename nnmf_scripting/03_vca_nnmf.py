"""NNMF seeded with Vertex Component Analysis (VCA).

VCA picks the purest pixels in the data and their spectra become the H seeds --
no manual regions needed. Components that already carry a seed are left alone,
so you can mix VCA with ROIs (add `rois=[...]` to PARAMS).

Edit the SETTINGS block and run the file. Figures are saved and shown.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hs_nnmf import (
    DEFAULT_PALETTE,
    NNMFParams,
    VcaParams,
    configure_logging,
    data_path,
    load_dataset,
    plot_composite,
    run_nnmf,
    save_composite_image,
    save_figures,
)

# ----------------------------------------------------------------- SETTINGS --
def main():
    DATA = data_path("2017_03_23_Lungcells_Day2_60mWBoth_2xZoom_16ms_Pos2_HS_CARS_ch-1_C.tif")
    RESULT_DIR = Path(__file__).resolve().parent / "results" / "vca"
    LABEL = "vca"
    PALETTE = DEFAULT_PALETTE  # or: high_contrast | okabe_ito | classic_rgb

    PARAMS = NNMFParams(
        n_components=3,
        init="custom",
        vca=VcaParams(
            enabled=True,
            n_endmembers=None,       # None -> n_components
            seed=0,                  # RNG seed of the VCA projection (reproducible)
            clip_negative=True,
            use_subtracted=False,
        ),
        background_components=(2,),  # treat component 2 as non-resonant background
        w_seed_mode="nnls",
        w_seed_downsample=4,
        normalize_h_to_unity=True,
        solver="mu",
        backend="gpu",
        max_iter=500,
        tol=1e-4,
        patience=3,
    )

    # False-color composite: true additive RGB (what FIJI and the GUI's composite
    # view do)
    COMPOSITE = dict(
        palette=PALETTE, mode="additive", gamma=1.0, low_percentile=0.0
    )
    # ------------------------------------------------------------------------------

    configure_logging("INFO")

    stack, wavenumbers, unit = load_dataset(DATA)
    print(f"stack {stack.shape} {stack.dtype}   axis {wavenumbers.max():.1f} ... {wavenumbers.min():.1f} {unit}")

    result = run_nnmf(stack, wavenumbers, PARAMS, spectral_unit=unit, label=LABEL)
    print(result.summary())
    print("VCA endmember pixels (y, x):", result.seed_info.get("vca_endmember_pixels"))

    result.save(RESULT_DIR, basename=LABEL)

    # full-size composite window + a pixel-exact RGB export (one pixel per pixel)
    composite = plot_composite(result, title=f"{LABEL}: composite", **COMPOSITE)
    composite.savefig(RESULT_DIR / f"{LABEL}_composite.png", dpi=200,
                      facecolor=composite.get_facecolor())
    save_composite_image(result, RESULT_DIR / f"{LABEL}_composite_rgb.png", **COMPOSITE)

    save_figures(result, RESULT_DIR, basename=LABEL, palette=PALETTE, show=True)
    print(f"results in {RESULT_DIR}")

if __name__ == "__main__":
    main()
