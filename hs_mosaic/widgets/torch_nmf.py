import logging
from typing import Optional

import numpy as np

from hs_mosaic.widgets import torch_devices

logger = logging.getLogger(__name__)

# ``torch`` is optional. The module-level name is kept (``torch_nmf.torch``)
# because the backend self-test in app.py reads version info through it.
torch = torch_devices.torch
_TORCH_IMPORT_ERROR = torch_devices.import_error()

# Device probes live in ``torch_devices`` since DirectML support was added;
# these thin aliases keep the historical ``torch_nmf.*`` API working.
torch_available = torch_devices.torch_available
cuda_available = torch_devices.cuda_available
mps_available = torch_devices.mps_available
xpu_available = torch_devices.xpu_available
directml_available = torch_devices.directml_available
gpu_available = torch_devices.gpu_available
import_error = torch_devices.import_error
default_device = torch_devices.default_device


def _as_nonnegative_float32(array: np.ndarray) -> np.ndarray:
    # NMF requires inputs >= 0, not strictly > 0. The init paths below add a
    # separate eps lift for W and H to dodge the multiplicative-update
    # zero-stuck-zero issue.
    arr = np.asarray(array, dtype=np.float32)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    # Row-major layout is essential: torch-CPU's matmul on a column-major
    # (Fortran-ordered) matrix is several hundred times slower, and DirectML
    # re-orders such arrays on every upload. No copy if already C-contiguous.
    return np.ascontiguousarray(np.maximum(arr, 0.0))


def _validate_nmf_inputs(
        data: np.ndarray,
        n_components: Optional[int],
        w_init: Optional[np.ndarray],
        h_init: Optional[np.ndarray],
) -> tuple[np.ndarray, int, Optional[np.ndarray], Optional[np.ndarray]]:
    x = np.asarray(data, dtype=np.float32)
    if x.ndim != 2:
        raise ValueError(f"NMF expects a 2D matrix, got {x.ndim}D input.")

    if w_init is not None:
        w_init = np.asarray(w_init, dtype=np.float32)
        if w_init.ndim != 2:
            raise ValueError("w_init must be a 2D array.")
        n_components = w_init.shape[1]

    if h_init is not None:
        h_init = np.asarray(h_init, dtype=np.float32)
        if h_init.ndim != 2:
            raise ValueError("h_init must be a 2D array.")
        if n_components is None:
            n_components = h_init.shape[0]
        elif h_init.shape[0] != n_components:
            raise ValueError(
                f"Inconsistent component count between inits: {n_components=} and {h_init.shape[0]=}."
            )

    if n_components is None or int(n_components) <= 0:
        raise ValueError("n_components must be provided when no valid init matrices are given.")
    n_components = int(n_components)

    if w_init is not None and w_init.shape[0] != x.shape[0]:
        raise ValueError(f"w_init has incompatible shape {w_init.shape} for data {x.shape}.")
    if h_init is not None and h_init.shape[1] != x.shape[1]:
        raise ValueError(f"h_init has incompatible shape {h_init.shape} for data {x.shape}.")

    return x, n_components, w_init, h_init


def reconstruction_error(data: np.ndarray, w: np.ndarray, h: np.ndarray) -> float:
    residual = np.asarray(data, dtype=np.float32) - np.asarray(w, dtype=np.float32) @ np.asarray(h, dtype=np.float32)
    return float(np.linalg.norm(residual, ord="fro"))


def _frobenius_norm(tensor):
    """Frobenius norm of a tensor, accurate on every device.

    Deliberately *not* ``torch.linalg.norm(..., ord="fro")``: on the CPU
    build of PyTorch that entry point accumulates the squares sequentially
    in float32, and for a 1024x1024x32 residual (34M elements) the result is
    already off by ~1e-3, at 4M pixels by ~1e-2 — larger than the 1e-4
    relative-improvement tolerance this norm feeds. ``torch.sum`` uses a
    cascaded (pairwise) reduction on all backends (measured relative error
    < 1e-7 on CPU and DirectML), so ``sqrt(sum(x*x))`` is both accurate and
    made of kernels every backend has.
    """
    return torch.sqrt(torch.sum(tensor * tensor))


