# Changelog

All notable user-facing changes to HS-MOSAIC are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/).

## [0.9.4] — 2026-05-28

### Added
- **Performance: W-seed spatial downsampling** (measured 1.4–6.4× speedup
  on the seed-initialisation step depending on mode and factor). A new
  **W-seed downsample** spinbox in the *Performance* column lets users
  compute the per-pixel NNLS or selective-score W-seed on a 1/factor²
  smaller copy of the data and bilinear-upsample the result back to full
  resolution. Because the W seed only has to initialise the NMF iterations
  (which then refine W to full quality), the speedup is essentially free.

  Measured on a 1024×1024×32 dataset, k=4, NVIDIA CUDA RTX4060 GPU:

  | factor | NNLS abundance | Selective score | Quality (cos sim vs full-res) |
  |---|---|---|---|
  | 1 (no downsample) | 0.81 s — | 2.19 s — | reference |
  | 2 | 0.57 s **(1.4×)** | 1.03 s **(2.1×)** | 0.9999 |
  | 4 (default) | 0.45 s **(1.8×)** | 0.48 s **(4.5×)** | 0.9999 |
  | 8 | 0.32 s **(2.5×)** | 0.34 s **(6.4×)** | 0.9997 |

  Default is **4** (fast; ~0.9999 cosine similarity to the full-resolution
  seed). Set **1** for no downsampling to reproduce the pre-v0.9.4 seed
  exactly; raise to **8** for very large mosaics. The downsample auto-skips
  when the image is too small for the factor. Applies to W-seed
  initialization **and** to residual-fallback
  H-seed estimation (the per-pixel NNLS used to build a seed for components
  with no ROI / file / Gaussian spectrum) for NNMF runs — same factor,
  same ~0.9999 cosine similarity to the full-resolution seed, spectral axis
  preserved by the block-mean, and component-masked / non-full-frame data
  automatically skips the optimization to preserve correctness. The GUI's
  Fixed-H NNLS reconstruction also builds its W maps through this W-seed
  path, so the factor affects those *final* maps too (they are upsampled
  and therefore look blurry); the GUI warns and offers to reset the factor
  to 1 when you start a Fixed-H NNLS run with a factor > 1. The low-level
  ``solve_fixed_H_nnls`` used in 4D-hybrid mode always runs at full
  resolution.

  All three Performance-column settings (W-seed downsample factor,
  early-stop patience, torch.compile flag) are now persisted in the
  application JSON preset under a ``"performance_settings"`` block.
  Legacy presets (v0.9.3 and earlier) that lack this block restore to the
  behaviour-preserving fallback (downsample=**1**, patience=1, compile=False)
  so they reproduce v0.9.2 numerical behaviour byte-for-byte — note this
  fallback intentionally keeps downsample=1 even though a fresh session now
  defaults to 4, so a shared legacy preset reproduces its original seed.

- **Performance: NMF early-stop tunables + optional torch.compile.** A new
  **Performance** column in the Analysis panel exposes two opt-in solver
  knobs for the PyTorch MU NMF path. Neither is a speedup by default;
  both are tools for users with specific workloads to tune themselves.
    * **Early-stop patience** (default **1**, matches pre-v0.9.4 behavior
      exactly, no regression). The MU solver already had early stopping in
      v0.9.2; v0.9.4 lets you raise the patience to **2 or 3** if your
      data has noisy convergence and the previous "exit at first below-tol
      check" behavior was triggering too eagerly. Higher patience trades
      a few extra iterations for noise robustness. It is **not** itself a
      speedup, and on smooth-converging data it actually runs slightly
      longer than patience=1.
    * **torch.compile (MU)** opt-in checkbox (default off). When enabled,
      wraps the MU update body in ``torch.compile()`` to fuse the matmul
      and pointwise ops into single kernels.
      If the active PyTorch build cannot compile (e.g. a CUDA build
      without Triton, or older MPS), the solver logs a warning and
      silently falls back to eager execution. No crash, no wrong
      results, no perf change.

