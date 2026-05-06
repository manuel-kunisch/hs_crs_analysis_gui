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


def bead_map(
    yy: np.ndarray,
    xx: np.ndarray,
    rng: np.random.Generator,
    count: int,
    *,
    radius_range: tuple[float, float] = (4.0, 8.0),
    margin: float = 12.0,
) -> np.ndarray:
    height, width = yy.shape
    out = np.zeros_like(xx, dtype=np.float64)
    for _ in range(max(0, int(count))):
        cx = rng.uniform(margin, width - margin)
        cy = rng.uniform(margin, height - margin)
        sx = rng.uniform(*radius_range)
        sy = rng.uniform(*radius_range)
        amp = rng.uniform(0.65, 1.0)
        out += amp * np.exp(-(((xx - cx) / sx) ** 2 + ((yy - cy) / sy) ** 2))
    return normalize(out)


def mutant_spectrum(axis: np.ndarray, variant_index: int, variant_count: int) -> np.ndarray:
    if variant_count <= 1:
        tail_center = 3010.0
        tail_strength = 0.55
    else:
        fraction = variant_index / max(1, variant_count - 1)
        tail_center = 2985.0 + 50.0 * fraction
        tail_strength = 0.35 + 0.35 * fraction
    return normalize(
        1.0 * gaussian(axis, 2850.0, 16.0)
        + 0.18 * gaussian(axis, 2885.0, 28.0)
        + tail_strength * gaussian(axis, tail_center, 30.0)
    )


def build_dataset(
    *,
    seed: int = 7,
    beads_per_class: int = 8,
    mutant_variants: int = 3,
    mutant_beads_per_variant: int = 4,
    noise: float = 280.0,
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    channels = 32
    height = 120
    width = 160
    axis = np.linspace(2750.0, 3050.0, channels)
    rng = np.random.default_rng(seed)

    yy, xx = np.mgrid[0:height, 0:width]

    lipid_map = bead_map(yy, xx, rng, beads_per_class, radius_range=(5.0, 9.0))
    protein_map = bead_map(yy, xx, rng, beads_per_class, radius_range=(5.0, 10.0))
    mutant_maps = [
        bead_map(yy, xx, rng, mutant_beads_per_variant, radius_range=(3.2, 5.5))
        for _ in range(max(0, int(mutant_variants)))
    ]
    background_map = normalize(0.35 + 0.45 * (xx / (width - 1)) + 0.20 * (yy / (height - 1)))

    spectra: dict[str, np.ndarray] = {
        "lipid_like": normalize(1.0 * gaussian(axis, 2850.0, 16.0) + 0.25 * gaussian(axis, 2885.0, 28.0)),
    }
    for index in range(len(mutant_maps)):
        spectra[f"mutated_lipid_like_{index + 1}"] = mutant_spectrum(axis, index, len(mutant_maps))
    spectra.update({
        "protein_like": normalize(
            0.42 * gaussian(axis, 2850.0, 18.0)
            + 1.0 * gaussian(axis, 2930.0, 18.0)
            + 0.35 * gaussian(axis, 2965.0, 24.0)
        ),
        "broad_background": normalize(0.35 + 0.65 * gaussian(axis, 2890.0, 95.0)),
    })

    stack = (
        spectra["lipid_like"][:, None, None] * lipid_map[None, :, :] * 34000.0
        + spectra["protein_like"][:, None, None] * protein_map[None, :, :] * 32000.0
        + spectra["broad_background"][:, None, None] * background_map[None, :, :] * 7500.0
    )
    for index, mutant_map in enumerate(mutant_maps):
        name = f"mutated_lipid_like_{index + 1}"
        stack += spectra[name][:, None, None] * mutant_map[None, :, :] * 30000.0

    stack += rng.normal(loc=0.0, scale=float(noise), size=stack.shape)
    stack = np.clip(stack, 0.0, 65535.0).astype(np.uint16)
    return stack, axis, spectra


def write_outputs(
    output_dir: Path,
    *,
    seed: int,
    beads_per_class: int,
    mutant_variants: int,
    mutant_beads_per_variant: int,
    noise: float,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stack, axis, spectra = build_dataset(
        seed=seed,
        beads_per_class=beads_per_class,
        mutant_variants=mutant_variants,
        mutant_beads_per_variant=mutant_beads_per_variant,
        noise=noise,
    )

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

    mutant_lines = "\n".join(
        f"- mutated_lipid_like_{index + 1}: {mutant_beads_per_variant} small beads with the same 2850 cm^-1 peak and a variant-specific tail"
        for index in range(max(0, int(mutant_variants)))
    )
    readme = f"""Synthetic quickstart data

Files:
- synthetic_hs_stack.tif: 3D hyperspectral stack, shape (channel, y, x)
- wavelength.json: spectral axis metadata
- synthetic_reference_spectra.csv: one reference spectrum per synthetic component

Generator settings:
- seed: {seed}
- beads_per_class: {beads_per_class}
- mutant_variants: {mutant_variants}
- mutant_beads_per_variant: {mutant_beads_per_variant}
- noise: {noise}

Expected components:
- lipid_like: {beads_per_class} beads with a peak near 2850 cm^-1
{mutant_lines}
- protein_like: {beads_per_class} beads with a main peak near 2930 cm^-1 and weaker overlap near 2850 cm^-1
- broad_background: smooth background gradient
"""
    (output_dir / "README.txt").write_text(readme, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="synthetic_quickstart_data", help="Output directory.")
    parser.add_argument("--seed", type=int, default=7, help="Random seed for bead placement and noise.")
    parser.add_argument("--beads-per-class", type=int, default=12, help="Number of ordinary lipid/protein beads.")
    parser.add_argument("--mutant-variants", type=int, default=2, help="Number of mutated lipid-like spectral variants.")
    parser.add_argument(
        "--mutant-beads-per-variant",
        type=int,
        default=4,
        help="Number of beads for each mutated lipid-like variant.",
    )
    parser.add_argument("--noise", type=float, default=280.0, help="Gaussian noise standard deviation.")
    args = parser.parse_args()
    output_dir = Path(args.output).resolve()
    write_outputs(
        output_dir,
        seed=args.seed,
        beads_per_class=args.beads_per_class,
        mutant_variants=args.mutant_variants,
        mutant_beads_per_variant=args.mutant_beads_per_variant,
        noise=args.noise,
    )
    print(f"Wrote synthetic quickstart data to: {output_dir}")


if __name__ == "__main__":
    main()
