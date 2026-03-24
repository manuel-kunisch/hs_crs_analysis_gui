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
) -> np.ndarray:
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
    # TODO: forces a GPU → CPU synchronization. Can we estimate this more cheaply?
    max_eig = torch.linalg.eigvalsh(gram).amax().item()
    step = 1.0 / max(max_eig, eps)

    n_pixels, _ = x_np.shape
    n_components = b_np.shape[1]
    chunk_size = max(int(chunk_size), 1)
    abundance = np.full((n_pixels, n_components), eps, dtype=np.float32)

    logger.info(
        "Running PyTorch NNLS solver on %s with %s pixels, %s components, chunk_size=%s, max_iter=%s.",
        dev,
        n_pixels,
        n_components,
        chunk_size,
        max_iter,
    )

    for start in range(0, n_pixels, chunk_size):
        stop = min(start + chunk_size, n_pixels)
        x_chunk = torch.as_tensor(x_np[start:stop], device=dev)
        c = x_chunk @ basis_t

        # Diagonal-scaled non-negative initialization converges faster than zeros.
        a = torch.clamp(c / (diag.unsqueeze(0) + eps), min=0.0)
        y = a.clone()
        t = 1.0

        for iteration in range(max_iter):
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
                    break

            a = a_next

        abundance[start:stop] = torch.clamp(a, min=eps).detach().cpu().numpy()

    return abundance
