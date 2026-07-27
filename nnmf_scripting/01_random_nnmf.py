"""NNMF with random initialization -- no seeds at all.

Edit the SETTINGS block and run the file (IDE run button or `python 01_random_nnmf.py`).
Figures are saved to RESULT_DIR and shown on screen.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hs_nnmf import (
    NNMFParams,
    configure_logging,
    data_path,
    load_dataset,
    plot_composite,
    run_nnmf,
    save_composite_image,
    save_figures,
)

def main():
    # ----------------------------------------------------------------- SETTINGS --
    DATA = data_path("2017_03_23_Lungcells_Day2_60mWBoth_2xZoom_16ms_Pos2_HS_CARS_ch-1_C.tif")
    RESULT_DIR = Path(__file__).resolve().parent / "results" / "random"
    LABEL = "random"

    PARAMS = NNMFParams(
        n_components=3,
        init="random",        # random init: no H/W seeds are built at all
        solver="mu",          # 'mu' or 'cd'
        backend="gpu",        # 'gpu' = torch (falls back to CPU), 'cpu' = scikit-learn
        max_iter=500,
        tol=1e-4,
        patience=3,
    )

    # False-color composite: true additive RGB (what FIJI and the GUI's composite
    # view do)
    COMPOSITE = dict(mode="additive", gamma=1.0, low_percentile=0.0)
    # ------------------------------------------------------------------------------

    configure_logging("INFO")

    stack, wavenumbers, unit = load_dataset(DATA)
    print(f"stack {stack.shape} {stack.dtype}   axis {wavenumbers.max():.1f} ... {wavenumbers.min():.1f} {unit}")

    result = run_nnmf(stack, wavenumbers, PARAMS, spectral_unit=unit, label=LABEL)
    print(result.summary())

    result.save(RESULT_DIR, basename=LABEL)

    # full-size composite window + a pixel-exact RGB export (one pixel per pixel)
    composite = plot_composite(result, title=f"{LABEL}: composite", **COMPOSITE)
    composite.savefig(RESULT_DIR / f"{LABEL}_composite.png", dpi=200,
                      facecolor=composite.get_facecolor())
    save_composite_image(result, RESULT_DIR / f"{LABEL}_composite_rgb.png", **COMPOSITE)

    save_figures(result, RESULT_DIR, basename=LABEL, show=True)
    print(f"results in {RESULT_DIR}")


if __name__ == "__main__":
    main()