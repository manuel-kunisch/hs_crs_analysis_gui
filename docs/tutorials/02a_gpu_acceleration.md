# 02a GPU Acceleration

The GUI can use optional PyTorch backends for selected NNMF and NNLS paths. If PyTorch or CUDA is not available, the analysis falls back to CPU implementations where supported.

## What Can Use The GPU

GPU acceleration is currently relevant for:

- multiplicative-update NNMF through the PyTorch backend;
- batched fixed-H NNLS through the PyTorch/CUDA NNLS backend.

The coordinate-descent NNMF solver uses the scikit-learn CPU backend.

## Backend Selection

The analysis panel contains backend options for NNMF. Depending on the selected solver and backend preference, the app can:

- automatically choose a backend,
- force CPU-only behavior,
- prefer GPU if available.

When GPU execution is not available or fails, the code logs the fallback and continues with a CPU backend where possible.

> Screenshot placeholder: NNMF solver/backend dropdowns and iteration settings.

## CUDA Requirements

For NVIDIA GPU acceleration, the important requirement is a CUDA-enabled PyTorch installation. In most cases, the full CUDA Toolkit is not required just to run the GUI. A compatible NVIDIA driver and CUDA-enabled PyTorch wheel/conda package are usually sufficient.

Check CUDA availability with:

```bash
python -c "import torch; print(torch.cuda.is_available()); print(torch.version.cuda)"
```

If this prints `True`, the PyTorch CUDA paths should be available to the GUI.

## What To Report In A Paper Or Tutorial

When documenting an analysis, report:

- solver,
- backend,
- maximum iterations,
- whether fixed-H NNLS was used,
- whether GPU acceleration was available,
- final error or iteration summary when relevant.

This makes runtime and reproducibility easier to interpret.
