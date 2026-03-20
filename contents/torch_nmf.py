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
    return torch is not None and torch.cuda.is_available()


def import_error() -> Exception | None:
    return _TORCH_IMPORT_ERROR


def default_device() -> str:
    if cuda_available():
        return "cuda"
    if torch_available():
        return "cpu"
    raise RuntimeError("PyTorch is not available.")


def _as_nonnegative_float32(array: np.ndarray, eps: float) -> np.ndarray:
    arr = np.asarray(array, dtype=np.float32)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return np.maximum(arr, eps)


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
) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Factorize X ≈ W @ H with W >= 0 and H >= 0 using multiplicative updates.

    Shapes:
        data  : (n_samples, n_features)
        W     : (n_samples, n_components)
        H     : (n_components, n_features)

    This is the GPU-friendly algorithm to try first in PyTorch. It is usually
    slower to converge than sklearn's coordinate-descent NMF on CPU, but it maps
    cleanly to CUDA because it consists of dense matrix multiplies and pointwise ops.
    """
    if not torch_available():
        raise RuntimeError(f"PyTorch is not available: {_TORCH_IMPORT_ERROR}")

    x_np, n_components, w_init, h_init = _validate_nmf_inputs(data, n_components, w_init, h_init)
    x_np = _as_nonnegative_float32(x_np, eps)

    resolved_device = device or default_device()
    dev = torch.device(resolved_device)
    generator = torch.Generator(device=dev)
    generator.manual_seed(int(seed))

    x = torch.as_tensor(x_np, device=dev)
    n_samples, n_features = x.shape

    if w_init is None:
        w_np = np.random.default_rng(seed).random((n_samples, n_components), dtype=np.float32)
    else:
        w_np = _as_nonnegative_float32(w_init, eps)

    if h_init is None:
        h_np = np.random.default_rng(seed + 1).random((n_components, n_features), dtype=np.float32)
    else:
        h_np = _as_nonnegative_float32(h_init, eps)

    w = torch.as_tensor(w_np, device=dev)
    h = torch.as_tensor(h_np, device=dev)
    w = torch.clamp(w, min=eps)
    h = torch.clamp(h, min=eps)

    if not update_w and not update_h:
        raise ValueError("At least one of update_w or update_h must be True.")

    history: list[float] = []
    prev_error = None
    track_error_every = max(int(track_error_every), 1)

    logger.info(
        "Starting PyTorch NMF MU on %s with data=%s, components=%s, max_iter=%s, update_w=%s, update_h=%s.",
        dev,
        tuple(x.shape),
        n_components,
        max_iter,
        update_w,
        update_h,
    )

    """
    Main loop: iteratively update W and H with multiplicative rules. 
    Optionally track reconstruction error every few iterations and check for convergence based on relative improvement.
    """
    for iteration in range(1, int(max_iter) + 1):
        # Update W: W_ij *= (X @ H^T)_ij / (W @ H @ H^T)_ij
        if update_w:
            hht = h @ h.T
            xht = x @ h.T
            w = w * (xht / (w @ hht + eps))
            w = torch.clamp(w, min=eps)

        # Update H: H_ij *= (W^T @ X)_ij / (W^T @ W @ H)_ij
        if update_h:
            wtw = w.T @ w
            wtx = w.T @ x
            h = h * (wtx / (wtw @ h + eps))
            h = torch.clamp(h, min=eps)

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
                    logger.info(
                        "PyTorch NMF MU converged at iter=%s with error=%s and rel_improvement=%s.",
                        iteration,
                        current_error,
                        rel_improvement,
                    )
                    break
            prev_error = current_error

    # Convert the final W and H matrices back to NumPy arrays on the CPU
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
    }
    return w_out, h_out, info
