import logging
from typing import Callable, Optional

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
    """True if Apple-Metal (MPS) PyTorch is built and a Metal device is detected.
    Supported on Apple Silicon Macs with macOS 12.3+ and a PyTorch build that
    includes the MPS backend (the standard PyPI macOS wheel does)."""
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
    """True if Intel-XPU PyTorch is installed and an Intel GPU is detected."""
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


def solve_batched_nnls_projected_gradient(
        image_data: np.ndarray,
        basis: np.ndarray,
        *,
        device: Optional[str] = None,
        max_iter: int = 250,
        tol: float = 1e-4,
        eps: float = 1e-8,
        chunk_size: int = 32768,
        use_acceleration: bool = True,
        progress_callback: Optional[Callable[[], None]] = None,
) -> tuple[np.ndarray, dict]:
    """
    Solve the fixed-H NNMF subproblem for W with a batched PyTorch NNLS solver.

    With the hyperspectral data matrix X and seeded spectra H kept fixed, this
    estimates the non-negative abundance matrix W by solving

        W = argmin_{W >= 0} ||X - W H||_F^2 .

    This is the same NNLS problem as in the SciPy backend, but solved in
    batches with projected-gradient updates and optional FISTA acceleration.

    For each pixel spectrum x_p, the abundance vector w_p is obtained from

        w_p = argmin_{w_p >= 0} ||x_p - w_p H||_2^2 .

    In the implementation, ``basis`` stores the seeded spectra as columns, so
    ``basis = H^T`` and the solved form is

        w_p = argmin_{w_p >= 0} ||basis @ w_p - x_p||_2^2 .
    """
    if not torch_available():
        raise RuntimeError(f"PyTorch is not available: {_TORCH_IMPORT_ERROR}")

    resolved_device = device or default_device()
    dev = torch.device(resolved_device)

    x_np = np.asarray(image_data, dtype=np.float32)
    x_np = np.nan_to_num(x_np, nan=0.0, posinf=0.0, neginf=0.0)
    x_np = np.maximum(x_np, 0.0)

    b_np = np.asarray(basis, dtype=np.float32)
    b_np = np.nan_to_num(b_np, nan=0.0, posinf=0.0, neginf=0.0)
    b_np = np.maximum(b_np, 0.0)

    if x_np.ndim != 2 or b_np.ndim != 2:
        raise ValueError("image_data and basis must be 2D arrays.")
    if x_np.shape[1] != b_np.shape[0]:
        raise ValueError(
            f"Incompatible shapes for batched NNLS: {x_np.shape=} and {b_np.shape=}."
        )

    basis_t = torch.as_tensor(b_np, device=dev)
    gram = basis_t.T @ basis_t
    diag = torch.diag(gram)
    # Lipschitz-constant estimation for the FISTA step size.
    # `torch.linalg.eigvalsh` is supported on CUDA and CPU, and on MPS since
    # PyTorch 2.1 (with possible internal CPU fallback for some shapes). On
    # older builds or unsupported devices, fall back to a one-off CPU compute
    # — gram is k×k where k = #components (≤ ~10), so the cost is negligible.
    # TODO: forces a device→CPU synchronization via .item(); can we estimate
    # this more cheaply for very small k?
    try:
        max_eig = torch.linalg.eigvalsh(gram).amax().item()
    except (NotImplementedError, RuntimeError) as exc:
        logger.debug(
            "torch.linalg.eigvalsh failed on device %s (%s); using CPU fallback.",
            dev, exc,
        )
        max_eig = torch.linalg.eigvalsh(gram.detach().cpu()).amax().item()
    step = 1.0 / max(max_eig, eps)

    n_pixels, _ = x_np.shape
    n_components = b_np.shape[1]
    chunk_size = max(int(chunk_size), 1)
    abundance = np.zeros((n_pixels, n_components), dtype=np.float32)
    chunk_iterations: list[int] = []
    total_residual_sq = 0.0

    logger.info(
        "Running PyTorch NNLS solver on %s with %s pixels, %s components, chunk_size=%s, max_iter=%s.",
        dev,
        n_pixels,
        n_components,
        chunk_size,
        max_iter,
    )

    for start in range(0, n_pixels, chunk_size):
        if progress_callback is not None:
            try:
                progress_callback()
            except Exception:
                logger.debug("NNLS progress callback failed.", exc_info=True)
        stop = min(start + chunk_size, n_pixels)
        x_chunk = torch.as_tensor(x_np[start:stop], device=dev)
        c = x_chunk @ basis_t

        # Diagonal-scaled non-negative initialization converges faster than zeros.
        a = torch.clamp(c / (diag.unsqueeze(0) + eps), min=0.0)
        y = a.clone()
        t = 1.0

        iterations_used = max_iter
        for iteration in range(max_iter):
            if progress_callback is not None and iteration % 10 == 0:
                try:
                    progress_callback()
                except Exception:
                    logger.debug("NNLS progress callback failed.", exc_info=True)
            grad = y @ gram - c
            a_next = torch.clamp(y - step * grad, min=0.0)

            if use_acceleration:
                t_next = 0.5 * (1.0 + (1.0 + 4.0 * t * t) ** 0.5)
                y = a_next + ((t - 1.0) / t_next) * (a_next - a)
                t = t_next
            else:
                y = a_next

            if iteration % 10 == 0 or iteration == max_iter - 1:
                delta = torch.linalg.norm(a_next - a)
                base = torch.linalg.norm(a) + eps
                if (delta / base).item() <= tol:
                    a = a_next
                    iterations_used = iteration + 1
                    break

            a = a_next

        # Inner loop already clamps each update to >= 0, so a is non-negative here.
        abundance[start:stop] = a.detach().cpu().numpy()
        residual = x_chunk - (a @ basis_t.T)
        total_residual_sq += float(torch.sum(residual * residual).item())
        chunk_iterations.append(int(iterations_used))

    info = {
        "algorithm": "projected_gradient_nnls",
        "device": str(dev),
        "n_pixels": int(n_pixels),
        "n_components": int(n_components),
        "chunk_size": int(chunk_size),
        "max_iter": int(max_iter),
        "tol": float(tol),
        "n_chunks": int(len(chunk_iterations)),
        "chunk_iterations": chunk_iterations,
        "max_chunk_iter": int(max(chunk_iterations)) if chunk_iterations else 0,
        "mean_chunk_iter": float(np.mean(chunk_iterations)) if chunk_iterations else 0.0,
        "final_error": float(total_residual_sq ** 0.5),
    }
    return abundance, info
