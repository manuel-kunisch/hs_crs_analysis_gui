"""binlets denoising for a 4D multi-channel z-stack (experimental).

Input layout is the ImageJ hyperstack convention, ZCYX: z slices, detection
channels, then the two image axes.

Each z slice is treated exactly like a 3D hyperspectral stack: the channel axis
is never binned but carries the evidence for every merge decision, and only Y
and X are binned. Slices are processed independently, so no signal is ever mixed
across depth. One noise model is fitted on the whole volume and used for all
slices, so the decision threshold is identical everywhere.

The output keeps the input shape and dtype and is written as an ImageJ
hyperstack, so it opens with the channels and slices intact.

Needs `pip install binlets`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import tifffile

from hs_nnmf import (
    binlets_denoise,
    configure_logging,
    data_path,
    estimate_noise_model,
    plot_denoise_check,
)


def main():
    # ------------------------------------------------------------- SETTINGS --
    DATA = data_path("fov_03_original.tif")
    RESULT_DIR = Path(__file__).resolve().parent / "results" / "binlets_4d"
    LABEL = "fov_03"

    AXES = "ZCYX"        # input axis order; "CZYX" is also accepted

    GAIN = None          # None -> fitted from the data
    OFFSET = None

    BINLETS = dict(
        n_sigma=3.0,          # with few channels the pooled test is weaker than
        levels=3,             # for a hyperspectral stack, so start lower
        joint_channels=True,
    )

    CHECK_SLICE = 25     # z slice shown in the QC panel
    CHECK_CHANNEL = 1    # channel shown in the QC panel
    CHECK_PIXEL = None   # (y, x); None picks the brightest pixel of that slice
    # -------------------------------------------------------------------------

    configure_logging("INFO")
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    raw = tifffile.imread(str(DATA))
    if raw.ndim != 4:
        raise ValueError(f"Expected a 4D stack, got shape {raw.shape}.")
    axes = AXES.upper()
    if sorted(axes) != sorted("ZCYX"):
        raise ValueError(f"AXES must be a permutation of ZCYX, got {AXES!r}.")
    print(f"loaded {DATA.name}: {raw.shape} {raw.dtype} as {axes}")

    # -> (C, Z, Y, X) so that axis 0 is the channel axis binlets keeps
    czyx = np.moveaxis(raw, [axes.index(a) for a in "CZYX"], [0, 1, 2, 3])
    n_channels, n_z = czyx.shape[0], czyx.shape[1]
    print(f"{n_channels} channels, {n_z} z slices, {czyx.shape[2]}x{czyx.shape[3]} px")

    model = estimate_noise_model(czyx)
    gain = model.gain if GAIN is None else GAIN
    offset = model.offset if OFFSET is None else OFFSET
    print(f"noise model: {model}")

    # one call per z slice: (C, Y, X) in, only Y and X are binned
    denoised = np.empty_like(czyx)
    for z in range(n_z):
        denoised[:, z] = binlets_denoise(czyx[:, z], gain=gain, offset=offset, **BINLETS)
        if (z + 1) % 10 == 0 or z == n_z - 1:
            print(f"  slice {z+1}/{n_z}")

    # back to the input layout and out as an ImageJ hyperstack
    out = np.moveaxis(denoised, [0, 1, 2, 3], [axes.index(a) for a in "CZYX"])
    out_path = RESULT_DIR / f"{LABEL}_denoised.tif"
    tifffile.imwrite(
        str(out_path),
        np.moveaxis(out, [axes.index(a) for a in "ZCYX"], [0, 1, 2, 3]),
        imagej=True, metadata={"axes": "ZCYX"},
    )
    print(f"denoised stack -> {out_path.name}  {out.shape} {out.dtype}")

    def spatial_noise(a):
        d = a[..., :-2] - 2 * a[..., 1:-1] + a[..., 2:]
        return float(np.median(np.abs(d)) / 0.6745 / np.sqrt(6))

    raw_f, den_f = czyx.astype(float), denoised.astype(float)
    print(f"spatial noise {spatial_noise(raw_f):.1f} -> {spatial_noise(den_f):.1f} "
          f"({100*(1-spatial_noise(den_f)/spatial_noise(raw_f)):.1f}% lower)")
    print(f"mean {raw_f.mean():.2f} -> {den_f.mean():.2f}")

    # QC on one slice: channels take the role the bands have in the 3D check
    slice_raw = czyx[:, CHECK_SLICE]
    slice_den = denoised[:, CHECK_SLICE]
    pixel = CHECK_PIXEL
    if pixel is None:
        flat_index = int(np.argmax(slice_raw[CHECK_CHANNEL]))
        pixel = (flat_index // slice_raw.shape[-1], flat_index % slice_raw.shape[-1])
    figure = plot_denoise_check(
        slice_raw, slice_den, band=CHECK_CHANNEL, pixel=pixel,
        title=f"{LABEL}: z={CHECK_SLICE}, channel {CHECK_CHANNEL} "
              f"(n_sigma={BINLETS['n_sigma']}, per-slice)",
    )
    figure.savefig(RESULT_DIR / f"{LABEL}_denoise_check.png", dpi=200,
                   facecolor=figure.get_facecolor())
    print(f"results in {RESULT_DIR}")

    from matplotlib import pyplot as plt
    plt.show()


if __name__ == "__main__":
    main()
