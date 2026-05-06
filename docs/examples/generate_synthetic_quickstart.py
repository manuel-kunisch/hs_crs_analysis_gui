"""Generate a small synthetic hyperspectral dataset for the documentation."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import tifffile


def gaussian(axis: np.ndarray, center: float, width: float) -> np.ndarray:
    return np.exp(-0.5 * ((axis - center) / width) ** 2)


def normalize(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float64)
    max_value = float(np.max(arr))
    if max_value <= 0:
        return arr
    return arr / max_value


def build_dataset() -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    channels = 32
    height = 96
    width = 128
    axis = np.linspace(2750.0, 3050.0, channels)

    yy, xx = np.mgrid[0:height, 0:width]

    lipid_map = np.exp(-(((xx - 38.0) / 18.0) ** 2 + ((yy - 48.0) / 23.0) ** 2))
    protein_map = np.exp(-(((xx - 86.0) / 24.0) ** 2 + ((yy - 50.0) / 15.0) ** 2))
    mutated_lipid_map = np.exp(-(((xx - 92.0) / 7.0) ** 2 + ((yy - 28.0) / 7.0) ** 2))
    background_map = normalize(0.35 + 0.45 * (xx / (width - 1)) + 0.20 * (yy / (height - 1)))

    spectra = {
        "lipid_like": normalize(1.0 * gaussian(axis, 2850.0, 16.0) + 0.25 * gaussian(axis, 2885.0, 28.0)),
        "mutated_lipid_like": normalize(
            1.0 * gaussian(axis, 2850.0, 16.0)
            + 0.18 * gaussian(axis, 2885.0, 28.0)
            + 0.55 * gaussian(axis, 3010.0, 30.0)
        ),
        "protein_like": normalize(
            0.42 * gaussian(axis, 2850.0, 18.0)
            + 1.0 * gaussian(axis, 2930.0, 18.0)
            + 0.35 * gaussian(axis, 2965.0, 24.0)
        ),
        "broad_background": normalize(0.35 + 0.65 * gaussian(axis, 2890.0, 95.0)),
    }

    stack = (
        spectra["lipid_like"][:, None, None] * lipid_map[None, :, :] * 42000.0
        + spectra["mutated_lipid_like"][:, None, None] * mutated_lipid_map[None, :, :] * 34000.0
        + spectra["protein_like"][:, None, None] * protein_map[None, :, :] * 36000.0
        + spectra["broad_background"][:, None, None] * background_map[None, :, :] * 9000.0
    )

    rng = np.random.default_rng(7)
    stack += rng.normal(loc=0.0, scale=280.0, size=stack.shape)
    stack = np.clip(stack, 0.0, 65535.0).astype(np.uint16)
    return stack, axis, spectra


def write_outputs(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stack, axis, spectra = build_dataset()

    tifffile.imwrite(output_dir / "synthetic_hs_stack.tif", stack)

    metadata = {
        "spectral_unit": "cm^-1",
        "custom_values": [round(float(value), 6) for value in axis],
    }
    (output_dir / "wavelength.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    with (output_dir / "synthetic_reference_spectra.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["wavenumber", *spectra.keys()])
        for index, value in enumerate(axis):
            writer.writerow([round(float(value), 6), *[round(float(spec[index]), 8) for spec in spectra.values()]])

    readme = """Synthetic quickstart data

Files:
- synthetic_hs_stack.tif: 3D hyperspectral stack, shape (channel, y, x)
- wavelength.json: spectral axis metadata
- synthetic_reference_spectra.csv: three reference spectra for the ROI Manager

Expected components:
- lipid_like: left rounded region, peak near 2850 cm^-1
- mutated_lipid_like: small bright spot with the same 2850 cm^-1 peak but a different high-wavenumber tail
- protein_like: right elliptical region, main peak near 2930 cm^-1 and weaker overlap near 2850 cm^-1
- broad_background: smooth background gradient
"""
    (output_dir / "README.txt").write_text(readme, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="synthetic_quickstart_data", help="Output directory.")
    args = parser.parse_args()
    output_dir = Path(args.output).resolve()
    write_outputs(output_dir)
    print(f"Wrote synthetic quickstart data to: {output_dir}")


if __name__ == "__main__":
    main()
