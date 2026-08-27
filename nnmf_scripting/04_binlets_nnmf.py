"""NNMF on binlets-denoised data (experimental).

binlets bins the image adaptively: neighbouring pixels are merged only while a
statistical test says they are consistent, so flat areas get large bins while
droplets and edges keep full resolution. The spectral axis is never binned --
it is used as *evidence* for each spatial merge decision (joint_channels=True).

Needs `pip install binlets`.

Edit the SETTINGS block and run the file. Figures are saved and shown.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tifffile

from hs_nnmf import (
    DEFAULT_PALETTE,
    NNMFParams,
    Roi,
    binlets_denoise,
    configure_logging,
    data_path,
    estimate_noise_model,
    load_dataset,
    plot_composite,
    plot_denoise_check,
    run_nnmf,
    save_composite_image,
    save_figures,
)


def main():
    # ------------------------------------------------------------- SETTINGS --
    DATA = data_path("2017_03_23_Lungcells_Day2_60mWBoth_2xZoom_16ms_Pos2_HS_CARS_ch-1_C.tif")
    RESULT_DIR = Path(__file__).resolve().parent / "results" / "binlets"
    LABEL = "binlets"
    PALETTE = DEFAULT_PALETTE  # or: high_contrast | okabe_ito | classic_rgb

    # Detector noise model, var = gain * mean + offset.
    #   None  -> fitted from the data (photon-transfer curve)
    #   gain  -> ADU per effective photoelectron, i.e. with the PMT
    #            excess-noise factor already folded in
    #   offset-> read/dark/digitisation variance floor, in counts squared
    # A current-mode PMT can carry a substantial offset, and it accumulates
    # with the bin size, so it is fitted rather than assumed. It is not always
    # present: of our four stacks only one fits a non-zero offset.
    GAIN = None
    OFFSET = None

    # n_sigma is how far into the tail of the chi-square null a merge is still
    # accepted. Measured on this dataset (spatial noise / lipid-droplet contrast
    # vs the raw stack):
    #      3.0 -> noise -25%,  contrast -0.3%
    #      5.0 -> noise -65%,  contrast -0.5%    <- good default here
    #      8.0 -> noise -92%,  contrast -1.1%
    # It is dataset-dependent: a low-contrast stack needs a lower n_sigma (the
    # day-1 lung-cell field is well denoised at 3.0), and it also depends on the
    # number of channels, since the null is relatively wider for few channels.
    # Judge it on the residual panel, but read it correctly: for shot-noise
    # limited data the residual amplitude is meant to follow the brightness,
    # because the variance does. Only a sign-coherent residual, outlines that
    # are consistently one colour, means signal is being removed.
    BINLETS = dict(
        n_sigma=5.0,          # merge threshold; larger bins harder, blurs more
        levels=3,             # max bin size 2**levels = 8x8 px
        joint_channels=True,  # one merge decision per pixel, pooled over all bands
    )

    # Same ROI seeds as 02, so the effect of denoising is the only difference.
    ROIS = [
        Roi.from_center(0, y=348, x=150, size=9, name="lipid droplets (lower left)"),
        Roi.from_center(0, y=195, x=307, size=9, name="lipid droplets (upper right)"),
        Roi.from_center(1, y=168, x=372, size=15, name="nucleus (upper right)"),
        Roi.from_center(1, y=240, x=352, size=15, name="nucleus (centre right)"),
        Roi.from_center(1, y=370, x=442, size=15, name="nucleus (lower right)"),
        Roi(component=2, rect=(15, 20, 30, 40), name="NRB (top left)", is_background=True),
    ]

    PARAMS = NNMFParams(
        n_components=3,
        init="custom",
        rois=ROIS,
        w_seed_mode="nnls",
        w_seed_downsample=4,
        normalize_h_to_unity=True,
        solver="mu",
        backend="gpu",
        max_iter=500,
        tol=1e-4,
        patience=3,
    )

    COMPOSITE = dict(
        palette=PALETTE, mode="additive", gamma=1.0,
        low_percentile=(0, 0, 70),
    )
    # QC panel: which band and pixel to show raw vs denoised
    CHECK_BAND = 42          # 2850 cm-1, the CH2 lipid band
    CHECK_PIXEL = (348, 150) # a lipid droplet
    # -------------------------------------------------------------------------

    configure_logging("INFO")
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    stack, wavenumbers, unit = load_dataset(DATA)
    print(f"stack {stack.shape} {stack.dtype}   axis {wavenumbers.max():.1f} ... {wavenumbers.min():.1f} {unit}")

    # --- noise model ---------------------------------------------------------
    if GAIN is None or OFFSET is None:
        model = estimate_noise_model(stack)
        gain = model.gain if GAIN is None else GAIN
        offset = model.offset if OFFSET is None else OFFSET
        print(f"fitted noise model: {model}")
    else:
        gain, offset = GAIN, OFFSET
    print(f"using gain={gain:.3f}, offset={offset:.4g}")

    # --- denoise -------------------------------------------------------------
    denoised = binlets_denoise(stack, gain=gain, offset=offset, **BINLETS)

    # same shape/dtype as the input, so it drops straight into FIJI or back
    # into HS-MOSAIC as an ordinary hyperspectral stack
    denoised_tif = RESULT_DIR / f"{LABEL}_denoised.tif"
    tifffile.imwrite(str(denoised_tif), denoised)
    print(f"denoised stack -> {denoised_tif.name}  {denoised.shape} {denoised.dtype}")

    check = plot_denoise_check(
        stack, denoised, band=CHECK_BAND, pixel=CHECK_PIXEL,
        wavenumbers=wavenumbers, spectral_unit=unit,
        title=f"{LABEL}: denoising check (n_sigma={BINLETS['n_sigma']}, levels={BINLETS['levels']})",
    )
    check.savefig(RESULT_DIR / f"{LABEL}_denoise_check.png", dpi=200,
                  facecolor=check.get_facecolor())

    # --- NNMF on the denoised stack -----------------------------------------
    result = run_nnmf(denoised, wavenumbers, PARAMS, spectral_unit=unit, label=LABEL)
    print(result.summary())

    result.save(RESULT_DIR, basename=LABEL)

    composite = plot_composite(result, title=f"{LABEL}: composite", **COMPOSITE)
    composite.savefig(RESULT_DIR / f"{LABEL}_composite.png", dpi=200,
                      facecolor=composite.get_facecolor())
    save_composite_image(result, RESULT_DIR / f"{LABEL}_composite_rgb.png", **COMPOSITE)

    save_figures(result, RESULT_DIR, basename=LABEL, palette=PALETTE, show=True)
    print(f"results in {RESULT_DIR}")


if __name__ == "__main__":
    main()