def solve_nmf_multiplicative_updates(
        data: np.ndarray,
        *,
        n_components: Optional[int] = None,
        w_init: Optional[np.ndarray] = None,
        h_init: Optional[np.ndarray] = None,
        device: Optional[str] = None,
        max_iter: int = 500,
        tol: float = 1e-4,
        eps: float = 1e-8,
        update_w: bool = True,
        update_h: bool = True,
        track_error_every: int = 10,
        normalize_w_columns: bool = False,
        seed: int = 0,
        patience: int = 3,
        use_compile: bool = False,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Factorize X ≈ W @ H with W >= 0 and H >= 0 using multiplicative updates.

    Shapes:
        data  : (n_samples, n_features)
        W     : (n_samples, n_components)
        H     : (n_components, n_features)

    This implementation uses dense matrix products and pointwise updates, so it
    runs on every PyTorch device: CPU, CUDA, Apple MPS, Intel XPU and, through
    the ``torch-directml`` plugin, any DirectX-12 GPU on Windows (``device="dml"``,
    the route for AMD Radeon GPUs and APUs). ``device`` accepts the short names
    understood by :func:`hs_mosaic.widgets.torch_devices.resolve_torch_device`;
    ``None`` picks the best available device.

    Convergence
    -----------
    The reconstruction error is sampled every ``track_error_every`` iterations.
    The solver declares convergence and stops early only after the relative
    improvement has stayed at-or-below ``tol`` for ``patience`` *consecutive*
    sampled iterations.

    * ``patience=1`` (most aggressive): exits at the first below-tol check.
      Fastest on smooth-converging data, but can exit prematurely on noisy
      data where the relative-improvement curve dips below tol briefly and
      then recovers.
    * ``patience=3`` (default, robust): exits only after three consecutive
      below-tol checks. A few iterations slower than ``patience=1`` on
      well-behaved data, but immune to single-check noise dips.

    Optional graph compilation
    --------------------------
    When ``use_compile=True``, the per-iteration W/H update body is wrapped in
    ``torch.compile()`` to fuse the matmul + pointwise ops into single fused
    kernels. Most beneficial on CUDA (~1.3-2x); modest on CPU (~1.2-1.5x);
    inconsistent on MPS / XPU where PyTorch's compiler support is still
    evolving, and skipped on DirectML, which has no compiler backend. The
    first iteration pays a one-time compile cost (~5-10 s) that amortises
    across all subsequent iterations and is well worth it for 4D stacks where
    the same shape is processed many times.
    """
    if not torch_available():
        raise RuntimeError(f"PyTorch is not available: {_TORCH_IMPORT_ERROR}")

    x_np, n_components, w_init, h_init = _validate_nmf_inputs(data, n_components, w_init, h_init)
    x_np = _as_nonnegative_float32(x_np)

    dev = torch_devices.resolve_torch_device(device)
    dev_label = torch_devices.device_label(dev)

    x = torch.as_tensor(x_np, device=dev)
    n_samples, n_features = x.shape

    if w_init is None:
        w_np = np.random.default_rng(seed).random((n_samples, n_components), dtype=np.float32)
    else:
        w_np = _as_nonnegative_float32(w_init)

    if h_init is None:
        h_np = np.random.default_rng(seed + 1).random((n_components, n_features), dtype=np.float32)
    else:
        h_np = _as_nonnegative_float32(h_init)

    w = torch.as_tensor(w_np, device=dev)
    h = torch.as_tensor(h_np, device=dev)
    w = torch.clamp(w, min=eps)
    h = torch.clamp(h, min=eps)

    if not update_w and not update_h:
        raise ValueError("At least one of update_w or update_h must be True.")

    history: list[float] = []
    prev_error = None
    patience_hits = 0
    track_error_every = max(int(track_error_every), 1)
    patience = max(int(patience), 1)

    # Build the per-iteration update function. Wrapping in torch.compile fuses
    # the matmul + pointwise ops into single kernels on supported backends.
    # The first call pays a one-shot compile cost; subsequent calls are fast.
    def _mu_step_eager(w_t, h_t, x_t, eps_v: float, do_w: bool, do_h: bool):
        if do_w:
            hht = h_t @ h_t.T
            xht = x_t @ h_t.T
            w_t = w_t * (xht / (w_t @ hht + eps_v))
        if do_h:
            wtw = w_t.T @ w_t
            wtx = w_t.T @ x_t
            h_t = h_t * (wtx / (wtw @ h_t + eps_v))
        return w_t, h_t

    _mu_step = _mu_step_eager
    compiled = False
    if use_compile and not torch_devices.supports_torch_compile(dev):
        logger.info("torch.compile requested but not supported on %s; running eager MU.", dev_label)
    elif use_compile:
        compile_fn = getattr(torch, "compile", None)
        if compile_fn is not None:
            try:
                _mu_step = compile_fn(_mu_step_eager, mode="reduce-overhead", dynamic=False)
                compiled = True
                logger.info("torch.compile registered for MU step (mode=reduce-overhead).")
            except Exception as exc:
                logger.info("torch.compile registration failed (%s); running eager MU.", exc)
                _mu_step = _mu_step_eager
        else:
            logger.debug("use_compile=True but torch.compile is not available in this PyTorch.")

    logger.info(
        "Starting PyTorch NMF MU on %s with data=%s, components=%s, max_iter=%s, update_w=%s, update_h=%s, patience=%s, compiled=%s.",
        dev_label,
        tuple(x.shape),
        n_components,
        max_iter,
        update_w,
        update_h,
        patience,
        compiled,
    )

    # Multiplicative updates for W and H. The reconstruction error is sampled
    # every few iterations and used as the stopping criterion. Convergence is
    # declared only after ``patience`` consecutive below-tolerance samples, so
    # a single noisy iteration cannot trigger an early exit.
    # Note: MU naturally drives entries toward zero to expose sparsity, so we do
    # NOT clamp W/H to >= eps after each update, that would bias the factors
    # away from true zeros. The eps lift on init above is enough to avoid the
    # zero-stuck-zero startup degeneracy.
    converged_iter = None
    iteration = 0
    for iteration in range(1, int(max_iter) + 1):
        try:
            w, h = _mu_step(w, h, x, eps, update_w, update_h)
        except Exception as exc:
            # torch.compile can raise at first execution (e.g. Triton missing
            # on a CUDA PyTorch build that wasn't built with the Inductor /
            # Triton backend). Fall back to eager mode for the rest of the
            # run instead of crashing the analysis.
            if compiled and iteration <= 2:
                logger.warning(
                    "torch.compile execution failed at iter %s (%s). Falling back to eager MU.",
                    iteration, exc,
                )
                _mu_step = _mu_step_eager
                compiled = False
                w, h = _mu_step(w, h, x, eps, update_w, update_h)
            else:
                raise

        if normalize_w_columns:
            scale = torch.clamp(torch.sum(w, dim=0, keepdim=True), min=eps)
            w = w / scale
            h = h * scale.T

        if iteration % track_error_every == 0 or iteration == max_iter:
            residual = x - (w @ h)
            current_error = _frobenius_norm(residual).item()
            history.append(float(current_error))

            if prev_error is not None:
                rel_improvement = (prev_error - current_error) / max(prev_error, eps)
                if rel_improvement <= tol:
                    patience_hits += 1
                    if patience_hits >= patience:
                        converged_iter = iteration
                        logger.info(
                            "PyTorch NMF MU converged at iter=%s with error=%s, rel_improvement=%s "
                            "(below tol=%s for %s consecutive checks).",
                            iteration, current_error, rel_improvement, tol, patience,
                        )
                        break
                else:
                    patience_hits = 0
            prev_error = current_error

    # Return NumPy arrays for the rest of the analysis pipeline.
    w_out = w.detach().cpu().numpy().astype(np.float32, copy=False)
    h_out = h.detach().cpu().numpy().astype(np.float32, copy=False)
    final_error = reconstruction_error(x_np, w_out, h_out)

    info = {
        "algorithm": "mu",
        "device": dev_label,
        "device_kind": torch_devices.device_kind(dev),
        "n_iter": iteration,
        "final_error": final_error,
        "history": history,
        "update_w": bool(update_w),
        "update_h": bool(update_h),
        "patience": int(patience),
        "converged": converged_iter is not None,
        "compiled": bool(compiled),
    }
    return w_out, h_out, info
