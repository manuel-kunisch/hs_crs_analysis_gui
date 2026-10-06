"""Unified PyTorch device detection for the optional accelerated backends.

* ``cuda`` — NVIDIA (and AMD ROCm on Linux, which maps to the CUDA namespace)
* ``mps``  — Apple Silicon Metal
* ``xpu``  — Intel Arc / Intel XPU builds of PyTorch
* ``dml``  — **DirectML** (Windows only): Microsoft's ``torch-directml``
  plugin runs PyTorch on any DirectX-12 GPU, which is the only way to use AMD
  Radeon GPUs — including the integrated Radeon graphics of Ryzen APUs — from
  PyTorch on Windows, where ROCm is not available for those parts. Intel and
  NVIDIA GPUs work through DirectML too, but their native backends are faster
  and therefore take priority.

Priority order when several are present: ``cuda > mps > xpu > dml > cpu``.

Forcing a device
----------------
Set the environment variable ``HS_MOSAIC_TORCH_DEVICE`` to one of
``auto`` (default), ``cpu``, ``cuda``, ``mps``, ``xpu`` or ``dml`` to
override the automatic choice, e.g. to benchmark torch-CPU against DirectML
on the same machine. ``cpu`` makes the analyzer behave like a GPU-less torch
install (torch-CPU NNMF, SciPy NNLS). Requesting an accelerator that is not
available logs a warning and falls back to the automatic order.

DirectML device objects
-----------------------
``torch-directml`` exposes its device as ``torch.device("privateuseone", i)``
rather than a named backend, so device *names* used throughout HS-MOSAIC
(``"dml"``) are translated with :func:`resolve_torch_device`, and labels for
logs / fit summaries go through :func:`device_kind` and :func:`device_label`.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

try:
    import torch
except Exception as exc:  # pragma: no cover - optional dependency
    torch = None
    _TORCH_IMPORT_ERROR: Exception | None = exc
else:
    _TORCH_IMPORT_ERROR = None

# The DirectML plugin only ships Windows wheels. Import it eagerly (guarded)
# so that, like torch itself, its native DLLs are loaded before PyQt is
# imported (see the note at the top of hs_mosaic/app.py).
_torch_directml = None
_DIRECTML_IMPORT_ERROR: Exception | None = None
if torch is not None and sys.platform == "win32":
    try:
        import torch_directml as _torch_directml  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - optional dependency
        _DIRECTML_IMPORT_ERROR = exc

ENV_DEVICE_OVERRIDE = "HS_MOSAIC_TORCH_DEVICE"
ACCELERATOR_PRIORITY: tuple[str, ...] = ("cuda", "mps", "xpu", "dml")
KNOWN_DEVICE_NAMES: tuple[str, ...] = ("cpu",) + ACCELERATOR_PRIORITY

# torch-directml registers its device under PyTorch's generic "private use"
# backend slot; this is the ``torch.device.type`` string it reports.
_DML_DEVICE_TYPE = "privateuseone"

_DML_AVAILABLE_CACHE: bool | None = None
_OVERRIDE_WARNED = False


# ── Availability probes ──────────────────────────────────────────────────────

def torch_available() -> bool:
    return torch is not None


def import_error() -> Exception | None:
    return _TORCH_IMPORT_ERROR


def directml_import_error() -> Exception | None:
    """The exception raised when importing ``torch_directml``, if any.

    ``None`` both when the import succeeded and when it was never attempted
    (non-Windows platforms, or torch itself missing).
    """
    return _DIRECTML_IMPORT_ERROR


def cuda_available() -> bool:
    """True if NVIDIA-CUDA (or AMD-ROCm on Linux) PyTorch is installed and a device is detected."""
    if torch is None:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


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
    """True if Intel-XPU PyTorch is installed and an Intel GPU is detected.
    Requires the IPEX (Intel Extension for PyTorch) or PyTorch >= 2.5 XPU build."""
    if torch is None:
        return False
    xpu = getattr(torch, "xpu", None)
    if xpu is None:
        return False
    try:
        return bool(xpu.is_available())
    except Exception:
        return False


def directml_available() -> bool:
    """True if the ``torch-directml`` plugin is importable and reports at
    least one DirectX-12 adapter. Windows only.

    The adapter enumeration is cached after the first call: it is not free,
    and the GUI polls the backend state on every settings change.
    """
    global _DML_AVAILABLE_CACHE
    if _DML_AVAILABLE_CACHE is not None:
        return _DML_AVAILABLE_CACHE
    result = False
    if _torch_directml is not None:
        try:
            is_avail = getattr(_torch_directml, "is_available", None)
            count_fn = getattr(_torch_directml, "device_count", None)
            available = bool(is_avail()) if callable(is_avail) else True
            count = int(count_fn()) if callable(count_fn) else 1
            result = available and count > 0
        except Exception as exc:
            logger.debug("torch_directml probe failed: %s", exc)
            result = False
    _DML_AVAILABLE_CACHE = result
    return result


_PROBES = {
    "cuda": cuda_available,
    "mps": mps_available,
    "xpu": xpu_available,
    "dml": directml_available,
}


def accelerator_available(name: str) -> bool:
    """Availability of one accelerator by short name (``cuda``/``mps``/``xpu``/``dml``)."""
    probe = _PROBES.get(str(name).lower())
    return bool(probe()) if probe is not None else False


# ── Selection ────────────────────────────────────────────────────────────────

def device_override() -> str | None:
    """Validated value of ``HS_MOSAIC_TORCH_DEVICE`` or ``None`` for automatic."""
    global _OVERRIDE_WARNED
    raw = os.environ.get(ENV_DEVICE_OVERRIDE, "").strip().lower()
    if raw in ("", "auto"):
        return None
    if raw not in KNOWN_DEVICE_NAMES:
        if not _OVERRIDE_WARNED:
            logger.warning(
                "%s=%r is not one of %s; ignoring the override.",
                ENV_DEVICE_OVERRIDE, raw, ("auto",) + KNOWN_DEVICE_NAMES,
            )
            _OVERRIDE_WARNED = True
        return None
    return raw


def available_accelerators() -> list[str]:
    """Accelerators that can be used right now, best first.

    Honours ``HS_MOSAIC_TORCH_DEVICE``: ``cpu`` yields an empty list (so the
    callers treat the machine as GPU-less), a specific accelerator narrows the
    list to that one entry when it is available and otherwise falls back to
    the automatic order with a one-time warning.
    """
    global _OVERRIDE_WARNED
    if torch is None:
        return []
    detected = [name for name in ACCELERATOR_PRIORITY if accelerator_available(name)]
    override = device_override()
    if override is None:
        return detected
    if override == "cpu":
        return []
    if override in detected:
        return [override]
    if not _OVERRIDE_WARNED:
        logger.warning(
            "%s=%r requested but that accelerator is not available (detected: %s); "
            "using the automatic device order instead.",
            ENV_DEVICE_OVERRIDE, override, detected or "none",
        )
        _OVERRIDE_WARNED = True
    return detected


def gpu_available() -> bool:
    """True if ANY GPU-class accelerator is usable: CUDA, MPS, XPU or DirectML."""
    return bool(available_accelerators())


def default_device() -> str:
    """Best available device name. Order: CUDA > MPS > XPU > DirectML > CPU."""
    if torch is None:
        raise RuntimeError("PyTorch is not available.")
    accelerators = available_accelerators()
    return accelerators[0] if accelerators else "cpu"


# ── torch.device translation and labelling ───────────────────────────────────

def resolve_torch_device(name: "str | torch.device | None" = None) -> "torch.device":
    """Turn an HS-MOSAIC device name into a ``torch.device``.

    Accepts the short names ``cpu``/``cuda``/``mps``/``xpu``/``dml`` (with an
    optional ``:index``), any string ``torch.device`` understands, an existing
    ``torch.device``, or ``None`` for :func:`default_device`.
    """
    if torch is None:
        raise RuntimeError(f"PyTorch is not available: {_TORCH_IMPORT_ERROR}")
    if name is None:
        name = default_device()
    if isinstance(name, torch.device):
        return name
    spec = str(name).strip().lower()
    kind, _, index = spec.partition(":")
    if kind == "dml":
        if _torch_directml is None:
            raise RuntimeError(
                "DirectML device requested but the torch-directml package is not importable"
                + (f": {_DIRECTML_IMPORT_ERROR}" if _DIRECTML_IMPORT_ERROR else ".")
            )
        return _torch_directml.device(int(index)) if index else _torch_directml.device()
    return torch.device(spec)


def is_directml_device(device: "torch.device") -> bool:
    return getattr(device, "type", None) == _DML_DEVICE_TYPE


def device_kind(device: "str | torch.device") -> str:
    """Short backend name for a device: ``cpu``, ``cuda``, ``mps``, ``xpu`` or ``dml``.

    This is what the fit summaries use (``backend = "torch-<kind>"``), so the
    opaque ``privateuseone`` type of DirectML devices never leaks into logs.
    """
    if torch is not None and isinstance(device, torch.device):
        return "dml" if is_directml_device(device) else str(device.type)
    return str(device).split(":", 1)[0].strip().lower()


def device_name(kind: str, index: int = 0) -> str | None:
    """Marketing name of the adapter behind an accelerator, if PyTorch exposes it."""
    if torch is None:
        return None
    try:
        if kind == "cuda":
            name = str(torch.cuda.get_device_name(index))
        elif kind == "xpu":
            name = str(torch.xpu.get_device_name(index))
        elif kind == "mps":
            name = "Apple Metal (MPS)"
        elif kind == "dml" and _torch_directml is not None:
            name_fn = getattr(_torch_directml, "device_name", None)
            name = str(name_fn(index)) if callable(name_fn) else "DirectML adapter"
        else:
            return None
    except Exception:
        return None
    # torch-directml returns the raw DXGI adapter description, which carries a
    # trailing NUL and padding whitespace.
    name = name.replace("\x00", "").strip()
    return name or None


def device_label(device: "str | torch.device") -> str:
    """Human-readable device label for log lines, e.g. ``dml:0 (AMD Radeon(TM) Graphics)``."""
    kind = device_kind(device)
    index = 0
    if torch is not None and isinstance(device, torch.device):
        index = int(device.index or 0)
    else:
        _, _, idx = str(device).partition(":")
        if idx.strip().isdigit():
            index = int(idx)
    if kind == "cpu":
        return "cpu"
    name = device_name(kind, index)
    base = f"{kind}:{index}"
    return f"{base} ({name})" if name else base


def supports_torch_compile(device: "str | torch.device") -> bool:
    """Whether ``torch.compile`` is worth attempting on this device.

    DirectML has no Inductor/Triton backend, so compiling would only cost the
    warm-up time and then fall back to eager mode.
    """
    return device_kind(device) != "dml"


# ── Reporting ────────────────────────────────────────────────────────────────

def accelerator_summary() -> dict:
    """Structured availability report used by the backend self-test and the GUI."""
    detected = [name for name in ACCELERATOR_PRIORITY if accelerator_available(name)] if torch else []
    summary = {
        "torch_available": torch_available(),
        "torch_version": getattr(torch, "__version__", None) if torch else None,
        "cuda_available": cuda_available(),
        "mps_available": mps_available(),
        "xpu_available": xpu_available(),
        "directml_available": directml_available(),
        "directml_import_error": None if _DIRECTML_IMPORT_ERROR is None else repr(_DIRECTML_IMPORT_ERROR),
        "detected_accelerators": detected,
        "device_override": device_override(),
        "default_device": default_device() if torch else None,
        "device_names": {name: device_name(name) for name in detected},
    }
    return summary


def describe_accelerators() -> str:
    """One-line human summary for the startup log and tooltips."""
    if torch is None:
        return "PyTorch not installed (CPU paths: scikit-learn NMF, SciPy NNLS)"
    accelerators = available_accelerators()
    if not accelerators:
        note = " (forced by HS_MOSAIC_TORCH_DEVICE=cpu)" if device_override() == "cpu" else ""
        return f"PyTorch {torch.__version__} on CPU, no GPU accelerator detected{note}"
    parts = []
    for name in accelerators:
        adapter = device_name(name)
        parts.append(f"{name} ({adapter})" if adapter else name)
    return f"PyTorch {torch.__version__}, accelerators: " + ", ".join(parts) + f"; using {accelerators[0]}"
