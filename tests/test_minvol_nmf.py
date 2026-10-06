"""Tests for minimum-volume NNMF regularization (v0.9.9).

Covers the two MU kernels in ``hs_mosaic/widgets/torch_nmf.py``:

* the PyTorch kernel (``solve_nmf_multiplicative_updates``), skipped when
  PyTorch is not installed, and
* the pure-NumPy twin (``solve_nmf_multiplicative_updates_numpy``) that serves
  min-volume runs in torch-less installs.

The modules are loaded directly from their files (not through the
``hs_mosaic`` package) so the tests run without PyQt installed.

Run with the dev environment, e.g.::

    C:\\Users\\manue\\anaconda3\\envs\\py312_nnmf_pytorch\\python.exe -m pytest tests -v
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import numpy as np
import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


torch_nmf = _load("_test_torch_nmf", "hs_mosaic/widgets/torch_nmf.py")
diag = _load("_test_unmixing_diagnostics", "hs_mosaic/widgets/unmixing_diagnostics.py")

if not hasattr(torch_nmf, "solve_nmf_multiplicative_updates_numpy"):
    pytest.skip(
        "min-volume NNMF is not on this branch yet (the implementation is parked in "
        "the git stash '0.9.9 min-vol WIP'); these tests target that API and run "
        "again automatically once it lands.",
        allow_module_level=True,
    )

needs_torch = pytest.mark.skipif(
    not torch_nmf.torch_available(), reason="PyTorch is not installed"
)


# ---------------------------------------------------------------------------
# Synthetic no-pure-pixel dataset (deterministic)
# ---------------------------------------------------------------------------

def _make_synthetic(seed=7, n_px=3000, n_ch=60, max_frac=0.70):
    """3 moderately-overlapping spectra; every pixel a mixture (max fraction
    ``max_frac``), but facet-touching mixtures exist — the regime where
    min-volume NNMF is identifiable while pure-pixel methods are not."""
    rng = np.random.default_rng(seed)
    ch = np.arange(n_ch, dtype=np.float64)

    def gauss(c, s):
        return np.exp(-0.5 * ((ch - c) / s) ** 2)

    H_true = np.stack([
        1.00 * gauss(14, 3.0) + 0.35 * gauss(24, 5.0),
        0.90 * gauss(30, 3.5) + 0.30 * gauss(40, 6.0),
        1.00 * gauss(46, 3.0) + 0.25 * gauss(20, 7.0),
    ])
    H_true /= H_true.max(axis=1, keepdims=True)

    A = np.empty((0, 3))
    while A.shape[0] < n_px:
        cand = rng.dirichlet([0.45, 0.45, 0.45], size=2 * n_px)
        cand = cand[cand.max(axis=1) <= max_frac]
        A = np.vstack([A, cand])
    A = A[:n_px]
    brightness = 3.0e4 * rng.uniform(0.3, 1.0, size=(n_px, 1))
    W_true = A * brightness

    X = W_true @ H_true
    X = X + rng.normal(0.0, 0.01 * X.max(), size=X.shape)
    X = np.clip(X, 0.0, None).astype(np.float32)
    return X, W_true.astype(np.float32), H_true.astype(np.float32)


def _mixed_seed(H_true, m=0.35):
    """Deliberately re-mixed spectra: what a user starts from when no pure
    region exists to draw a seed ROI in."""
    k = H_true.shape[0]
    M = (1.0 - m) * np.eye(k) + m * np.ones((k, k)) / k
    Hs = M @ H_true
    Hs /= Hs.max(axis=1, keepdims=True)
    return Hs.astype(np.float32)


def _best_match_cosines(H, H_ref):
    def unit(a):
        return a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)

    C = unit(H.astype(np.float64)) @ unit(H_ref.astype(np.float64)).T
    k = C.shape[0]
    cos, used_r, used_c = [], set(), set()
    for _ in range(k):
        best = (-2.0, None, None)
        for i in range(k):
            for j in range(k):
                if i not in used_r and j not in used_c and C[i, j] > best[0]:
                    best = (C[i, j], i, j)
        cos.append(best[0])
        used_r.add(best[1])
        used_c.add(best[2])
    return np.asarray(cos)


@pytest.fixture(scope="module")
def synthetic():
    X, W_true, H_true = _make_synthetic()
    return {
        "X": X,
        "H_true": H_true,
        "H_seed": _mixed_seed(H_true),
        "solver_kwargs": dict(max_iter=1500, tol=1e-6, patience=3, seed=0),
    }


# ---------------------------------------------------------------------------
# 1. Recovery: min-vol pulls the solution toward the true spectra
# ---------------------------------------------------------------------------

def test_minvol_improves_truth_recovery_numpy(synthetic):
    X, H_true, H_seed = synthetic["X"], synthetic["H_true"], synthetic["H_seed"]
    kwargs = dict(synthetic["solver_kwargs"], h_init=H_seed)

    _, H_plain, info_plain = torch_nmf.solve_nmf_multiplicative_updates_numpy(X, **kwargs)
    _, H_mv, info_mv = torch_nmf.solve_nmf_multiplicative_updates_numpy(
        X, minvol_lambda=0.05, **kwargs)

    cos_plain = _best_match_cosines(H_plain, H_true).mean()
    cos_mv = _best_match_cosines(H_mv, H_true).mean()
    assert cos_mv > cos_plain, (
        f"min-vol should recover the true spectra better: {cos_mv} vs {cos_plain}")

    # Separability moves TOWARD the true value (plain MU tends to
    # over-separate: its implicit sparsity bias sharpens spectra beyond
    # reality; min-vol shrinks the simplex back onto the data).
    eta_true = diag.separability(H_true).eta_min
    eta_plain = diag.separability(H_plain).eta_min
    eta_mv = diag.separability(H_mv).eta_min
    assert abs(eta_mv - eta_true) < abs(eta_plain - eta_true)

    # The fit must not degrade materially (penalty refines, not distorts).
    assert info_mv["final_error"] < 1.05 * info_plain["final_error"]

    # Info contract.
    assert info_mv["minvol_lambda_rel"] == pytest.approx(0.05)
    assert info_mv["minvol_lambda_abs"] is not None and info_mv["minvol_lambda_abs"] > 0
    assert info_mv["minvol_delta"] == pytest.approx(0.1)
    assert info_mv["minvol_calibration_iter"] is not None
    assert np.isfinite(info_mv["volume_logdet"])
    assert np.isfinite(info_mv["objective_final"])
    assert len(info_mv["objective_history"]) > 1
    # Output gauge: H rows at unit max (dead-row floor aside).
    assert np.allclose(H_mv.max(axis=1), 1.0, atol=1e-4)


# ---------------------------------------------------------------------------
# 2. Objective descent (root-form update is monotone modulo the gauge fix)
# ---------------------------------------------------------------------------

def test_minvol_objective_descends_numpy(synthetic):
    X, H_seed = synthetic["X"], synthetic["H_seed"]
    kwargs = dict(synthetic["solver_kwargs"], h_init=H_seed)
    _, _, info = torch_nmf.solve_nmf_multiplicative_updates_numpy(
        X, minvol_lambda=0.1, **kwargs)
    oh = np.asarray(info["objective_history"], dtype=np.float64)
    assert len(oh) > 2
    rel_rises = np.diff(oh) / np.maximum(np.abs(oh[:-1]), 1.0)
    assert (rel_rises <= 1e-3).all(), f"objective rose: max rise {rel_rises.max()}"


# ---------------------------------------------------------------------------
# 3. lambda = 0 is exactly the unregularized solver
# ---------------------------------------------------------------------------

def test_lambda_zero_identity_numpy(synthetic):
    X, H_seed = synthetic["X"], synthetic["H_seed"]
    kwargs = dict(synthetic["solver_kwargs"], h_init=H_seed)
    W0, H0, _ = torch_nmf.solve_nmf_multiplicative_updates_numpy(X, **kwargs)
    W1, H1, info1 = torch_nmf.solve_nmf_multiplicative_updates_numpy(
        X, minvol_lambda=0.0, **kwargs)
    assert np.array_equal(W0, W1) and np.array_equal(H0, H1)
    assert "minvol_lambda_rel" not in info1


@needs_torch
def test_lambda_zero_identity_torch(synthetic):
    X, H_seed = synthetic["X"], synthetic["H_seed"]
    kwargs = dict(synthetic["solver_kwargs"], h_init=H_seed)
    W0, H0, _ = torch_nmf.solve_nmf_multiplicative_updates(X, device="cpu", **kwargs)
    W1, H1, info1 = torch_nmf.solve_nmf_multiplicative_updates(
        X, device="cpu", minvol_lambda=0.0, **kwargs)
    assert np.array_equal(W0, W1) and np.array_equal(H0, H1)
    assert "minvol_lambda_rel" not in info1


# ---------------------------------------------------------------------------
# 4. NumPy vs torch parity (identical inits, same math)
# ---------------------------------------------------------------------------

@needs_torch
def test_numpy_torch_parity(synthetic):
    X, H_seed = synthetic["X"], synthetic["H_seed"]
    kwargs = dict(synthetic["solver_kwargs"], h_init=H_seed, minvol_lambda=0.05)
    _, H_np, info_np = torch_nmf.solve_nmf_multiplicative_updates_numpy(X, **kwargs)
    _, H_t, info_t = torch_nmf.solve_nmf_multiplicative_updates(X, device="cpu", **kwargs)

    cos = _best_match_cosines(H_t, H_np)
    assert (cos > 0.999).all(), f"kernel disagreement: {cos}"
    assert info_t["objective_final"] == pytest.approx(info_np["objective_final"], rel=0.01)
    assert info_t["minvol_lambda_abs"] == pytest.approx(info_np["minvol_lambda_abs"], rel=0.01)


# ---------------------------------------------------------------------------
# 5. Gauge renormalization preserves the reconstruction
# ---------------------------------------------------------------------------

def test_gauge_renorm_preserves_product():
    rng = np.random.default_rng(3)
    w = rng.random((50, 4)).astype(np.float32)
    h = rng.random((4, 30)).astype(np.float32) * np.array([[1.0], [10.0], [0.1], [1e-7]], dtype=np.float32)
    w2, h2 = torch_nmf._numpy_minvol_normalize_h_rows(w, h, torch_nmf._MINVOL_DEAD_ROW_FLOOR)
    assert np.allclose(w2 @ h2, w @ h, rtol=1e-5)
    norms = np.linalg.norm(h2, axis=1)
    # Alive rows are unit-l2; the numerically dead row is left untouched.
    assert np.allclose(norms[:3], 1.0, rtol=1e-5)
    assert norms[3] < 1e-5


# ---------------------------------------------------------------------------
# 6. Guards: k=1 and frozen H skip the penalty instead of failing
# ---------------------------------------------------------------------------

def test_minvol_skipped_for_single_component(synthetic):
    X = synthetic["X"]
    _, _, info = torch_nmf.solve_nmf_multiplicative_updates_numpy(
        X, n_components=1, minvol_lambda=0.05, max_iter=30, tol=1e-4, patience=1, seed=0)
    assert "minvol_skipped" in info
    assert "minvol_lambda_rel" not in info


def test_minvol_skipped_for_frozen_h(synthetic):
    X, H_seed = synthetic["X"], synthetic["H_seed"]
    _, _, info = torch_nmf.solve_nmf_multiplicative_updates_numpy(
        X, h_init=H_seed, update_h=False, minvol_lambda=0.05,
        max_iter=30, tol=1e-4, patience=1, seed=0)
    assert "minvol_skipped" in info
    assert "minvol_lambda_rel" not in info


# ---------------------------------------------------------------------------
# 7. Delta is clamped to its safe range
# ---------------------------------------------------------------------------

def test_minvol_delta_clamped(synthetic):
    X, H_seed = synthetic["X"], synthetic["H_seed"]
    _, _, info = torch_nmf.solve_nmf_multiplicative_updates_numpy(
        X, h_init=H_seed, minvol_lambda=0.05, minvol_delta=1e-9,
        max_iter=60, tol=1e-4, patience=1, seed=0)
    assert info["minvol_delta"] == pytest.approx(1e-3)
