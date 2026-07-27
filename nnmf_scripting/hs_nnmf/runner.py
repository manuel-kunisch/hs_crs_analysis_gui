"""Run HS-MOSAIC's custom (seeded) NNMF from a script.

This drives ``hs_mosaic.widgets.multivariate_analyzer.MultivariateAnalyzer``
through the same call sequence the GUI's analysis manager uses, so a scripted
run and a GUI run with the same settings produce the same factorization.

Seed order (highest priority first), same as in the GUI:

1. ``params.h_seeds``      -- spectra handed in directly
2. ``params.rois``         -- mean spectrum of a spatial region (averaged per component)
3. ``params.vca``          -- VCA endmembers fill every component still unseeded
4. analyzer fallbacks      -- residual-NNLS spectrum, else smoothed random
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import tifffile

from hs_mosaic.widgets.multivariate_analyzer import MultivariateAnalyzer
from hs_mosaic.widgets.vca import extract_endmember_spectra

from .config import NNMFParams, Roi

logger = logging.getLogger(__name__)

EPS = 1e-8


# ---------------------------------------------------------------------------
# result container
# ---------------------------------------------------------------------------
@dataclass
class NNMFResult:
    """Outcome of one run: ``X ~= W @ H`` with ``W >= 0``, ``H >= 0``."""

    W: np.ndarray                  # (n_pixels, k) abundances
    H: np.ndarray                  # (k, n_bands) spectra
    W_2D: np.ndarray               # (k, Y, X) abundance maps
    wavenumbers: np.ndarray
    spectral_unit: str
    label: str = "nnmf"
    seed_H: np.ndarray | None = None
    seed_W_2D: np.ndarray | None = None
    info: dict[str, Any] = field(default_factory=dict)
    seed_info: dict[str, Any] = field(default_factory=dict)
    params_summary: dict[str, Any] = field(default_factory=dict)
    elapsed_s: float = 0.0
    seed_elapsed_s: float = 0.0

    @property
    def n_components(self) -> int:
        return int(self.H.shape[0])

    @property
    def relative_error(self) -> float | None:
        value = self.info.get("relative_error")
        return None if value is None else float(value)

    def reorder(self, order) -> "NNMFResult":
        """Return a copy with components permuted by ``order``."""
        order = np.asarray(order, dtype=int)
        return NNMFResult(
            W=self.W[:, order],
            H=self.H[order],
            W_2D=self.W_2D[order],
            wavenumbers=self.wavenumbers,
            spectral_unit=self.spectral_unit,
            label=self.label,
            seed_H=None if self.seed_H is None else self.seed_H[order],
            seed_W_2D=None if self.seed_W_2D is None else self.seed_W_2D[order],
            info=dict(self.info),
            seed_info=dict(self.seed_info),
            params_summary=dict(self.params_summary),
            elapsed_s=self.elapsed_s,
            seed_elapsed_s=self.seed_elapsed_s,
        )

    def match_to(self, reference_H: np.ndarray) -> "NNMFResult":
        """Permute components so each one lines up with the closest reference
        spectrum (cosine similarity, one-to-one). Makes runs with different
        seeding comparable component by component."""
        from scipy.optimize import linear_sum_assignment

        similarity = _cosine_similarity_matrix(self.H, np.asarray(reference_H, dtype=np.float64))
        rows, cols = linear_sum_assignment(-similarity)
        order = np.empty(self.H.shape[0], dtype=int)
        order[cols] = rows
        logger.info(
            "%s: matched components to reference, similarity %s",
            self.label, np.round(similarity[rows, cols], 3).tolist(),
        )
        return self.reorder(order)

    def summary(self) -> str:
        parts = [
            f"{self.label}: {self.n_components} components",
            f"backend={self.info.get('backend')}",
            f"solver={self.info.get('solver')}",
            f"iters={self.info.get('n_iter')}/{self.info.get('max_iter')}",
        ]
        if self.relative_error is not None:
            parts.append(f"rel.err={self.relative_error:.4f}")
        parts.append(f"seeding={self.seed_elapsed_s:.1f}s")
        parts.append(f"fit={self.elapsed_s:.1f}s")
        return " | ".join(parts)

    # -- saving ------------------------------------------------------------
    def save(self, out_dir: str | Path, basename: str | None = None) -> dict[str, Path]:
        """Write component maps (TIFF), spectra (CSV) and a run sidecar (JSON).

        The TIFF is a ``(k, Y, X)`` uint16 stack scaled by one global factor, so
        relative component amplitudes stay comparable and it opens in FIJI as a
        stack. The scale factor is recorded in the JSON.
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        base = basename or self.label
        written: dict[str, Path] = {}

        maps = np.nan_to_num(np.asarray(self.W_2D, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
        maps = np.maximum(maps, 0.0)
        peak = float(maps.max()) if maps.size else 0.0
        scale = (65535.0 / peak) if peak > 0 else 1.0
        tif_path = out_dir / f"{base}_W_components.tif"
        tifffile.imwrite(str(tif_path), np.clip(maps * scale, 0, 65535).astype(np.uint16))
        written["components_tif"] = tif_path

        csv_path = out_dir / f"{base}_H_spectra.csv"
        header = f"wavenumber_{self.spectral_unit}," + ",".join(
            f"component_{i}" for i in range(self.n_components)
        )
        table = np.column_stack([np.asarray(self.wavenumbers, dtype=float), self.H.T])
        np.savetxt(csv_path, table, delimiter=",", header=header, comments="", fmt="%.6g")
        written["spectra_csv"] = csv_path

        if self.seed_H is not None:
            seed_csv = out_dir / f"{base}_H_seeds.csv"
            seed_table = np.column_stack([np.asarray(self.wavenumbers, dtype=float), self.seed_H.T])
            np.savetxt(seed_csv, seed_table, delimiter=",", header=header, comments="", fmt="%.6g")
            written["seed_spectra_csv"] = seed_csv

        json_path = out_dir / f"{base}_run.json"
        json_path.write_text(
            json.dumps(
                {
                    "label": self.label,
                    "n_components": self.n_components,
                    "spectral_unit": self.spectral_unit,
                    "params": self.params_summary,
                    "seed_info": _jsonable(self.seed_info),
                    "nnmf_info": _jsonable(self.info),
                    "seed_seconds": round(self.seed_elapsed_s, 3),
                    "fit_seconds": round(self.elapsed_s, 3),
                    "component_tif_scale": scale,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        written["run_json"] = json_path

        logger.info("Saved %s results to %s", self.label, out_dir)
        return written


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------
def run_nnmf(
    stack: np.ndarray,
    wavenumbers: np.ndarray,
    params: NNMFParams,
    *,
    spectral_unit: str = "cm-1",
    label: str | None = None,
) -> NNMFResult:
    """Run NNMF on a ``(bands, Y, X)`` stack and return the factorization."""
    params.validate()
    stack = np.asarray(stack)
    if stack.ndim != 3:
        raise ValueError(f"Expected a (bands, Y, X) stack, got shape {stack.shape}.")
    wavenumbers = np.asarray(wavenumbers, dtype=np.float32)
    if wavenumbers.size != stack.shape[0]:
        raise ValueError(
            f"Spectral axis has {wavenumbers.size} points but the stack has {stack.shape[0]} bands."
        )
    run_label = label or (f"{params.init}_nnmf" if not params.vca.enabled else "vca_nnmf")

    analyzer = MultivariateAnalyzer(stack, params.n_components, wavenumbers, method="NNMF")
    analyzer.set_spectral_units(spectral_unit)
    _configure_solver(analyzer, params)

    subtracted = None
    if params.background_roi is not None:
        subtracted = _subtract_background(analyzer, stack, params.background_roi)

    seed_start = time.perf_counter()
    seed_info: dict[str, Any] = {}
    if params.init == "random":
        analyzer.set_custom_nnmf_init(False)
        logger.info("[%s] random-init NNMF (no seeds)", run_label)
    else:
        analyzer.set_custom_nnmf_init(True)
        seed_info = _build_seeds(analyzer, stack, subtracted, params, run_label)
    seed_elapsed = time.perf_counter() - seed_start

    seed_H = None if analyzer.seed_H is None else np.array(analyzer.seed_H, copy=True)
    seed_W_2D = None
    if params.init != "random" and analyzer.seed_W is not None:
        seed_W_2D = analyzer.reshape_2d_3d_mv_data(np.asarray(analyzer.seed_W, dtype=np.float32))

    logger.info("[%s] starting NNMF (%s components)", run_label, params.n_components)
    fit_start = time.perf_counter()
    analyzer.start_analysis()
    fit_elapsed = time.perf_counter() - fit_start

    if analyzer.fixed_W is None or analyzer.fixed_H is None:
        raise RuntimeError(
            f"[{run_label}] NNMF did not produce a result -- check the log for aborted seeding."
        )

    fit_info = dict(analyzer.last_nnmf_info or {})
    fit_info.setdefault("max_iter", params.max_iter)

    result = NNMFResult(
        W=np.asarray(analyzer.fixed_W, dtype=np.float32),
        H=np.asarray(analyzer.fixed_H, dtype=np.float32),
        W_2D=np.asarray(analyzer.fixed_W_2D, dtype=np.float32),
        wavenumbers=wavenumbers,
        spectral_unit=spectral_unit,
        label=run_label,
        seed_H=seed_H,
        seed_W_2D=seed_W_2D,
        info=fit_info,
        seed_info=seed_info,
        params_summary=params.describe(),
        elapsed_s=fit_elapsed,
        seed_elapsed_s=seed_elapsed,
    )
    logger.info("[%s] %s", run_label, result.summary())
    return result


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _configure_solver(analyzer: MultivariateAnalyzer, params: NNMFParams) -> None:
    analyzer.set_nnmf_solver(params.solver)
    analyzer.set_nnmf_backend_preference(params.backend)
    analyzer.set_nnmf_max_iter(params.max_iter)
    analyzer.set_nnmf_tol(params.tol)
    analyzer.set_nnmf_patience(params.patience)
    analyzer.set_nnmf_use_compile(params.use_compile)
    analyzer.set_nnls_max_iter(params.nnls_max_iter)
    analyzer.set_nnls_tol(params.nnls_tol)
    analyzer.set_w_seed_downsample_factor(params.w_seed_downsample)
    analyzer.set_W_seed_mode(params.w_seed_mode)


def _subtract_background(
    analyzer: MultivariateAnalyzer, stack: np.ndarray, roi: Roi
) -> np.ndarray:
    """Reproduce the ROI 'Subtract' checkbox: remove a background spectrum and
    hand the result to the analyzer as the 'subtracted data' used for seeds."""
    background = roi.spectrum(stack)
    subtracted = np.asarray(stack, dtype=np.float32) - background[:, None, None].astype(np.float32)
    subtracted[subtracted <= 0] = np.finfo(np.float32).eps
    analyzer.update_resonance_image_data(subtracted)
    logger.info(
        "Subtracted background spectrum from %s (mean level %.1f counts).",
        roi.label, float(background.mean()),
    )
    return subtracted


def _build_seeds(
    analyzer: MultivariateAnalyzer,
    stack: np.ndarray,
    subtracted: np.ndarray | None,
    params: NNMFParams,
    run_label: str,
) -> dict[str, Any]:
    """Fill seed_H / seed_W following the GUI's analysis-manager sequence."""
    info: dict[str, Any] = {"h_seed_source": {}}
    analyzer.reset_seeds()

    background_components = set(int(c) for c in params.background_components)
    for roi in params.rois:
        if roi.is_background:
            background_components.add(int(roi.component))

    # -- 1. H seeds from ROIs (several ROIs per component are averaged) -----
    roi_by_component: dict[int, list[Roi]] = {}
    for roi in params.rois:
        roi_by_component.setdefault(int(roi.component), []).append(roi)
    for component, rois in sorted(roi_by_component.items()):
        source = stack
        spectra = []
        for roi in rois:
            source = stack if (roi.is_background or not roi.use_subtracted or subtracted is None) else subtracted
            spectra.append(roi.spectrum(source))
        spectrum = np.mean(spectra, axis=0)
        analyzer.set_H_seed(component, spectrum, flag_background=component in background_components)
        names = ", ".join(roi.label for roi in rois)
        info["h_seed_source"][component] = f"roi[{names}]"
        logger.info(
            "[%s] H seed for component %s from %s ROI(s): %s", run_label, component, len(rois), names
        )

    # -- 2. explicit spectra win over ROIs ---------------------------------
    for component, spectrum in sorted(params.h_seeds.items()):
        spectrum = np.asarray(spectrum, dtype=np.float64).ravel()
        analyzer.set_H_seed(int(component), spectrum, flag_background=int(component) in background_components)
        info["h_seed_source"][int(component)] = "explicit"
        logger.info("[%s] H seed for component %s from explicit spectrum", run_label, component)

    # -- 3. VCA fills whatever is still unseeded ---------------------------
    if params.vca.enabled:
        info.update(_apply_vca_seeds(analyzer, stack, subtracted, params, run_label, background_components))

    for component in range(params.n_components):
        if component in background_components:
            analyzer.seed_H_background_flag[component] = True
        info["h_seed_source"].setdefault(component, "analyzer fallback (residual/random)")

    # -- 4. spectral seeds -> W columns (GUI resonance table) --------------
    if params.spectral_seeds:
        analyzer.update_spectral_info([seed.as_info() for seed in params.spectral_seeds])
        # debug_mode=False keeps this headless; the GUI opens a preview window here.
        analyzer.make_W_seeds_from_spectral_info(reset_old_seed=True, debug_mode=False)
        info["spectral_seed_components"] = sorted({seed.component for seed in params.spectral_seeds})

    # -- 5. fixed W columns -------------------------------------------------
    for component, w_map in sorted(params.fixed_w_seeds.items()):
        column = np.asarray(w_map, dtype=np.float64).reshape(-1)
        if column.size != analyzer.seed_W.shape[0]:
            raise ValueError(
                f"fixed_w_seeds[{component}] has {column.size} pixels, expected {analyzer.seed_W.shape[0]}."
            )
        analyzer.seed_W[:, int(component)] = analyzer._scale_w_seed_to_unity(column, eps=EPS)
        logger.info("[%s] using fixed W seed for component %s", run_label, component)

    # -- 6. unity-normalize H (GUI: 'Normalize H seeds to unity') ----------
    def finalize_h_scale() -> None:
        if params.normalize_h_to_unity:
            scales = analyzer.apply_H_seed_unity_normalization()
            if scales is not None:
                logger.info("[%s] normalized H seeds to unity, scale factors %s", run_label, np.round(scales, 2))
        else:
            analyzer.clear_H_seed_scale_reference()

    if params.normalize_h_to_unity:
        if not analyzer.has_complete_H_seed_set():
            logger.info("[%s] completing missing H seeds before unity normalization", run_label)
            analyzer.set_up_missing_H_seeds()
        finalize_h_scale()
    else:
        analyzer.clear_H_seed_scale_reference()

    # -- 7. W seeds from H, then fill the remainder ------------------------
    analyzer.estimate_W_seed_matrix_from_H(
        overwrite=params.overwrite_w_from_h,
        skip_components=set(int(c) for c in params.fixed_w_seeds),
        normalize_w_seed=params.normalize_w_seed,
    )
    analyzer.set_up_missing_W_seeds(
        skip_spectral_info=True,
        fill_H_seed=True,
        normalize_w_seed=params.normalize_w_seed,
        h_seed_finalizer=finalize_h_scale if params.normalize_h_to_unity else None,
    )
    if not params.normalize_h_to_unity:
        analyzer.set_up_missing_H_seeds()

    analyzer._W_prepared = analyzer._all_columns_seeded(analyzer.seed_W)
    if not analyzer._W_prepared:
        raise RuntimeError(f"[{run_label}] W seed matrix is incomplete; NNMF would abort.")

    info["w_seed_mode"] = analyzer.w_seed_mode
    info["w_seed_downsample"] = analyzer.w_seed_downsample_factor
    info["nnls"] = _jsonable(analyzer.last_nnls_info or {})
    info["background_components"] = sorted(background_components)
    return info


def _apply_vca_seeds(
    analyzer: MultivariateAnalyzer,
    stack: np.ndarray,
    subtracted: np.ndarray | None,
    params: NNMFParams,
    run_label: str,
    background_components: set[int],
) -> dict[str, Any]:
    """Fill unseeded components with VCA endmembers.

    With nothing else seeded this is a plain 1:1 mapping (endmember i ->
    component i). When some components already carry a seed, the remaining
    endmembers are assigned greedily to the components they resemble least,
    so VCA adds new information instead of duplicating an existing seed.
    """
    source = stack
    if params.vca.use_subtracted and subtracted is not None:
        source = subtracted

    n_endmembers = int(params.vca.n_endmembers or params.n_components)
    spectra, pixel_indices = extract_endmember_spectra(
        source, n_endmembers, seed=params.vca.seed, clip_negative=params.vca.clip_negative
    )
    height, width = stack.shape[1], stack.shape[2]
    coords = [(int(idx // width), int(idx % width)) for idx in np.asarray(pixel_indices).ravel()]
    logger.info("[%s] VCA endmember pixels (y, x): %s", run_label, coords)

    unseeded = [
        component
        for component in range(params.n_components)
        if not analyzer._has_seed_signal(analyzer.seed_H[component])
    ]
    seeded = [c for c in range(params.n_components) if c not in unseeded]

    if not seeded:
        assignment = {component: component for component in unseeded if component < len(spectra)}
    else:
        seeded_H = analyzer.seed_H[seeded]
        similarity = _cosine_similarity_matrix(np.asarray(spectra, dtype=np.float64), seeded_H)
        redundancy = similarity.max(axis=1)  # how much each endmember duplicates an existing seed
        candidates = list(np.argsort(redundancy))
        assignment = {}
        for component in unseeded:
            if not candidates:
                break
            assignment[component] = int(candidates.pop(0))

    for component, endmember in sorted(assignment.items()):
        analyzer.set_H_seed(
            component,
            np.asarray(spectra[endmember], dtype=np.float64),
            flag_background=component in background_components,
        )
        logger.info(
            "[%s] H seed for component %s from VCA endmember %s at pixel (y=%s, x=%s)",
            run_label, component, endmember, coords[endmember][0], coords[endmember][1],
        )

    return {
        "vca_endmember_pixels": {int(c): coords[e] for c, e in assignment.items()},
        "vca_n_endmembers": n_endmembers,
    }


def _cosine_similarity_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Row-wise cosine similarity between two sets of spectra."""
    a = np.nan_to_num(np.asarray(a, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    b = np.nan_to_num(np.asarray(b, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    a_norm = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), EPS)
    b_norm = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), EPS)
    return a_norm @ b_norm.T


def _jsonable(obj: Any) -> Any:
    """Make solver info dictionaries JSON-serialisable."""
    if isinstance(obj, dict):
        return {str(key): _jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(value) for value in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)