- **Performance: NNMF and NNLS convergence-tolerance controls.** The
  *Performance* column also exposes two editable dropdowns — **NNMF
  tolerance** and **NNLS tolerance** — pre-filled with the ladder
  ``1e-1 … 1e-7`` (type any custom value, e.g. ``5e-5``). They set the
  relative-improvement tolerance of the PyTorch MU NNMF solver and the
  relative-step tolerance of the PyTorch FISTA NNLS solver, respectively.
  Tighten to 1e-5 / 1e-6 for publication-grade fits; loosen to 1e-3 for
  fast CPU exploration. Both default to **1e-4**, matching pre-v0.9.4
  numerical behaviour, and are persisted in the application JSON preset
  under ``performance_settings.torch_nmf_tol`` and
  ``performance_settings.torch_nnls_tol``. Legacy presets that lack these
  keys restore to 1e-4. The controls affect only the PyTorch backends; the
  scikit-learn NMF path and SciPy Lawson–Hanson NNLS path are unchanged.
  (Implemented as editable ``QComboBox`` widgets rather than a custom
  ``QDoubleSpinBox`` subclass, which segfaulted on Windows + Python 3.12 +
  PyQt5 through SIP's virtual dispatch.)

### Changed
- **NNMF Backend dropdown simplified from three options to two.** The
  legacy **Automatic** item was removed because it had identical behavior
  to **Prefer GPU**: both tried the first available GPU accelerator
  (CUDA, then MPS, then XPU) and silently fell back to CPU torch if no
  GPU was detected. The dropdown now offers only the two functionally
  distinct choices:
    * **Prefer GPU** (default): try CUDA > MPS > XPU, fall back to CPU
      torch if no GPU is present, with a log message indicating the
      fallback. This is what the old **Automatic** option also did.
    * **CPU only**: skip the PyTorch MU path entirely and run the
      scikit-learn MU NMF on CPU (not torch CPU). Useful for benchmarking,
      reproducibility against the scikit-learn reference, or when the GPU
      is busy elsewhere.

  **Coordinate Descent (cd)** always runs on the scikit-learn CPU backend
  regardless of this setting.

  **Backwards compatibility.** Presets saved by v0.9.3 with
  `nnmf_backend: "auto"` continue to load without changes. The setter
  accepts `"auto"` as a silent alias for `"gpu"` (functionally identical),
  and the GUI maps a loaded `"auto"` value to the **Prefer GPU** dropdown
  item. No legacy preset breaks; the change is purely cosmetic in the
  dropdown.

  The corresponding `_resolve_torch_nmf_device` logic was simplified
  accordingly, removing the previously-dead branch that distinguished
  `"gpu"` from `"auto"`.

- **Physical Units tab redesigned.** The previously sparse tab is now
  organised into *Calibration*, *Scale Bar*, and a new read-only *Image
  Details* panel (dimensions, megapixels, field of view, pixel size in nm,
  and imaged area), with live unit suffixes and top-left layout alignment.
  No change to calibration behaviour or the preset format.


## [0.9.3] — 2026-05-25

### Added
- **Color-blind-safe component palette.** Two new bidirectionally-synced
  **Palette** dropdowns (one in the result-viewer toolbar next to *Save
  Histogram and Spectra Preset*, one in the ROI Manager next to *Load
  Lookup Table and Spectra Preset*) let users switch between the new
  default **Okabe-Ito** palette (designed for protanopia and deuteranopia; Wong, *Nat. Methods* **8**, 441, 2011),
  a **High-Contrast** palette (also designed for colour vision deficiencies), and the legacy
  **Classic RGB** palette that HS-MOSAIC shipped before v0.9.3. The
  selected palette is persisted in the application JSON preset.
  Custom palettes can be added by editing the `PALETTES` /
  `PALETTE_LABELS` dictionaries in `hs_mosaic/widgets/color_manager.py`
  — see *Results and export → Default colour palette → Adding a custom
  palette* in the docs.
- **Apple Silicon (MPS) and Intel Arc (XPU) GPU acceleration.** The
  PyTorch NNMF and NNLS backends now pick a device in priority order
  **CUDA → MPS → XPU → CPU** instead of the previous CUDA-only check.
  Apple Silicon Macs (M1/M2/M3/M4) get hardware acceleration via the
  PyTorch MPS backend automatically — the standard PyPI macOS torch wheel
  already includes MPS, so `pip install hs-mosaic torch` is the entire
  setup. Intel Arc GPUs are detected via `torch.xpu.is_available()` when
  an XPU-enabled PyTorch is installed. New `mps_available()`,
  `xpu_available()` and `gpu_available()` helpers are exposed alongside
  the existing `cuda_available()` in both `hs_mosaic/widgets/torch_nmf.py`
  and `hs_mosaic/widgets/nnls_pytorch.py`. The fit-summary `backend` label
  now reports `torch-mps` or `torch-xpu` accordingly. The Lipschitz-constant
  `torch.linalg.eigvalsh` call in fixed-H NNLS is wrapped in a defensive
  CPU fallback so older PyTorch MPS builds (≤ 2.0) don't error out on it.
  CUDA remains the primary tested platform; MPS and XPU support is
  dispatch-clean but throughput depends on PyTorch's own op coverage for
  the hardware.

### Changed
- **Default component-colour palette switched to Magenta–Cyan–Yellow.**
  Fresh sessions and new analyses now use the additive-secondary trio
  (magenta + cyan + yellow) as components 1, 2, 3 by default, with five
  supplementary colours filling slots 4–8. This palette gives the highest
  three-way contrast on a black composite background of any three-colour
  combination. The previous "High contrast" magenta-green palette and the
  Okabe-Ito palette remain available in the dropdown. Per-component colour
  choices made with the colour pickers (and colours loaded from any
  `.preset`) always override the palette and are not affected.
- **Palette dropdown now shows `(customized)` when colours diverge from the
  active palette's baseline.** Modifying any component colour via the
  picker tags the current palette in both dropdowns as e.g.
  *"Magenta–Cyan–Yellow (max contrast) (customized)"*; switching palette
  or re-applying the same palette resets the tag. The custom colour values
  themselves persist through preset save/load via the existing ROI and
  histogram serialisation, so a customised palette round-trips through
  `Save Preset` / `Load Preset` correctly.
- **Confirmed minimum Python version is 3.10.**
- Renamed the Windows launcher from `hs_mosaic.bat` to `hs-mosaic.bat` for
  consistency with the PyPI package name (`hs-mosaic`) and the console-script
  command (`hs-mosaic`).
- README and docs now use absolute URLs for embedded images and cross-links
  so they render correctly on the PyPI project page in addition to GitHub.
- **Renamed the optional `[gpu]` install extra to `[torch]`.** The previous
  name was misleading: PyPI only hosts CPU PyTorch, so `pip install
  "hs-mosaic[gpu]"` never gave GPU acceleration — it just added the
  PyTorch backend running on CPU. The new `[torch]` name reflects what is
  actually installed. For real NVIDIA-CUDA GPU acceleration, the
  recommended path is now to install CUDA-enabled torch from PyTorch's
  index **first**, then `pip install hs-mosaic`; see the *CUDA-enabled
  PyTorch* section of the installation docs. **Breaking change for v0.9.2
  users who scripted `pip install "hs-mosaic[gpu]"`** — they need to
  switch to `[torch]` or drop the extra entirely. A one-command recovery
  path is documented in README → Install → PyPI.

### Backwards compatibility
- Application JSON presets saved before v0.9.3 do **not** carry a
  `palette_name` field. When such a legacy preset is loaded, HS-MOSAIC
  falls back to the **Classic RGB** palette, preserving the visual identity
  of the original session. New presets always serialise the active palette
  name explicitly.

## [0.9.2] — 2026-05-24

### Added
- The application is now distributable as a pip-installable Python package
  (`pip install hs-mosaic`), with an `hs-mosaic` console entry point that
  launches the GUI without invoking a script directly.
- Optional dependency extras: `[gpu]` (CPU PyTorch backend for MU-NMF and
  FISTA-NNLS) and `[dev]` (PyInstaller, ruff, pytest).
- `python -m hs_mosaic` is supported as an equivalent module-style launch.

### Changed
- Source restructured into a single top-level package, `hs_mosaic/`, with
  the previous `contents/` directory becoming `hs_mosaic/widgets/`, and
  the previous root-level `main.py` and `composite_image.py` moving inside
  the package. Bundled assets (logo, etc.) moved to `hs_mosaic/assets/`.
- PyInstaller spec files and the Windows launcher updated to match the new
  layout; standalone Windows builds (`HS_MOSAIC_*_v0.9.2.zip`) regenerated.
- Documentation install and launch commands updated throughout (`README.md`,
  `docs/installation.md`, `docs/quickstart.md`, `docs/troubleshooting.md`,
  `docs/examples/synthetic_quickstart.md`, `docs/standalone_windows.md`).

### Removed
- Two leftover learning scripts (`pyqt_overview.py`, `pyqtgraph_test.py`)
  that were never imported by the application.

## [0.9.1] — 2026

Last release before the package restructure. Adds the live "Composite (from
analysis)" projection mirror in the raw image viewer, the Save / Load
Histogram and Spectra Preset workflow for cross-FOV reproducibility,
documentation polish (Essentials TL;DR, stitching internals, results page),
and assorted seed-construction and stitching improvements (cosine blending
profile, per-tile intensity matching, H-seed unity normalisation).

## [0.9.0] — 2026

Initial public release of HS-MOSAIC: seeded NNMF and fixed-H NNLS for
hyperspectral and multispectral microscopy data, with optional NVIDIA-CUDA
PyTorch backend and 4D processing support.
