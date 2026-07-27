"""NNMF seeded with custom ROIs given as coordinate indices.

Each ROI's mean spectrum becomes the H seed of its component; several ROIs on
the same component are averaged. Before the fit, the mean projection of the
stack is shown with the ROIs drawn on it, so you can check where the seeds sit.

Edit the SETTINGS block and run the file. Figures are saved and shown.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hs_nnmf import (
    NNMFParams,
    Roi,
    configure_logging,
    data_path,
    load_dataset,
    plot_composite,
    plot_roi_overview,
    run_nnmf,
    save_composite_image,
    save_figures,
)

# ----------------------------------------------------------------- SETTINGS --
def main():
    DATA = data_path("2017_03_23_Lungcells_Day2_60mWBoth_2xZoom_16ms_Pos2_HS_CARS_ch-1_C.tif")
    RESULT_DIR = Path(__file__).resolve().parent / "results" / "custom_seeds"
    LABEL = "custom_seeds"

    # its mean spectrum is subtracted for SEED estimation only (fit stays on raw data)
    NRB_SUBTRACT = Roi(component=2, rect=(430, 380, 30, 40), name="NRB subtraction (bottom right)", is_background=True)

    # Spatial seeds. Regions can be given as
    #   Roi.from_center(component, y=..., x=..., size=...)   square around a pixel
    #   Roi(component=..., rect=(y0, x0, height, width))     rectangle
    #   Roi(component=..., pixels=[(y, x), ...])             explicit indices
    #   Roi(component=..., mask=bool_array_YX)               arbitrary region
    # Optional per ROI: name, is_background, sigma (Gaussian smoothing of the
    # spectrum), scale, offset.
    ROIS = [
        # component 0 -- lipid droplets (sharp 2850 cm-1 CH2 peak)
        Roi.from_center(0, y=348, x=150, size=9, name="lipid droplets (lower left)"),
        Roi.from_center(0, y=195, x=307, size=9, name="lipid droplets (upper right)"),
        # component 1 -- nuclei / protein (the large smooth round structures;
        # these three have the highest 2930/2850 ratio in the stack)
        Roi.from_center(1, y=168, x=372, size=15, name="nucleus (upper right)"),
        Roi.from_center(1, y=240, x=352, size=15, name="nucleus (centre right)"),
        Roi.from_center(1, y=370, x=442, size=15, name="nucleus (lower right)"),
        # component 2 -- non-resonant background, cell-free corners
        Roi(component=2, rect=(15, 20, 30, 40), name="NRB (top left)", is_background=True),
        NRB_SUBTRACT,   # still a seed to use to average with the other component seed
    ]

    PARAMS = NNMFParams(
        n_components=3,
        init="custom",
        rois=ROIS,
        background_roi=NRB_SUBTRACT, # subtract this region's mean spectrum from the stack before fitting
        w_seed_mode="nnls",          # nnls | selective_score | h_weighted | average | empty
        w_seed_downsample=4,         # 1 = full resolution W seeds (slower)
        normalize_h_to_unity=True,
        overwrite_w_from_h=True,
        solver="mu",
        backend="gpu",
        max_iter=500,
        tol=1e-4,
        patience=3,
    )

    # False-color composite: true additive RGB (what FIJI and the GUI's composite
    # view do)
    COMPOSITE = dict(mode="additive", gamma=1.0, low_percentile=(0, 0, 70))
    # ------------------------------------------------------------------------------

    configure_logging("INFO")

    stack, wavenumbers, unit = load_dataset(DATA)
    print(f"stack {stack.shape} {stack.dtype}   axis {wavenumbers.max():.1f} ... {wavenumbers.min():.1f} {unit}")

    # where the seeds sit: mean projection over the spectral axis + ROI outlines
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    overview = plot_roi_overview(
        stack, ROIS,
        n_components=PARAMS.n_components,
        title=f"{LABEL}: seed ROIs on the mean projection",
    )
    overview.savefig(RESULT_DIR / f"{LABEL}_roi_overview.png", dpi=200,
                     facecolor=overview.get_facecolor())

    result = run_nnmf(stack, wavenumbers, PARAMS, spectral_unit=unit, label=LABEL)
    print(result.summary())

    result.save(RESULT_DIR, basename=LABEL)

    # full-size composite window + a pixel-exact RGB export (one pixel per pixel)
    composite = plot_composite(result, title=f"{LABEL}: composite", **COMPOSITE)
    composite.savefig(RESULT_DIR / f"{LABEL}_composite.png", dpi=200,
                      facecolor=composite.get_facecolor())
    save_composite_image(result, RESULT_DIR / f"{LABEL}_composite_rgb.png", **COMPOSITE)

    # show=True displays the ROI overview and composite with the W/H figures
    save_figures(result, RESULT_DIR, basename=LABEL, show=True)
    print(f"results in {RESULT_DIR}")

if __name__ == "__main__":
    main()