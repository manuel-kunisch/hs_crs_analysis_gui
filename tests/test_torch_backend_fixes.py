"""Regression tests for the v0.9.9 PyTorch backend fixes.

Covered here:
* the row-major (pixels, bands) data layout (`_cube_to_pixel_matrix`), which
  fixed the up-to-~100x slowdown of torch-CPU NNMF on the old Fortran-ordered
  zero-copy view, and the vectorized per-frame PCA standardization;
* the accurate residual norms (`torch_nmf._frobenius_norm`,
  `nnls_pytorch._l2_norm`) that replaced `torch.linalg.norm`;
* the FISTA step size being computed on the CPU on every backend;
* the `torch_devices` module: probes, `HS_MOSAIC_TORCH_DEVICE` override,
  labels and the torch.compile gate for DirectML.

Everything runs on the CPU; torch-dependent tests are skipped when PyTorch is
not installed.
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import nnls as scipy_nnls

from hs_mosaic.widgets import nnls_pytorch, torch_devices, torch_nmf
from hs_mosaic.widgets.multivariate_analyzer import MultivariateAnalyzer

TORCH = torch_devices.torch_available()
needs_torch = pytest.mark.skipif(not TORCH, reason="PyTorch is not installed")


def _synthetic_cube(n_bands: int = 12, side: int = 16, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.gamma(2.0, 1.0, size=(n_bands, side, side)).astype(np.float32)


def _synthetic_low_rank(n_pixels: int = 1024, n_bands: int = 16, k: int = 3, seed: int = 0):
    rng = np.random.default_rng(seed)
    axis = np.linspace(0, 1, n_bands, dtype=np.float32)
    H = np.stack(
        [np.exp(-((axis - c) ** 2) / (2 * 0.08 ** 2)) + 0.05 for c in np.linspace(0.2, 0.8, k)]
    ).astype(np.float32)
    W = rng.gamma(1.5, 1.0, size=(n_pixels, k)).astype(np.float32)
    X = W @ H + rng.normal(0, 0.005, (n_pixels, n_bands)).astype(np.float32)
    return np.maximum(X, 0.0).astype(np.float32), W, H


# ── torch_devices ────────────────────────────────────────────────────────────

def test_device_kind_parses_strings_and_devices():
    assert torch_devices.device_kind("cpu") == "cpu"
    assert torch_devices.device_kind("cuda:1") == "cuda"
    assert torch_devices.device_kind("dml") == "dml"
    if TORCH:
        assert torch_devices.device_kind(torch_devices.torch.device("cpu")) == "cpu"


def test_supports_torch_compile_gates_directml_only():
    assert torch_devices.supports_torch_compile("dml") is False
    assert torch_devices.supports_torch_compile("dml:0") is False
    assert torch_devices.supports_torch_compile("cpu") is True
    assert torch_devices.supports_torch_compile("cuda") is True


@needs_torch
def test_default_device_and_resolution():
    name = torch_devices.default_device()
    assert name in torch_devices.KNOWN_DEVICE_NAMES
    dev = torch_devices.resolve_torch_device("cpu")
    assert dev.type == "cpu"
    assert torch_devices.device_label("cpu") == "cpu"
    # None resolves to the default device without raising.
    assert torch_devices.resolve_torch_device(None) is not None


@needs_torch
def test_env_override_cpu_disables_accelerators(monkeypatch):
    monkeypatch.setenv(torch_devices.ENV_DEVICE_OVERRIDE, "cpu")
    assert torch_devices.available_accelerators() == []
    assert torch_devices.gpu_available() is False
    assert torch_devices.default_device() == "cpu"
    assert torch_nmf.default_device() == "cpu"  # alias goes through torch_devices
    assert nnls_pytorch.gpu_available() is False


@needs_torch
def test_env_override_invalid_value_falls_back_to_auto(monkeypatch):
    monkeypatch.delenv(torch_devices.ENV_DEVICE_OVERRIDE, raising=False)
    automatic = torch_devices.available_accelerators()
    monkeypatch.setenv(torch_devices.ENV_DEVICE_OVERRIDE, "hal9000")
    assert torch_devices.device_override() is None
    assert torch_devices.available_accelerators() == automatic


def test_accelerator_summary_and_description_have_the_selftest_fields():
    summary = torch_devices.accelerator_summary()
    for key in (
        "torch_available", "cuda_available", "mps_available", "xpu_available",
        "directml_available", "detected_accelerators", "default_device",
        "device_names", "device_override",
    ):
        assert key in summary
    assert isinstance(torch_devices.describe_accelerators(), str)
    assert torch_devices.describe_accelerators()


def test_solver_modules_reexport_the_probes():
    for module in (torch_nmf, nnls_pytorch):
        assert module.torch_available is torch_devices.torch_available
        assert module.directml_available is torch_devices.directml_available
        assert module.default_device is torch_devices.default_device


# ── data layout (the ~100x torch-CPU fix) ────────────────────────────────────

def test_cube_to_pixel_matrix_matches_moveaxis_reference():
    cube = _synthetic_cube()
    reference = np.moveaxis(cube, 0, -1).reshape(-1, cube.shape[0])
    matrix = MultivariateAnalyzer._cube_to_pixel_matrix(cube)
    assert matrix.shape == reference.shape
    np.testing.assert_array_equal(matrix, reference)
    if TORCH:
        assert matrix.flags["C_CONTIGUOUS"]


def test_cube_to_pixel_matrix_casts_dtype():
    cube = (_synthetic_cube() * 100).astype(np.uint16)
    matrix = MultivariateAnalyzer._cube_to_pixel_matrix(cube, dtype=np.float32)
    assert matrix.dtype == np.float32
    reference = np.moveaxis(cube, 0, -1).reshape(-1, cube.shape[0]).astype(np.float32)
    np.testing.assert_array_equal(matrix, reference)


def test_cube_to_pixel_matrix_rejects_non_cubes():
    with pytest.raises(ValueError):
        MultivariateAnalyzer._cube_to_pixel_matrix(np.zeros((4, 5)))


def test_analyzer_data_2d_layout_and_standardization():
    cube = _synthetic_cube(n_bands=10, side=12)
    analyzer = MultivariateAnalyzer(cube, 3, np.arange(cube.shape[0]), method="NNMF")

    reference = np.moveaxis(cube, 0, -1).reshape(-1, cube.shape[0]).astype(np.float32)
    np.testing.assert_array_equal(analyzer.data_2d, reference)
    assert analyzer.data_2d.dtype == np.float32
    if TORCH:
        assert analyzer.data_2d.flags["C_CONTIGUOUS"]

    # Vectorized standardization must reproduce the former per-frame loop.
    expected = np.zeros_like(reference)
    for i in range(reference.shape[1]):
        frame = reference[:, i]
        mean = np.nanmean(frame)
        std = np.std(frame - mean)
        expected[:, i] = (frame - mean) / std
    np.testing.assert_allclose(analyzer.pca_data_std, expected, rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(analyzer.pca_data_std.mean(axis=0), 0.0, atol=1e-4)
    np.testing.assert_allclose(analyzer.pca_data_std.std(axis=0), 1.0, atol=1e-4)


def test_resonance_data_uses_row_major_matrix():
    cube = _synthetic_cube(n_bands=8, side=10)
    analyzer = MultivariateAnalyzer(cube, 2, np.arange(cube.shape[0]), method="NNMF")
    subtracted = np.maximum(cube - 0.5, 0.0)
    analyzer.update_resonance_image_data(subtracted)
    reference = np.moveaxis(subtracted, 0, -1).reshape(-1, cube.shape[0])
    np.testing.assert_array_equal(analyzer.resonance_data_2d, reference)
    if TORCH:
        assert analyzer.resonance_data_2d.flags["C_CONTIGUOUS"]


# ── accurate norms ───────────────────────────────────────────────────────────

@needs_torch
def test_frobenius_norm_matches_float64_reference():
    torch = torch_devices.torch
    rng = np.random.default_rng(3)
    values = rng.normal(1.0, 0.1, size=(700, 500)).astype(np.float32)
    reference = float(np.linalg.norm(values.astype(np.float64)))
    result = float(torch_nmf._frobenius_norm(torch.from_numpy(values)).item())
    assert abs(result - reference) / reference < 1e-6
    assert float(torch_nmf._frobenius_norm(torch.zeros(5, 5)).item()) == 0.0


@needs_torch
def test_l2_norm_matches_float64_reference():
    torch = torch_devices.torch
    rng = np.random.default_rng(4)
    values = rng.normal(0.5, 0.2, size=(400, 300)).astype(np.float32)
    reference = float(np.linalg.norm(values.astype(np.float64)))
    result = float(nnls_pytorch._l2_norm(torch.from_numpy(values)).item())
    assert abs(result - reference) / reference < 1e-6


# ── solvers on the new layout ────────────────────────────────────────────────

@needs_torch
def test_torch_mu_solves_fortran_ordered_input():
    X, _, H = _synthetic_low_rank()
    x_fortran = np.asfortranarray(X)  # the pre-fix layout must still be accepted
    W_out, H_out, info = torch_nmf.solve_nmf_multiplicative_updates(
        x_fortran, n_components=3, device="cpu", max_iter=300, seed=0,
    )
    assert info["device"] == "cpu"
    assert info["device_kind"] == "cpu"
    relative_error = info["final_error"] / np.linalg.norm(X)
    assert relative_error < 0.05
    assert W_out.min() >= 0 and H_out.min() >= 0


@needs_torch
def test_torch_mu_handles_zero_iteration_budget():
    X, W, H = _synthetic_low_rank(n_pixels=64, n_bands=8, k=2)
    W_out, H_out, info = torch_nmf.solve_nmf_multiplicative_updates(
        X, w_init=np.maximum(W, 1e-6), h_init=np.maximum(H, 1e-6),
        device="cpu", max_iter=0,
    )
    assert info["n_iter"] == 0
    assert W_out.shape == W.shape and H_out.shape == H.shape


@needs_torch
def test_torch_nnls_matches_scipy_reference():
    X, _, H = _synthetic_low_rank(n_pixels=256)
    basis = np.asfortranarray(H.T.astype(np.float64))  # F-ordered on purpose
    abundance, info = nnls_pytorch.solve_batched_nnls_projected_gradient(
        X, basis, device="cpu", max_iter=600, tol=1e-7, chunk_size=100,
    )
    assert info["device"] == "cpu"
    assert info["device_kind"] == "cpu"
    reference = np.stack([scipy_nnls(np.asarray(basis), row)[0] for row in X])
    np.testing.assert_allclose(abundance, reference, rtol=0.05, atol=0.02)


@needs_torch
def test_analyzer_reports_torch_backend_labels(monkeypatch):
    monkeypatch.setenv(torch_devices.ENV_DEVICE_OVERRIDE, "cpu")
    cube = _synthetic_cube(n_bands=6, side=8)
    analyzer = MultivariateAnalyzer(cube, 2, np.arange(cube.shape[0]), method="NNMF")
    # With the override forcing CPU, the GPU-preferring dispatch falls back to
    # torch-CPU for both solvers, exactly like a GPU-less machine with torch:
    # since the NNLS un-gating, SciPy runs only when torch is not installed.
    analyzer.set_nnmf_backend_preference("gpu")
    assert analyzer._resolve_torch_nmf_device() == "cpu"
    assert analyzer._nnls_backend_name() == "torch-cpu"


def test_nnls_backend_name_without_torch_preference():
    cube = _synthetic_cube(n_bands=6, side=8)
    analyzer = MultivariateAnalyzer(cube, 2, np.arange(cube.shape[0]), method="NNMF")
    analyzer.prefer_torch_nnls = False
    assert analyzer._nnls_backend_name() == "scipy-cpu"
