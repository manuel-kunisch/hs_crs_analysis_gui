# 02 Analysis modes

This page explains which mode to choose in the GUI and what kind of result to expect. For the mathematical background, see [NNMF and NNLS modes](../reference/nnmf_nnls_modes.md).

## The one-line summary

| Mode | Seeds | Spectra adapt? | Maps adapt? | Best for |
|---|---|---|---|---|
| PCA | none | — | — | First look, artifact check |
| Random NNMF | none | yes | yes | Unguided non-negative exploration |
| Seeded NNMF | H and/or W | yes | yes | Main guided workflow |
| Fixed-H NNLS | H required | **no** | yes | Stable cross-slice comparison |

The modes form a progression: each one uses more prior knowledge and enforces it more strictly.

## Why different modes exist

Hyperspectral data is a stack of many grayscale images over a spectral axis. Chemically meaningful signals, non-resonant background, and acquisition artifacts all overlap in that stack. Looking at slices one by one is slow and often ambiguous.

All analysis modes reorganize the stack into a small set of component spectra and matching spatial maps. The maps can then be shown as false-color composite images. The difference between modes is how much prior knowledge they require and whether they allow the solution to adapt during fitting.

## PCA

PCA is the least guided mode. It finds the directions of strongest variance in the data — not chemically pure components, and not non-negative ones.

Use it as a first diagnostic step: it quickly shows the dominant patterns, often reveals where the main resonances sit, and can expose gradients, background trends, or acquisition artifacts. It is rarely the final result because components can be negative, one molecular signature can be spread across several PCA components, and strong non-chemical variance often dominates.

**When to use:** first look at an unknown dataset, estimating how many meaningful components exist, spotting artifacts before seeded analysis.

## Random NNMF

Random NNMF applies the same additive non-negative model as seeded NNMF, but starts from random initialization instead of user seeds. Both spectra and maps are discovered entirely from the data.

The non-negativity constraint makes the result physically easier to interpret than PCA — components are additive contributions rather than signed variance directions. The downside is that results can depend on initialization, especially in low-SNR data.

**When to use:** when no seed spectra are available yet, to get a first non-negative decomposition, or to generate candidate components that can later be imported back as seeds for a more guided run.

## Seeded NNMF

This is the main workflow mode. It uses the same non-negative factorization as random NNMF, but starts from seeds you provide — ROI spectra, loaded reference spectra, Gaussian resonance models, or maps from a previous result. The seeds are initial conditions, not hard constraints: both spectra and maps are still updated during fitting.

Seeded NNMF is the best compromise for most real datasets. It is more stable and interpretable than random NNMF because the initialization steers it away from chemically meaningless local optima. It is less rigid than fixed-H NNLS, so it can still adapt if your seeds are only approximate.

When only spectral seeds are given, the GUI estimates spatial starting maps automatically. The W-seed mode dropdown controls how: `nnls` fits coefficient maps from the seeded spectra (default, usually best), `selective_score` is a heuristic that downweights pixels already well explained by other components, and `average`/`empty` are neutral fallbacks. See [Seeds, spectra, and W maps](03_seeds_spectral_and_spatial.md) for details.

**When to use:** whenever approximate resonances or ROI spectra are available — which is the normal case once you have looked at the data with PCA or random NNMF.

## Fixed-H NNLS

Fixed-H NNLS is the strictest mode. The spectra are locked to the provided seeds and cannot change. Only the spatial abundance maps are fitted, independently for each pixel.

This makes results directly comparable across z slices, time points, or fields of view because the spectral basis is the same everywhere. The trade-off is that the mode is only as good as the supplied spectra — if a seed spectrum is wrong, the map will be mathematically consistent but scientifically misleading. Results can also look grainier than NNMF maps. Because the exact H is forced as the spectral basis, every pixel must be explained using only those fixed spectra — there is no freedom to let the basis shift slightly to better fit local variations. That strictness is the point of the mode, but it means spatial noise is not absorbed by small spectral adjustments the way it can be in NNMF. Grainier maps are not a sign of a worse fit; they are a direct consequence of holding H fixed.
If the images look too grainy, consider switching to seeded NNMF mode.

**When to use:** after seeded NNMF has given you a trusted spectral basis, for 4D series where a common basis across slices is important, or when spectra must stay exactly fixed.

## Recommended workflow

For most datasets, the practical sequence is:

1. Run **PCA** for a first overview of variance and possible resonances.
2. Run **Random NNMF** if no seeds exist yet, to get a first non-negative decomposition.
3. Import useful result components or draw ROIs to build seeds.
4. Run **Seeded NNMF** for the main guided analysis.
5. Once the spectral basis looks stable, switch to **Fixed-H NNLS** for cross-slice comparison or 4D workflows.

## Advanced settings

The analysis panel exposes several settings that affect how NNMF and NNLS run internally. They are all saved in the preset.

**NNMF solver** — two update rules are available: *Multiplicative Update (mu)*, the default, is reliable and enforces non-negativity at every step; *Coordinate Descent (cd)* can be faster on some datasets but is less commonly needed.

**Backend** — the GUI options are *Automatic*, *CPU only*, and *Prefer GPU*. With the multiplicative-update solver, *Automatic* uses the PyTorch/CUDA backend when CUDA is available and falls back to scikit-learn; *CPU only* uses the scikit-learn CPU backend; *Prefer GPU* requests PyTorch/CUDA and falls back to CPU if CUDA is unavailable. Coordinate Descent always uses the scikit-learn CPU backend. See [GPU acceleration](02a_gpu_acceleration.md).

**Iteration limits** — *NNMF max iterations* and *NNLS max iterations* both default to 1000. Increase them if the fit summary shows the solver has not converged; decrease them to speed up exploratory runs.

**Custom initialization** — forces NNMF to use the seeded W and H matrices without any rescaling beforehand. Enable this when the seeds are already on the right amplitude scale and you do not want the initializer to modify them.

**Scale results to 16-bit** — applies a single global scale factor so the maximum W value across all components equals 65535. Useful for display and histogram control; does not affect the underlying fit. See [Results and export](05_results_and_export.md#result-data-types-and-w-scaling).

**Fast multislice NNMF** *(4D data only)* — runs full seeded NNMF on one reference slice and applies fixed-H NNLS to all remaining slices. Faster than running NNMF on every slice and keeps the spectral basis consistent across the series. Disable it if per-slice spectral adaptation is important.

## What to read next

- [Seeds, spectra, and W maps](03_seeds_spectral_and_spatial.md) — how to build better seeds
- [NNMF and NNLS modes](../reference/nnmf_nnls_modes.md) — mathematical background
- [Quickstart](../quickstart.md) — jump straight to a working workflow
