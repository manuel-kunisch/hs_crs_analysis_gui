# Scripted NNMF (HS-MOSAIC custom mode)

Run HS-MOSAIC's seeded NNMF on any 3D hyperspectral stack from a script, with the
same seeding options the GUI offers: **spatial seeds (ROIs), spectral seeds, and
VCA**, plus W-seed mode, W-seed downsampling, unity normalization and all solver
settings.

Please check the [GUI's NNMF documentation](https://manuel-kunisch.github.io/hs_crs_analysis_gui/) for the theory and the meaning of the parameters.

The scripting runs `MultivariateAnalyzer` through the same call sequence the GUI's analysis
manager uses, so a scripted run reproduces a GUI run.

```
nnmf_scripting/
├── hs_nnmf/                    the library
│   ├── config.py               Roi, SpectralSeed, VcaParams, NNMFParams
│   ├── runner.py               run_nnmf() + NNMFResult
│   ├── data_io.py              TIFF + wavelength.json loading
│   ├── plotting.py             W maps, composite, H components, ROI overview
│   └── binlets_bridge.py       optional binlets denoising (experimental)
├── 01_random_nnmf.py           random init, no seeds
├── 02_custom_seeds_nnmf.py     ROI seeds from coordinate indices (+ ROI overview)
├── 03_vca_nnmf.py              VCA seeds
├── 04_binlets_nnmf.py          binlets denoising, then ROI-seeded NNMF (experimental)
├── 05_binlets_4d.py            binlets denoising in 4D (experimental)
└── selftest.py                 synthetic check, no data needed, test your python installation here
```

The numbered scripts have no CLI: open one, edit the `SETTINGS` block at the top
(dataset, `NNMFParams`, ROIs) and hit run. Each saves its figures to
`results/<name>/` **and** shows them on screen.

## Where the data goes

The scripts name their dataset instead of hard-coding a path:

```python
DATA = data_path("2017_03_23_Lungcells_Day2_..._HS_CARS_ch-1_C.tif")
```

`data_path()` looks in, in order: the path as given, `$HS_NNMF_DATA` (this is a path variable you have to define once), and
`nnmf_scripting/data/` (one level of subfolders included). So drop the files into
`data/`, or point `HS_NNMF_DATA` at wherever the measurements live, and the
scripts run unchanged on any machine.

**Copy `wavelength.json` along with the TIFF.** It carries the spectral axis;
without it the axis silently falls back to frame indices and everything is
plotted against band number instead of cm⁻¹. See [data/README.md](data/README.md).

## Setup

Requires the HS-MOSAIC dependencies (numpy, scipy, scikit-learn, scikit-image,
tifffile, matplotlib). PyTorch is optional — with a GPU it is much faster, without
it everything falls back to scikit-learn automatically.

```bash
conda activate py312_nnmf_pytorch      # or py312_nnmf (CPU only)
python selftest.py                     # 15 checks, a few seconds, no data needed
```

`hs_mosaic` does not need to be installed. The package finds the checkout it
lives in; if you copy this folder somewhere else, set `HS_MOSAIC_ROOT` to the
`hs_crs_analysis_gui` directory.

## Quickstart

```python
from hs_nnmf import load_dataset, NNMFParams, Roi, run_nnmf, save_figures

stack, wavenumbers, unit = load_dataset("my_stack.tif")   # (bands, Y, X)

params = NNMFParams(
    n_components=3,
    init="custom",
    rois=[
        Roi.from_center(0, y=348, x=150, size=9, name="lipid droplets"),
        Roi.from_center(1, y=196, x=372, size=15, name="nucleus"),
        Roi(component=2, rect=(15, 20, 30, 40), name="NRB", is_background=True),
    ],
)

result = run_nnmf(stack, wavenumbers, params, spectral_unit=unit)
print(result.summary())

result.save("out")                       # W TIFF, H CSV, run JSON
save_figures(result, "out", show=True)   # save PNG+PDF and show the windows
```

`show=True` leaves the figures open and calls `plt.show()`, so anything else you
plotted first (a ROI overview, say) pops up in the same call.

`result.W` is `(n_pixels, k)`, `result.H` is `(k, n_bands)` (rows are spectra),
`result.W_2D` is `(k, Y, X)`.

## Seeding

| method | how | GUI equivalent |
|---|---|---|
| **random** | `init="random"` | custom-init checkbox off |
| **spatial (ROI)** | `rois=[Roi(...)]` | draw ROIs, assign to components |
| **VCA** | `vca=VcaParams(enabled=True)` | "Suggest spectra (VCA)" |
| **spectral** | `spectral_seeds=[SpectralSeed(...)]` | resonance table row |
| **explicit spectra** | `h_seeds={0: array}` | — (scripting only) |
| **fixed W map** | `fixed_w_seeds={2: array}` | ROI with a fixed W image |

Priority when several apply, matching the GUI: `h_seeds` > `rois` > `vca` >
the analyzer's own fallback (residual-NNLS spectrum, else smoothed random).
Anything you do not seed is filled in automatically, so partial seeding is fine.
Seed the two components you know and let VCA or the fallback handle the rest.

An `Roi` takes a region in any of three forms, and several ROIs on the same
component are averaged (as `get_roi_mean_curves` does in the GUI):

```python
Roi.from_center(0, y=348, x=150, size=9)          # square around a pixel index
Roi(component=1, rect=(y0, x0, height, width))     # rectangle
Roi(component=2, pixels=[(2, 2), (60, 61)])        # explicit coordinate indices
Roi(component=2, mask=bool_array_YX)               # arbitrary region
```

`sigma`, `scale`, `offset`, `is_background` mirror the ROI table columns.

Check where the seeds actually landed before trusting a run: this is what
`02_custom_seeds_nnmf.py` shows first:

```python
from hs_nnmf import plot_roi_overview
plot_roi_overview(stack, ROIS, n_components=3)   # mean projection + ROI outlines
```

## Parameters

All of these are `NNMFParams` fields, set in the `SETTINGS` block of each script.

| field | default | meaning |
|---|---|---|
| `n_components` | 3 | number of components |
| `w_seed_mode` | `"nnls"` | `nnls`, `selective_score`, `h_weighted`, `average`, `empty` |
| `w_seed_downsample` | 4 | compute W seeds on a 1/f² smaller image, then upsample (1 = full res) |
| `normalize_h_to_unity` | True | scale each H seed row to peak 1 before fitting |
| `normalize_w_seed` | True | scale each W seed column to peak 1 |
| `overwrite_w_from_h` | True | recompute W seeds from H even where a W seed exists |
| `background_components` | `()` | components treated as non-resonant background |
| `background_roi` | None | ROI whose mean spectrum is subtracted to make the "subtracted data" used for seeding |
| `solver` | `"mu"` | `mu` (multiplicative updates) or `cd` |
| `backend` | `"gpu"` | `gpu` = torch (CUDA/MPS/XPU, else CPU torch); `cpu` = scikit-learn |
| `max_iter` / `tol` / `patience` | 500 / 1e-4 / 1 | solver stopping; `patience` = consecutive below-tol checks |
| `nnls_max_iter` / `nnls_tol` | 500 / 1e-4 | NNLS abundance solve used for W seeds |

The defaults match the HS-MOSAIC GUI. The scripts use `patience=3` (the torch
solver's own default) because it costs ~2 s and settles a little further.

## The lung-cell example

The three scripts are preconfigured for
`2017_03_23_Lungcells_Day2_..._Pos2_HS_CARS_ch-1_C.tif`: 84 bands × 512 × 512,
spectral axis 3082.8 → 2632.3 cm⁻¹ (from the `wavelength.json` sidecar: pump
tuned 801.2–831.2 nm against a fixed 1064 nm Stokes beam). Three components:
lipids, proteins/nuclei, non-resonant background.

The ROI seeds in `02_custom_seeds_nnmf.py` are plain coordinate indices picked
from the data: component 0 on two lipid-droplet clusters (sharp 2850 cm⁻¹ CH₂
peak), component 1 on three nuclei (the large smooth round structures, highest
2930/2850 ratio in the stack), component 2 on the cell-free corners where the
spectrum is the flat non-resonant background.

Runtime on a CUDA GPU is ~1–3 s per fit; the ROI seeding (NNLS abundance maps at
downsample 4) takes ~1 s.

**What the three runs show.** All three converge to essentially the same
reconstruction error (relative error 0.337–0.339) but *not* to the same
factorization! 

That is the practical point of seeding: NMF has many equally good factorizations
of this data, and the seeds decide which one you land on, not how well the model
fits. **Do not read a lower reconstruction error as a better decomposition!**

> ***The whole magic lies in the seeding process!***

Component order is arbitrary in the unsupervised runs. To line them up with the
seeded run so component 0/1/2 mean the same thing everywhere:

```python
aligned = vca_result.match_to(roi_result.H)   # cosine similarity, one-to-one
```

## Figures

`save_figures()` writes three figures per run (PNG + PDF): the **W components**
with a composite panel, the **W seeds**, and the **H components** with their
seeds overlaid dashed. `plot_roi_overview()` adds the mean projection with the
seed ROIs drawn on it, and `plot_composite()` the full-size composite.

### Composite

The composite is a **true RGB array** handed to a single `imshow`, no
matplotlib alpha compositing anywhere (as in alpha versions of HS-MOSAIC). `mode="additive"` (the default) is what
HS-MOSAIC's composite view and FIJI do: normalize each map between its levels,
map it through a black → color LUT, and *sum* the channels, so the background is
black and overlaps brighten toward white. `mode="multiply"` is the subtractive
alternative on white — better for print, washed out on screen.

`percentile`, `low_percentile` and `gamma` each take one value for all
components **or one value per component** — the scripting equivalent of the
per-channel histogram levels in the GUI. A component that covers the whole field
(the NRB, typically) washes the composite out until its black level is raised:

```python
from hs_nnmf import plot_composite, save_composite_image

plot_composite(result, mode="additive", low_percentile=(0, 0, 70), gamma=1.0)
save_composite_image(result, "out/composite_rgb.png", low_percentile=(0, 0, 70))
```

`save_composite_image()` writes a pixel-exact RGB PNG (one output pixel per data
pixel, no axes, no resampling): the equivalent of exporting the composite
straight out of the GUI viewer.

```python
from hs_nnmf import CLASSIC_COLORS
save_figures(result, "out", colors=CLASSIC_COLORS)
```

## binlets (experimental)

`04_binlets_nnmf.py` denoises with [binlets](https://github.com/maurosilber/binlets)
before the NNMF. Needs `pip install binlets`; verified against binlets 1.0.0.

### Which axis to bin

Binning commutes with the mixing model on *either* axis — spatially
`B(WH) = (BW)H` leaves H untouched, spectrally `(WH)P = W(HP)` leaves W
untouched. So "which axis preserves the model" does **not** pick a domain.

What picks it is where the redundancy is and what you can afford to lose. On the
lung-cell stack the spectrum is only ~2× oversampled (autocorrelation half-width
11 cm⁻¹ at 5.43 cm⁻¹/band) while the lipid droplets sit at the spatial sampling
limit. So the spectral axis is used as **evidence** for each spatial merge
decision (`joint_channels=True` pools χ² over all 84 bands) rather than being
averaged away — you get the benefit of the spectral redundancy without paying
spectral resolution for it.

Denoise on raw counts, before any nonlinear preprocessing (ratios, normalization,
background division); binlets bins adaptively, so flat regions get large bins
while droplets and edges keep full resolution.

### Noise model (this matters for a PMT)

binlets uses an **unnormalized** Haar wavelet, so at decomposition `level` the
two coefficients handed to the test are *sums of N = 2^level raw pixels*. For a
detector with per-pixel `var = gain·mean + offset`:

```
var(x)     = gain·x + N·offset
var(x − y) = gain·(x + y) + 2·N·offset
```

The shot term is level-independent — that is why photon-counting data needs no
level correction (`gain=1, offset=0`). A **current-mode PMT** is different: its
read/dark/digitisation floor is a real constant per pixel, so it accumulates with
bin size and must be carried through the levels. `gain` here is `F·g` in ADU per
photoelectron, with F the dynode excess-noise factor — measure it, never assume it:

```python
from hs_nnmf import estimate_noise_model, binlets_denoise

model = estimate_noise_model(stack)          # fits var = gain*mean + offset
denoised = binlets_denoise(stack, gain=model.gain, offset=model.offset,
                           n_sigma=3.0, levels=3)
result = run_nnmf(denoised, wavenumbers, params)
```

On the day-2 stack the fit gives `var ≈ 543·mean + 4.2e6`, i.e. a read-noise floor
that *dominates* the shot term at typical levels; the day-1 stack fits
`var ≈ 289·mean + 0`. Sanity check: on a synthetic pure-Poisson stack the same
estimator returns `offset = 0`, so a large offset is a real property of the
detector, not an artifact.

**The fit is calibrated before it is returned.** A raw transfer-curve fit is
biased high — real image structure leaks into the per-bin noise floor, badly so
in low-contrast images (2.6× too large on the day-1 stack, 1.15× on day-2). An
inflated variance makes the test call every pair consistent, so it bins
everything and `n_sigma` stops doing anything at all — that is the symptom to
watch for. `estimate_noise_model` therefore rescales the fit so that on flat
parts of the image the pairwise statistic follows its χ²₁ null (median 0.4549).
Pass `calibrate=False` to see the raw fit.

### Choosing n_sigma

`n_sigma` is how far into the upper tail of the χ²ₖ null a merge is still
accepted (the pooled test uses `k + n_sigma·√(2k)`, not `n_sigma²·k` — the latter
puts the cut at the *mean* of the null, i.e. a coin flip). It is
**dataset-dependent**; measured against each raw stack:

| n_sigma | day 2 (droplets) | day 1 idler-filter | day 1 pos 1 |
|---|---|---|---|
| 1.0 | — | −35 % / 100.0 % | −67 % / 99.7 % |
| 2.0 | −10 % / 99.9 % | −62 % / 99.9 % | **−87 % / 99.4 %** |
| 3.0 | −25 % / 99.7 % | **−82 % / 99.8 %** | −96 % / 99.0 % |
| 5.0 | **−65 % / 99.5 %** | −98 % / 99.5 % | −99 % / 98.4 % |
| 8.0 | −92 % / 98.9 % | — | — |

(noise reduction / contrast retained; bold = the value used for that dataset)

Contrast survives because the test refuses to bin across real structure. The
required `n_sigma` differs by a factor of two or more between fields, so do not
carry a value across datasets.

Measure contrast **away from object boundaries**. A mask-based contrast measured
right at the edge drops by 10-20 % even when nothing is wrong, because binning
legitimately smooths the one-pixel transition itself: on the day-1 pos-1 field
the naive number said −12.7 % while the same comparison eroded by 9 px said
−0.3 %.

### Reading the residual panel

The residual in `<name>_denoise_check.png` is the main check, but read it
correctly. For shot-noise-limited data the residual **amplitude is supposed to
follow the brightness**, because the variance does: a faint imprint of the
structure is visible in how strong the speckle is, and that is not a defect. On
the mouse-liver stack the correlation between the local residual *standard
deviation* and the signal is 0.63, which is the expected Poisson behaviour.

What must not appear is a **sign-coherent** residual: outlines, edges or whole
objects that are consistently one colour, meaning the denoised image sits
systematically below or above the raw one there. Quantitatively that is the
correlation between the local residual *mean* and the signal; on the same stack
the bias is 0.26 % of signal at `n_sigma=3`. If you see coherent edges, lower
`n_sigma`.

Denoising takes ~17 s for 84 × 512 × 512. Note that the NNMF relative error drops
(0.339 → 0.226) simply because there is less noise left to explain — that is
**not** evidence of a better decomposition.


## Outputs

`result.save(dir)` writes:

| file | contents |
|---|---|
| `<name>_W_components.tif` | `(k, Y, X)` uint16 stack, one global scale factor (opens in FIJI) |
| `<name>_H_spectra.csv` | wavenumber column + one column per component |
| `<name>_H_seeds.csv` | the seed spectra the fit started from |
| `<name>_run.json` | every parameter, seed source per component, solver info, timings |

`save_figures()` adds `<name>_W_components`, `<name>_W_seeds` and
`<name>_H_components` as PNG and PDF. The scripts additionally write
`<name>_composite.png` (the figure) and `<name>_composite_rgb.png` (pixel-exact
RGB); `02_custom_seeds_nnmf.py` also writes `<name>_roi_overview.png`.

`04_binlets_nnmf.py` additionally writes `<name>_denoised.tif` — the denoised
stack itself, same shape and dtype as the input, so it opens in FIJI or reloads
into HS-MOSAIC as an ordinary hyperspectral stack — and
`<name>_denoise_check.png`, the raw / denoised / residual QC panel.
