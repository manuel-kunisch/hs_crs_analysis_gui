"""Generate a synthetic overlap dataset for testing the Purify seed feature.

The scene mimics the lipid/nucleus situation in cells: cytoplasm blobs
(lipid-like spectrum) have large pure regions, while every nucleus blob
(nucleus-like spectrum) sits fully inside a cytoplasm blob and is therefore
always measured on top of lipid. No pure nucleus pixel exists anywhere in the
image, so any ROI drawn on a nucleus yields a mixed spectrum.

This is exactly the case the ROI Manager's Purify seed dialog is built for:
draw one ROI on cytoplasm only (pure lipid seed), one ROI on a nucleus (mixed
seed), then purify the nucleus seed against the lipid reference. The lipid
spectrum has its main peak at 2850 cm^-1 where the nucleus-like spectrum is
essentially dark, so the extrapolation to the non-negativity boundary lands on
the true nucleus spectrum. The written CSV contains the ground-truth spectra
for comparison.

The lipid amount covering each nucleus varies from cell to cell, so the mixed
nucleus spectra are not all the same mixture.
"""

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import tifffile


def gaussian(axis: np.ndarray, center: float, width: float) -> np.ndarray:
    return np.exp(-0.5 * ((axis - center) / width) ** 2)


def normalize(arr: np.ndarray) -> np.ndarray:
    peak = float(np.max(arr))
    return arr / peak if peak > 0 else arr


def blob(yy: np.ndarray, xx: np.ndarray, cy: float, cx: float, sy: float, sx: float) -> np.ndarray:
    return np.exp(-(((xx - cx) / sx) ** 2 + ((yy - cy) / sy) ** 2))


def build_dataset(
    *,
    seed: int = 7,
    cells: int = 6,
    noise: float = 280.0,
    background_strength: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray], dict[str, np.ndarray]]:
    channels = 32
    height = 160
    width = 200
    axis = np.linspace(2750.0, 3050.0, channels)
    rng = np.random.default_rng(seed)

    yy, xx = np.mgrid[0:height, 0:width]

    cytoplasm_map = np.zeros((height, width), dtype=np.float64)
    nucleus_map = np.zeros((height, width), dtype=np.float64)
    margin = 26.0
    for _ in range(max(0, int(cells))):
        cx = rng.uniform(margin, width - margin)
        cy = rng.uniform(margin, height - margin)
        cell_sx = rng.uniform(14.0, 20.0)
        cell_sy = rng.uniform(12.0, 18.0)
        # Wide amplitude ranges so the lipid fraction covering each nucleus
        # differs clearly from cell to cell.
        cell_amp = rng.uniform(0.5, 1.0)
        cytoplasm_map += cell_amp * blob(yy, xx, cy, cx, cell_sy, cell_sx)

        # The nucleus sits well inside its cell (small center offset, less than
        # half the cell radius), so its support is always covered by cytoplasm.
        ncx = cx + rng.uniform(-0.3, 0.3) * cell_sx
        ncy = cy + rng.uniform(-0.3, 0.3) * cell_sy
        nucleus_amp = rng.uniform(0.55, 1.0)
        nucleus_map += nucleus_amp * blob(yy, xx, ncy, ncx, 0.38 * cell_sy, 0.38 * cell_sx)

    cytoplasm_map = normalize(cytoplasm_map)
    nucleus_map = normalize(nucleus_map)
    background_map = normalize(0.35 + 0.45 * (xx / (width - 1)) + 0.20 * (yy / (height - 1)))

    # The lipid-like spectrum peaks at 2850 cm^-1 where the nucleus-like
    # spectrum is essentially zero. That reference-free channel is what makes
    # the mixed nucleus seed purifiable by subtraction.
    spectra: dict[str, np.ndarray] = {
        "lipid_like": normalize(1.0 * gaussian(axis, 2850.0, 16.0) + 0.25 * gaussian(axis, 2885.0, 28.0)),
        "nucleus_like": normalize(1.0 * gaussian(axis, 2930.0, 18.0) + 0.30 * gaussian(axis, 2965.0, 22.0)),
    }
    if background_strength > 0:
        spectra["broad_background"] = normalize(0.35 + 0.65 * gaussian(axis, 2890.0, 95.0))

    stack = (
        spectra["lipid_like"][:, None, None] * cytoplasm_map[None, :, :] * 34000.0
        + spectra["nucleus_like"][:, None, None] * nucleus_map[None, :, :] * 30000.0
    )
    if background_strength > 0:
        stack += spectra["broad_background"][:, None, None] * background_map[None, :, :] * float(background_strength)

    stack += rng.normal(loc=0.0, scale=float(noise), size=stack.shape)
    stack = np.clip(stack, 0.0, 65535.0).astype(np.uint16)

    maps = {"cytoplasm": cytoplasm_map, "nucleus": nucleus_map, "background": background_map}
    return stack, axis, spectra, maps


