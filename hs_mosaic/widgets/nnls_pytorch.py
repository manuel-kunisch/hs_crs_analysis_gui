import logging
from typing import Callable, Optional

import numpy as np

from hs_mosaic.widgets import torch_devices

logger = logging.getLogger(__name__)

# ``torch`` is optional; see torch_devices for the guarded import.
torch = torch_devices.torch
_TORCH_IMPORT_ERROR = torch_devices.import_error()

# Device probes live in ``torch_devices`` since DirectML support was added;
# these thin aliases keep the historical ``nnls_pytorch.*`` API working.
torch_available = torch_devices.torch_available
cuda_available = torch_devices.cuda_available
mps_available = torch_devices.mps_available
xpu_available = torch_devices.xpu_available
directml_available = torch_devices.directml_available
gpu_available = torch_devices.gpu_available
import_error = torch_devices.import_error
default_device = torch_devices.default_device


def _l2_norm(tensor):
    """Euclidean norm over all elements, accurate on every device.

    ``torch.sum`` reduces with a cascaded (pairwise) algorithm on all
    backends, whereas ``torch.linalg.norm`` on the CPU build accumulates
    sequentially in float32 and loses accuracy on large inputs (see
    ``torch_nmf._frobenius_norm``). The chunk-level norms here are small, but
    using the same accurate form keeps CPU / CUDA / DirectML consistent.
    """
    return torch.sqrt(torch.sum(tensor * tensor))


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

    ``device`` accepts the short names understood by
    :func:`hs_mosaic.widgets.torch_devices.resolve_torch_device` (``cpu``,
    ``cuda``, ``mps``, ``xpu``, ``dml``); ``None`` picks the best available.
    """
    if not torch_available():
        raise RuntimeError(f"PyTorch is not available: {_TORCH_IMPORT_ERROR}")

    dev = torch_devices.resolve_torch_device(device)
    dev_label = torch_devices.device_label(dev)

    # Row-major layout matters: torch-CPU matmuls on Fortran-ordered inputs
    # are pathologically slow and DirectML re-orders them on every upload.
    # np.ascontiguousarray is a no-op for arrays that are already C-ordered.
    x_np = np.asarray(image_data, dtype=np.float32)
    x_np = np.nan_to_num(x_np, nan=0.0, posinf=0.0, neginf=0.0)
    x_np = np.ascontiguousarray(np.maximum(x_np, 0.0))

    b_np = np.asarray(basis, dtype=np.float32)
    b_np = np.nan_to_num(b_np, nan=0.0, posinf=0.0, neginf=0.0)
    b_np = np.ascontiguousarray(np.maximum(b_np, 0.0))

    if x_np.ndim != 2 or b_np.ndim != 2:
        raise ValueError("image_data and basis must be 2D arrays.")
    if x_np.shape[1] != b_np.shape[0]:
        raise ValueError(
            f"Incompatible shapes for batched NNLS: {x_np.shape=} and {b_np.shape=}."
        )

    basis_t = torch.as_tensor(b_np, device=dev)
    gram = basis_t.T @ basis_t
    diag = torch.diag(gram)
    # Lipschitz constant for the FISTA step size: the largest eigenvalue of
    # the k×k Gram matrix (k = #components, typically <= 10). Symmetric
    # eigensolvers are LAPACK territory that not every backend implements
    # (DirectML has none, older MPS builds fall back internally), and the
    # matrix is tiny, so compute it on the CPU unconditionally. The
    # device->host copy is a few hundred bytes and happens once per solve.
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
        dev_label,
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
                delta = _l2_norm(a_next - a)
                base = _l2_norm(a) + eps
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
        "device": dev_label,
        "device_kind": torch_devices.device_kind(dev),
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
