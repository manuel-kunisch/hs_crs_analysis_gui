"""
Figures for a scripted NNMF run: W component maps, composite, H components.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, to_rgb
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

from hs_mosaic.widgets.color_manager import (
    DEFAULT_PALETTE as GUI_DEFAULT_PALETTE,
    PALETTES as GUI_PALETTES,
)

from .config import Roi
from .runner import NNMFResult

logger = logging.getLogger(__name__)

# Use the GUI registry as the single source of truth. Tuple values keep the
# scripting presets read-only while preserving the GUI's names and order.
PALETTES = {name: tuple(colors) for name, colors in GUI_PALETTES.items()}
DEFAULT_PALETTE = GUI_DEFAULT_PALETTE
DEFAULT_COLORS = PALETTES[DEFAULT_PALETTE]
CLASSIC_COLORS = PALETTES["classic_rgb"]

INK = "#0b0b0b"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"


def component_colors(
    n: int,
    colors: Sequence[str] | None = None,
    *,
    palette: str | None = None,
) -> list[str]:
    """Resolve component colors from an explicit sequence or a GUI palette.

    With neither argument, this uses the GUI's current fresh-session default.
    """
    if colors is not None and palette is not None:
        raise ValueError("Pass either `colors=` or `palette=`, not both.")
    if palette is not None:
        try:
            resolved = list(PALETTES[palette])
        except KeyError as exc:
            raise ValueError(
                f"Unknown palette {palette!r}; available: {sorted(PALETTES)}"
            ) from exc
    else:
        resolved = list(colors) if colors is not None else list(DEFAULT_COLORS)
    if n > len(resolved):
        raise ValueError(
            f"{n} components need {n} colors but only {len(resolved)} are defined. "
            "Pass an explicit `colors=` sequence rather than cycling hues."
        )
    return resolved[:n]


def single_hue_cmap(color: str) -> LinearSegmentedColormap:
    """Black -> ``color`` sequential ramp, matching the GUI channel LUT."""
    return LinearSegmentedColormap.from_list(f"hs_{color}", ["#000000", color])


def _normalize_map(image: np.ndarray, percentile: float, low_percentile: float = 0.0) -> np.ndarray:
    """Scale one map to [0, 1] between two percentile levels (FIJI's vmin/vmax)."""
    image = np.nan_to_num(np.asarray(image, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    image = np.maximum(image, 0.0)
    if image.size == 0:
        return image
    bottom = float(np.percentile(image, low_percentile)) if low_percentile > 0 else 0.0
    top = float(np.percentile(image, percentile))
    if top <= bottom:
        top = float(image.max())
    if top <= bottom:
        return np.zeros_like(image)
    return np.clip((image - bottom) / (top - bottom), 0.0, 1.0)


def _channel_color(color: str) -> np.ndarray:
    """Exact RGB channel color used by the GUI's black -> color LUT."""
    return np.asarray(to_rgb(color), dtype=np.float64)


def _per_component(value, n: int, name: str) -> list[float]:
    """Accept either one value for all components or one value per component."""
    if np.isscalar(value):
        return [float(value)] * n
    values = [float(v) for v in value]
    if len(values) != n:
        raise ValueError(f"{name} has {len(values)} entries but there are {n} components.")
    return values


def composite_rgb(
    maps: np.ndarray,
    colors: Sequence[str] | None = None,
    percentile: float | Sequence[float] = 99.5,
    *,
    palette: str | None = None,
    mode: str = "additive",
    low_percentile: float | Sequence[float] = 0.0,
    gamma: float | Sequence[float] = 1.0,
) -> np.ndarray:
    """Blend component maps into one true RGB image (no alpha compositing).

    ``mode="additive"`` (default) is what HS-MOSAIC's composite view and FIJI do:
    each map is normalized between its levels, mapped through a black -> color
    LUT and *summed*, so the background is black and overlapping components
    brighten toward white. This is the look you get from the pyqtgraph composite.

    ``mode="multiply"`` is the subtractive alternative on a white ground: each
    component absorbs light in its own hue, so overlaps darken. It prints
    better but looks washed out on screen.

    ``gamma`` < 1 lifts dim structures (0.7-0.8 is a good display gamma for CARS
    abundance maps); 1.0 leaves the data linear.

    ``percentile``, ``low_percentile`` and ``gamma`` each take either one value
    for every component or one value per component -- the scripting equivalent
    of the per-channel histogram levels in the GUI. A component that covers the
    whole field (the non-resonant background, typically) washes the composite
    out unless its black level is raised, e.g.
    ``low_percentile=(0, 0, 55)`` for a 3-component fit.

    Returns a float RGB array in [0, 1] with shape ``(Y, X, 3)``.
    """
    maps = np.asarray(maps)
    n_components = maps.shape[0]
    component_palette = component_colors(n_components, colors, palette=palette)
    height, width = maps.shape[1], maps.shape[2]

    if mode not in {"additive", "multiply"}:
        raise ValueError(f"mode must be 'additive' or 'multiply', got {mode!r}.")

    highs = _per_component(percentile, n_components, "percentile")
    lows = _per_component(low_percentile, n_components, "low_percentile")
    gammas = _per_component(gamma, n_components, "gamma")

    rgb = np.zeros((height, width, 3), dtype=np.float64) if mode == "additive" \
        else np.ones((height, width, 3), dtype=np.float64)

    for index, (image, color) in enumerate(zip(maps, component_palette)):
        weight = _normalize_map(image, highs[index], lows[index])
        if gammas[index] != 1.0:
            weight = weight ** gammas[index]
        if mode == "additive":
            rgb += weight[..., None] * _channel_color(color)
        else:
            rgb *= 1.0 - weight[..., None] * (1.0 - np.asarray(to_rgb(color), dtype=np.float64))

    return np.clip(rgb, 0.0, 1.0)


def composite_rgb_uint8(maps: np.ndarray, **kwargs) -> np.ndarray:
    """:func:`composite_rgb` as an 8-bit ``(Y, X, 3)`` image."""
    return (composite_rgb(maps, **kwargs) * 255.0 + 0.5).astype(np.uint8)


def plot_component_maps(
    result: NNMFResult,
    *,
    colors: Sequence[str] | None = None,
    palette: str | None = None,
    percentile: float = 99.5,
    ncols: int = 2,
    show_composite: bool = True,
    composite_mode: str = "additive",
    composite_gamma: float = 1.0,
    title: str | None = None,
    use_seeds: bool = False,
) -> Figure:
    """Grid of W component maps (one sequential hue each) plus a composite panel."""
    maps = result.seed_W_2D if use_seeds else result.W_2D
    if maps is None:
        raise ValueError("No seed maps available for this result (random init has no seeds).")
    maps = np.asarray(maps)
    component_palette = component_colors(maps.shape[0], colors, palette=palette)

    n_panels = maps.shape[0] + (1 if show_composite else 0)
    ncols = max(1, int(ncols))
    nrows = int(np.ceil(n_panels / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.1 * ncols, 4.1 * nrows), squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    flat_axes = axes.ravel()

    for index, (image, color) in enumerate(zip(maps, component_palette)):
        ax = flat_axes[index]
        ax.imshow(_normalize_map(image, percentile), cmap=single_hue_cmap(color), vmin=0.0, vmax=1.0)
        kind = "W seed" if use_seeds else "W"
        ax.set_title(f"{kind} component {index}", color=INK, fontsize=11)
        _style_image_axes(ax)

    if show_composite:
        ax = flat_axes[maps.shape[0]]
        ax.imshow(
            composite_rgb(maps, component_palette, percentile=percentile,
                          mode=composite_mode, gamma=composite_gamma),
            interpolation="nearest",
        )
        ax.set_title("Composite image", color=INK, fontsize=11)
        _style_image_axes(ax)

    for ax in flat_axes[n_panels:]:
        ax.axis("off")

    if title:
        fig.suptitle(title, color=INK, fontsize=13)
    fig.tight_layout()
    return fig


def plot_composite(
    result: NNMFResult,
    *,
    colors: Sequence[str] | None = None,
    palette: str | None = None,
    percentile: float = 99.5,
    mode: str = "additive",
    gamma: float = 1.0,
    low_percentile: float = 0.0,
    title: str | None = None,
    use_seeds: bool = False,
    figsize: tuple[float, float] = (7.0, 6.8),
) -> Figure:
    """Full-size false-color composite of the W components, as a true RGB image.

    The array handed to ``imshow`` is already blended RGB -- no per-artist alpha
    is involved, so it renders exactly like the pyqtgraph composite.
    """
    maps = result.seed_W_2D if use_seeds else result.W_2D
    if maps is None:
        raise ValueError("No seed maps available for this result (random init has no seeds).")
    component_palette = component_colors(
        np.asarray(maps).shape[0], colors, palette=palette
    )
    rgb = composite_rgb(
        maps,
        component_palette,
        percentile,
        mode=mode,
        gamma=gamma,
        low_percentile=low_percentile,
    )

    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(SURFACE)
    ax.imshow(rgb, interpolation="nearest")
    ax.set_title(title or f"{result.label}: composite", color=INK, fontsize=12)
    _style_image_axes(ax)
    ax.legend(
        handles=[Line2D([], [], color=color, lw=3, label=f"W component {index}")
                 for index, color in enumerate(component_palette)],
        frameon=False, fontsize=9, labelcolor=INK,
        loc="upper center", bbox_to_anchor=(0.5, -0.09),
        ncol=min(len(component_palette), 4),
    )
    fig.tight_layout()
    return fig


def save_composite_image(
    result: NNMFResult,
    path: str | Path,
    *,
    colors: Sequence[str] | None = None,
    palette: str | None = None,
    percentile: float = 99.5,
    mode: str = "additive",
    gamma: float = 1.0,
    low_percentile: float = 0.0,
    use_seeds: bool = False,
) -> Path:
    """Write the composite as a pixel-exact RGB image (no axes, no resampling).

    One output pixel per data pixel -- the equivalent of exporting the composite
    straight out of the GUI viewer.
    """
    maps = result.seed_W_2D if use_seeds else result.W_2D
    if maps is None:
        raise ValueError("No seed maps available for this result.")
    rgb = composite_rgb_uint8(
        maps, colors=colors, palette=palette, percentile=percentile, mode=mode,
        gamma=gamma, low_percentile=low_percentile,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.imsave(path, rgb)
    logger.info("Wrote pixel-exact composite %s (%s x %s)", path.name, rgb.shape[1], rgb.shape[0])
    return path


def plot_denoise_check(
    raw: np.ndarray,
    denoised: np.ndarray,
    *,
    band: int | None = None,
    pixel: tuple[int, int] | None = None,
    wavenumbers: np.ndarray | None = None,
    spectral_unit: str = "cm-1",
    percentile: float = 99.5,
    title: str | None = None,
) -> Figure:
    """Before/after check for a denoising step.

    Top row: one band raw / denoised / residual. Bottom row: the spectrum at one
    pixel, raw vs denoised. The residual panel is the one that matters -- it
    should look like noise. Any visible structure in it is signal the denoiser
    ate.
    """
    raw = np.asarray(raw, dtype=np.float64)
    denoised = np.asarray(denoised, dtype=np.float64)
    if raw.shape != denoised.shape:
        raise ValueError(f"Shapes differ: {raw.shape} vs {denoised.shape}.")
    band = raw.shape[0] // 2 if band is None else int(band)
    pixel = (raw.shape[1] // 2, raw.shape[2] // 2) if pixel is None else pixel
    row, col = int(pixel[0]), int(pixel[1])

    fig = plt.figure(figsize=(12.5, 7.6))
    fig.patch.set_facecolor(SURFACE)
    grid = fig.add_gridspec(2, 3, height_ratios=[1.35, 1.0])

    residual = raw[band] - denoised[band]
    limit = float(np.percentile(np.abs(residual), 99)) or 1.0
    panels = [
        (raw[band], "raw", dict(cmap="gray_r", vmin=0.0, vmax=1.0)),
        (denoised[band], "binlets denoised", dict(cmap="gray_r", vmin=0.0, vmax=1.0)),
    ]
    for column, (image, label, kwargs) in enumerate(panels):
        ax = fig.add_subplot(grid[0, column])
        ax.imshow(_normalize_map(image, percentile), **kwargs)
        ax.set_title(label, color=INK, fontsize=11)
        _style_image_axes(ax)

    ax = fig.add_subplot(grid[0, 2])
    ax.imshow(residual, cmap="RdBu_r", vmin=-limit, vmax=limit)
    ax.set_title("residual (raw - denoised)", color=INK, fontsize=11)
    _style_image_axes(ax)

    ax = fig.add_subplot(grid[1, :])
    if wavenumbers is None:
        x = np.arange(raw.shape[0], dtype=float)
        xlabel = "band index"
    else:
        order = np.argsort(np.asarray(wavenumbers, dtype=float))
        x = np.asarray(wavenumbers, dtype=float)[order]
        raw, denoised = raw[order], denoised[order]
        unit = "cm$^{-1}$" if spectral_unit.lower() in {"cm-1", "cm⁻¹", "cm^-1"} else spectral_unit
        xlabel = f"spectral axis ({unit})"
    ax.plot(x, raw[:, row, col], color=INK_MUTED, linewidth=1.0, label="raw")
    ax.plot(x, denoised[:, row, col], color=DEFAULT_COLORS[0], linewidth=2.0, label="denoised")
    ax.set_xlabel(xlabel, color=INK_MUTED)
    ax.set_ylabel("counts", color=INK_MUTED)
    ax.set_title(f"spectrum at pixel (y={row}, x={col})", color=INK, fontsize=11)
    ax.tick_params(colors=INK_MUTED)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK)

    if title:
        fig.suptitle(title, color=INK, fontsize=13)
    fig.tight_layout()
    return fig


def _style_image_axes(ax) -> None:
    ax.set_xlabel("x dimension", color=INK_MUTED, fontsize=9)
    ax.set_ylabel("y dimension", color=INK_MUTED, fontsize=9)
    ax.tick_params(colors=INK_MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)


def plot_spectra(
    result: NNMFResult,
    *,
    colors: Sequence[str] | None = None,
    palette: str | None = None,
    show_seeds: bool = True,
    normalize: bool = True,
    title: str | None = None,
) -> Figure:
    """H components (solid) and, optionally, the H seeds they started from
    (dashed). Normalized to unit peak by default so shapes are comparable."""
    component_palette = component_colors(
        result.n_components, colors, palette=palette
    )
    order = np.argsort(np.asarray(result.wavenumbers, dtype=float))
    x = np.asarray(result.wavenumbers, dtype=float)[order]

    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for index, color in enumerate(component_palette):
        spectrum = np.asarray(result.H[index], dtype=float)[order]
        if normalize:
            peak = float(np.max(spectrum))
            spectrum = spectrum / peak if peak > 0 else spectrum
        ax.plot(x, spectrum, color=color, linewidth=2.0, label=f"H component {index}")
        if show_seeds and result.seed_H is not None:
            seed = np.asarray(result.seed_H[index], dtype=float)[order]
            if normalize:
                seed_peak = float(np.max(seed))
                seed = seed / seed_peak if seed_peak > 0 else seed
            ax.plot(x, seed, color=color, linewidth=1.0, linestyle="--", alpha=0.55)

    unit = "cm$^{-1}$" if result.spectral_unit.lower() in {"cm-1", "cm⁻¹", "cm^-1"} else result.spectral_unit
    ax.set_xlabel(f"Raman shift ({unit})", color=INK_MUTED)
    ax.set_ylabel("Intensity (norm.)" if normalize else "Intensity (a.u.)", color=INK_MUTED)
    ax.set_title(title or f"{result.label}: H components", color=INK, fontsize=12)
    ax.tick_params(colors=INK_MUTED)
    ax.grid(True, color=GRID, linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    legend = ax.legend(frameon=False, fontsize=9, labelcolor=INK)
    if show_seeds and result.seed_H is not None:
        legend.set_title("solid: H result   dashed: H seed", prop={"size": 8})
    fig.tight_layout()
    return fig


def plot_roi_overview(
    stack: np.ndarray,
    rois: Sequence[Roi],
    *,
    colors: Sequence[str] | None = None,
    palette: str | None = None,
    n_components: int | None = None,
    percentile: float = 99.5,
    title: str | None = None,
    annotate: bool = True,
) -> Figure:
    """Mean projection of the stack with the seed ROIs drawn on top.

    Use this to check *where* the spatial seeds sit before trusting the run.
    The projection is a neutral light-to-dark gray so the component-colored
    outlines stay unambiguous.
    """
    stack = np.asarray(stack)
    if stack.ndim != 3:
        raise ValueError(f"Expected a (bands, Y, X) stack, got shape {stack.shape}.")
    projection = np.asarray(stack, dtype=np.float64).mean(axis=0)
    shape_yx = projection.shape

    n = n_components if n_components is not None else (max((r.component for r in rois), default=0) + 1)
    component_palette = component_colors(n, colors, palette=palette)

    fig, ax = plt.subplots(figsize=(7.0, 6.8))
    fig.patch.set_facecolor(SURFACE)
    ax.imshow(_normalize_map(projection, percentile), cmap="gray_r", vmin=0.0, vmax=1.0)

    height_px, width_px = shape_yx
    placed: list[tuple[float, float]] = []

    for roi in rois:
        color = component_palette[int(roi.component) % len(component_palette)]
        if roi.rect is not None:
            y0, x0, roi_h, roi_w = (int(v) for v in roi.rect)
            ax.add_patch(Rectangle((x0 - 0.5, y0 - 0.5), roi_w, roi_h,
                                   fill=False, edgecolor=color, linewidth=1.6))
            center_x, top_y, bottom_y = x0 + roi_w / 2, y0, y0 + roi_h
        else:
            rows, cols = roi.indices(shape_yx)
            mask = np.zeros(shape_yx, dtype=float)
            mask[rows, cols] = 1.0
            ax.contour(mask, levels=[0.5], colors=[color], linewidths=1.6)
            center_x, top_y, bottom_y = float(cols.mean()), float(rows.min()), float(rows.max())
        if annotate and roi.name:
            _annotate_roi(ax, roi.name, color, center_x, top_y, bottom_y,
                          width_px, height_px, placed)

    used = sorted({int(roi.component) for roi in rois})
    ax.legend(
        handles=[Line2D([], [], color=component_palette[c % len(component_palette)], lw=2,
                        label=f"component {c}") for c in used],
        frameon=False, fontsize=9, labelcolor=INK,
        loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=min(len(used), 4),
    )
    ax.set_title(title or "Seed ROIs on the mean projection", color=INK, fontsize=12)
    _style_image_axes(ax)
    fig.tight_layout()
    return fig


def _annotate_roi(ax, text, color, center_x, top_y, bottom_y, width_px, height_px, placed):
    """Place a ROI label clear of the image edges and of labels already placed."""
    # Keep long labels inside the frame by anchoring them to the nearer edge.
    if center_x < 0.18 * width_px:
        label_x, align = 2.0, "left"
    elif center_x > 0.82 * width_px:
        label_x, align = width_px - 2.0, "right"
    else:
        label_x, align = center_x, "center"

    candidates = [
        (top_y - 5, "bottom"), (bottom_y + 5, "top"),
        (top_y - 19, "bottom"), (bottom_y + 19, "top"),
    ]
    label_y, valign = candidates[0]
    for candidate_y, candidate_va in candidates:
        if not 0 <= candidate_y <= height_px:
            continue
        if all(abs(label_x - px) > 0.22 * width_px or abs(candidate_y - py) > 13
               for px, py in placed):
            label_y, valign = candidate_y, candidate_va
            break
    placed.append((label_x, label_y))
    ax.annotate(text, (label_x, label_y), color=color, fontsize=7.5,
                ha=align, va=valign, clip_on=True)


def save_figures(
    result: NNMFResult,
    out_dir: str | Path,
    *,
    basename: str | None = None,
    colors: Sequence[str] | None = None,
    palette: str | None = None,
    formats: Sequence[str] = ("png", "pdf"),
    dpi: int = 200,
    percentile: float = 99.5,
    show: bool = False,
) -> list[Path]:
    """Write the W-map figure, the W-seed figure and the H-component figure.

    With ``show=True`` the figures are left open and ``plt.show()`` is called, so
    the windows pop up in an IDE *and* the files are on disk. Any other figure
    still open (a ROI overview, for instance) is shown along with them.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = basename or result.label
    written: list[Path] = []

    figures = {
        "W_components": plot_component_maps(
            result, colors=colors, palette=palette, percentile=percentile,
            title=f"{result.label}: W components"
        ),
        "H_components": plot_spectra(result, colors=colors, palette=palette),
    }
    if result.seed_W_2D is not None:
        figures["W_seeds"] = plot_component_maps(
            result, colors=colors, palette=palette, percentile=percentile, use_seeds=True,
            show_composite=False, title=f"{result.label}: W seeds",
        )

    for name, fig in figures.items():
        for extension in formats:
            path = out_dir / f"{base}_{name}.{extension}"
            fig.savefig(path, dpi=dpi, facecolor=fig.get_facecolor())
            written.append(path)
        if not show:
            plt.close(fig)

    logger.info("Wrote %s figure files to %s", len(written), out_dir)
    if show:
        plt.show()
    return written