def write_outputs(
    output_dir: Path,
    *,
    seed: int,
    cells: int,
    noise: float,
    background_strength: float,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stack, axis, spectra, _ = build_dataset(
        seed=seed,
        cells=cells,
        noise=noise,
        background_strength=background_strength,
    )

    tifffile.imwrite(output_dir / "purify_overlap_stack.tif", stack)

    metadata = {
        "spectral_unit": "cm^-1",
        "custom_values": [round(float(value), 6) for value in axis],
    }
    (output_dir / "wavelength.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    with (output_dir / "ground_truth_spectra.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["wavenumber", *spectra.keys()])
        for index, value in enumerate(axis):
            writer.writerow([round(float(value), 6), *[round(float(spec[index]), 8) for spec in spectra.values()]])

    readme = f"""Purify seed overlap test data
- seed: {seed}
- cells: {cells}
- noise: {noise}
- background_strength: {background_strength}

Scene:
- lipid_like: {cells} cytoplasm blobs with a peak near 2850 cm^-1. Their outer
  regions contain pure lipid pixels.
- nucleus_like: one nucleus per cell, main peak near 2930 cm^-1 and essentially
  dark at 2850 cm^-1. Every nucleus lies inside a cytoplasm blob, so there is
  no pure nucleus pixel anywhere in the image. The lipid fraction on top of
  each nucleus varies from cell to cell.

Suggested test of the Purify seed feature:
1. Load purify_overlap_stack.tif (wavelength.json is picked up automatically).
2. Draw ROI 1 on a cytoplasm region without a nucleus -> pure lipid seed
   (Component 1).
3. Draw ROI 2 on a nucleus -> mixed seed (Component 2). The separability line
   under the ROI table should show a poor eta for this pair.
4. Click "Purify seed...", target = the nucleus row, reference = the lipid
   row. The eta line in the dialog should improve clearly on apply.
5. Compare the purified spectrum with nucleus_like in ground_truth_spectra.csv
   (Load Spectrum from File shows it as a dummy row for visual comparison).
"""
    (output_dir / "README.txt").write_text(readme, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="purify_overlap_data", help="Output directory.")
    parser.add_argument("--seed", type=int, default=7, help="Random seed for cell placement and noise.")
    parser.add_argument("--cells", type=int, default=6, help="Number of cells (each with one nucleus).")
    parser.add_argument("--noise", type=float, default=280.0, help="Gaussian noise standard deviation.")
    parser.add_argument(
        "--background-strength",
        type=float,
        default=0.0,
        help="Amplitude of an optional broad background component (0 disables it).",
    )
    args = parser.parse_args()
    output_dir = Path(args.output).resolve()
    write_outputs(
        output_dir,
        seed=args.seed,
        cells=args.cells,
        noise=args.noise,
        background_strength=args.background_strength,
    )
    print(f"Wrote purify overlap test data to: {output_dir}")


if __name__ == "__main__":
    main()
