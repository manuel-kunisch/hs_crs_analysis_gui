import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import torch
except Exception as exc:  # pragma: no cover - optional dependency
    torch = None
    _TORCH_IMPORT_ERROR = exc
else:
    _TORCH_IMPORT_ERROR = None


def torch_available() -> bool:
    return torch is not None


def cuda_available() -> bool:
    """True if NVIDIA-CUDA PyTorch is installed and a CUDA device is detected."""
    return torch is not None and torch.cuda.is_available()


def mps_available() -> bool:
    """True if Apple-Metal-Performance-Shaders (MPS) PyTorch is built and a
    Metal device is detected. Supported on Apple Silicon (M1/M2/M3/M4) Macs
    with macOS 12.3+ and a PyTorch build that includes the MPS backend
    (the standard PyPI macOS wheel does include it)."""
    if torch is None:
        return False
    mps = getattr(torch.backends, "mps", None)
    if mps is None:
        return False
    is_avail = getattr(mps, "is_available", None)
    is_built = getattr(mps, "is_built", None)
    try:
        return bool(is_avail and is_avail() and is_built and is_built())
    except Exception:
        return False


def xpu_available() -> bool:
    """True if Intel-XPU PyTorch is installed and an Intel GPU is detected.
    Requires the IPEX (Intel Extension for PyTorch) or PyTorch ≥ 2.5 XPU build."""
    if torch is None:
        return False
    xpu = getattr(torch, "xpu", None)
    if xpu is None:
        return False
    try:
        return bool(xpu.is_available())
    except Exception:
        return False


def gpu_available() -> bool:
    """True if ANY GPU-class accelerator is detected: CUDA, MPS, or XPU."""
    return cuda_available() or mps_available() or xpu_available()


def import_error() -> Exception | None:
    return _TORCH_IMPORT_ERROR


def default_device() -> str:
    """Pick the best available device. Order: CUDA > MPS > XPU > CPU."""
    if cuda_available():
        return "cuda"
    if mps_available():
        return "mps"
    if xpu_available():
        return "xpu"
    if torch_available():
        return "cpu"
    raise RuntimeError("PyTorch is not available.")


def _as_nonnegative_float32(array: np.ndarray) -> np.ndarray:
    # NMF requires inputs >= 0, not strictly > 0. The init paths below add a
    # separate eps lift for W and H to dodge the multiplicative-update
    # zero-stuck-zero issue.
    arr = np.asarray(array, dtype=np.float32)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return np.maximum(arr, 0.0)


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
    can run on either CPU or CUDA through PyTorch.

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
    evolving. The first iteration pays a one-time compile cost (~5-10 s) that
    amortises across all subsequent iterations and is well worth it for 4D
    stacks where the same shape is processed many times.
    """
    if not torch_available():
        raise RuntimeError(f"PyTorch is not available: {_TORCH_IMPORT_ERROR}")

    x_np, n_components, w_init, h_init = _validate_nmf_inputs(data, n_components, w_init, h_init)
    x_np = _as_nonnegative_float32(x_np)

    resolved_device = device or default_device()
    dev = torch.device(resolved_device)
    # Device-specific Generator (currently unused — random inits below go
    # through NumPy — but kept seeded for future torch.rand calls that might
    # be added). Some backends (notably older MPS) raise here, so swallow it.
    try:
        generator = torch.Generator(device=dev)
        generator.manual_seed(int(seed))
    except (RuntimeError, TypeError) as exc:
        logger.debug("torch.Generator(device=%s) not available: %s — skipping.", dev, exc)
        generator = None  # noqa: F841

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
    if use_compile:
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
        dev,
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
            current_error = torch.linalg.norm(residual, ord="fro").item()
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
        "device": str(dev),
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
