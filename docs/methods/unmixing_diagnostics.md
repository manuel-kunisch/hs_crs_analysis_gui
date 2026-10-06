# Unmixing diagnostics: effective rank and separability

Since version 0.9.8 the GUI answers two questions that previously required external analysis or trial and error:

1. **How many components can this dataset support at all?** More components than the data carries will fit noise, not chemistry.
2. **Can the current component spectra actually be told apart?** Two spectra can be perfectly valid on their own and still be so similar that no algorithm separates them at realistic noise levels.

Both are computed by the same diagnostics engine and shown in three places: a status line in the Analysis panel, a status line under the ROI table, and a status line in the seed/result viewer. A shared **Unmixing Diagnostics** window holds the full detail behind them.

The important conceptual point first: the two questions are different, and mixing them up is the most common source of confusion in spectral unmixing [1]. Question 1 is a property of the *data* (how many independent directions it contains above the noise). Question 2 is a property of the *spectra* (how much each one differs from every combination of the others). A dataset can support five components while the chosen five spectra are still inseparable, and a well-separated pair of spectra is useless if the data only carries one direction of variation.

![The GUI with the synthetic quickstart dataset loaded and the Unmixing Diagnostics window open on the Dataset tab. The headline reads K_eff of about 5 in green, the scree plot shows five singular values clearly above the dashed noise floor followed by a flat noise plateau, and the status line under the Components spinbox in the Analysis panel reads K_eff of 5 with 5 requested.](../assets/images/diagnostics_analysis_badge.png)

*The synthetic quickstart dataset, which is built from exactly five components. Five singular values stand clearly above the noise floor, the rest form a flat plateau on it, and the status line under the Components spinbox agrees with the request: $K_\mathrm{eff} \approx 5$ with 5 requested, shown in green. Note the estimated noise ($\sigma \approx 395$) is above the true simulated value of 280, inflated by the bead texture as described below, yet the component count is still exact because the signal singular values sit orders of magnitude above the floor. Requesting more components than $K_\mathrm{eff}$ turns the line red.*

## Question 1: how many components does the data support?

### The idea

The data matrix $X \in \mathbb{R}_{\ge 0}^{n_\mathrm{pixels} \times n_\mathrm{channels}}$ (see [NNMF and NNLS modes](nnmf_nnls_modes.md) for the layout) has one hard limit: every pixel spectrum is just $n_\mathrm{channels}$ numbers, so the whole stack cannot hold more than $n_\mathrm{channels}$ independent patterns. In practice noise erodes that number further.

The tool for counting patterns is the singular value decomposition (SVD) [2]. It answers a simple question: which independent patterns are needed to rebuild this dataset, and how strongly does each one contribute? The answer comes sorted by strength, one number per pattern, the singular values. What remains is deciding where in that sorted list real signal ends and noise begins.

Noise makes that decision harder than just counting nonzero values, because noise alone never produces zeros: random fluctuations partially align by chance, and with more pixels and channels those chance alignments grow. So the real question is how large a singular value pure chance can produce. That question has an exact answer, worked out by Marchenko and Pastur for matrices containing nothing but randomness [3, 4]: feed the SVD a stack of pure noise with standard deviation $\sigma$ and its largest singular value lands almost exactly at

$$
\sigma_\mathrm{max}^\mathrm{noise} \approx \sigma \left( \sqrt{n_\mathrm{pixels}} + \sqrt{n_\mathrm{channels}} \right).
$$

Chance alignment reaches this level and no further. That turns the value into a ceiling: any singular value of the measured data that lies **above** it cannot be produced by noise and must belong to signal. Counting these values gives the effective rank

$$
K_\mathrm{eff} = \#\left\{ i : \sigma_i > \sigma \left( \sqrt{P} + \sqrt{C} \right) \right\},
$$

which is the number the GUI reports. Requesting more components than $K_\mathrm{eff}$ does not make the analysis fail; the extra components just have nothing left to describe except noise.

### Why the noise level is channel dependent

The threshold needs the noise level $\sigma$, and in spectral data there is no single such number. A detector pixel follows the usual camera model [5]

$$
\sigma_c^2(x) \;=\; \underbrace{\sigma_\mathrm{read}^2}_{\text{read noise}}
\;+\; \underbrace{D\,t}_{\text{dark current}}
\;+\; \underbrace{g\, S(x, \lambda_c)}_{\text{shot noise}} ,
$$

and the shot term ties the noise to both the channel and the pixel. A channel sitting on a strong resonance collects the most photons and therefore has the largest *absolute* noise, yet the best SNR, because the signal grows linearly while the noise only grows as $\sqrt{S}$. Background signal is the unpleasant case: autofluorescence, the non-resonant background, or solvent bands add photons, and with them shot noise, exactly at their emission channels, without adding any usable contrast. On top of that, detector quantum efficiency (for camera-based detection) and per-channel excitation power vary with $\lambda$. A single global $\sigma$ is therefore always an approximation. The GUI offers two estimators, selectable on the Dataset tab; the second one removes at least the channel dependence.

### Noise estimation

**Automatic (Immerkær).** Estimating noise from an image that also contains signal needs a trick, because the plain standard deviation of the pixels measures signal contrast, not noise. The trick [6] is to look at the image through a filter that signal cannot pass. Each channel is convolved with the 3×3 kernel

$$
N \;=\; \begin{pmatrix} 1 & -2 & 1 \\ -2 & 4 & -2 \\ 1 & -2 & 1 \end{pmatrix},
$$

built so that any patch that is locally a plane, a brightness value plus a linear ramp in x and y, sums to exactly zero. At the three-pixel scale most real structures are close to such planes, so the convolution erases them. Noise is different: it jumps independently from pixel to pixel, no plane fits it, and it survives the filter. What comes out is therefore nearly pure noise, only rescaled: for pixel-independent noise of standard deviation $\sigma$ the output has standard deviation $6\sigma$ (the root of the summed squared kernel entries). Hence

$$
\sigma \;=\; \sqrt{\tfrac{\pi}{2}} \, \cdot \, \frac{\mathrm{mean}\,\lvert I * N \rvert}{6} .
$$

The mean absolute value is used instead of a standard deviation because it is far less sensitive to the few large outliers that sharp edges produce; the factor $\sqrt{\pi/2}$ converts it back to a standard deviation. The GUI runs this on every channel and takes the median across channels.

The failure mode follows directly from the assumption: anything that is *not* locally a plane, i.e. sharp edges, puncta, pixel-scale texture, leaks through the kernel and inflates the estimate. The bias is one-sided: an inflated $\sigma$ raises the threshold and lowers $K_\mathrm{eff}$, so the reported rank errs on the conservative side, never the optimistic one.

**From a background ROI.** Any ROI whose **Background** box is checked in the ROI Manager doubles as a noise region. Inside a region that contains no signal, no trick is needed: the standard deviation of the raw pixels *is* the noise, measured separately for every channel. That last part is the real gain. The Marchenko–Pastur edge assumes equal noise in every channel, which real channels (different exposure, gain, filter throughput) rarely deliver. With the per-channel values $\sigma_c$ the data is **whitened** before the SVD: every channel is divided by its own noise level, so each one is measured in units of its own noise and the edge applies exactly with $\sigma = 1$. Remote-sensing hyperspectral analysis uses the same trick under the name minimum noise fraction transform [7]. Without whitening, one channel with above-average noise is enough to push a pure-noise direction over the threshold and fake a component.

One safeguard is built in. A standard deviation estimated from $N$ pixels is itself uncertain by about $\sigma/\sqrt{2N}$, and the edge is sharp enough that a slightly underestimated $\sigma$ lets borderline noise through. The threshold is therefore inflated by $1 + \sqrt{2/N}$, and the tab warns when the region holds fewer than 200 pixels.

The two estimators fail in opposite directions, which makes their comparison a diagnostic in itself. The automatic estimate measures noise where the signal is, so signal-dependent (shot) noise is included, but texture inflates it. A dark region contains only read and dark noise, so for shot-noise-limited data it underestimates the noise present in bright areas; and if the "empty" region is not actually empty (tissue autofluorescence is the classic case), structure inflates it instead. The Dataset tab therefore always shows both values side by side and warns when they differ by more than a factor of two, and the direction of the gap says which failure it is. If the background estimate is the *higher* one, the "empty" region almost certainly contains structure and the ROI should be moved. If the automatic estimate is the *higher* one, the noise is signal-dependent (or texture inflates the automatic value); the background estimate is then the optimistic one and reports more components than the bright regions actually support, so the smaller automatic $K_\mathrm{eff}$ is the safer number.

When a background ROI exists it is used by default; the selector switches back to the automatic estimate at any time. When no reliable noise estimate is possible at all, the dialog falls back to explained-variance criteria.

### The Dataset tab

![The Dataset tab on a lung-cell CARS dataset with the noise source set to a background ROI. The headline reads K_eff of about 60 with 3 requested. The scree plot shows whitened singular values, most of them slightly above the dashed noise floor. The summary line reports the ROI sigma of about 676 next to the Immerkaer value of about 873, the variance cross-check reads 4 components for 99 percent, and an amber warning says the region holds only 189 noise pixels.](../assets/images/diagnostics_dataset_tab.png)

*The Dataset tab on a lung-cell CARS stack, deliberately showing a case where the background-ROI estimate goes wrong, together with the guards that catch it. The noise source is a small background ROI (189 pixels, the amber warning below the summary fires), its $\sigma \approx 676$ sits below the Immerkær value of $\approx 873$, and the whitened test then lets 60 of 84 singular values over the floor. The variance cross-check tells the real story: 99 % of the data is reproduced by 4 components, and the bend of the scree curve sits in the same region. When the ROI-based $K_\mathrm{eff}$ and the variance count disagree this strongly, the noise is signal-dependent and the ROI value is the optimistic one; enlarge the region or switch the selector back to the automatic estimate.*

The plot carries a second, older estimate that needs no noise model at all. Singular values of real components fall off steeply from one to the next; noise values are all of similar size and form a flat tail. The component count is where the steep part bends into the flat part. Reading the plot this way is Cattell's scree test [8], and it is where the plot's name comes from: the flat tail is the scree, the rubble at the foot of a cliff. The bend and $K_\mathrm{eff}$ are complementary because they fail independently. The bend reads the shape of the curve and survives a wrong noise estimate; the threshold reads the level and survives a mushy bend, for example when a smooth background makes the falloff gradual. When both agree, trust the number. When they disagree, as in the screenshot above, suspect the noise estimate first.

The tab reports, in order:

- the headline $K_\mathrm{eff}$, colored red when the Components spinbox currently requests more,
- the noise source selector (automatic, or a background ROI when one is marked),
- the scree plot with the noise floor; when a background ROI drives the estimate, the plotted singular values are the whitened ones and the axis says so,
- pixel and channel counts, the active noise $\sigma$ next to the other estimator's value for comparison, and a rough global SNR (median positive signal over $\sigma$),
- the component counts needed to reproduce 99 % and 99.9 % of the total variance in the data, as a cross-check that does not depend on the noise model.

The SVD is the only potentially expensive computation in the diagnostics, so it runs on demand: the first time the window is opened, and again after **Refresh**. The result is cached against the dataset content. Loading a new dataset invalidates the cache; the status line then drops its $K_\mathrm{eff}$ part until the window is opened again, rather than showing numbers that belong to the previous dataset. An open window refreshes itself on data load.

## Question 2: can these spectra be told apart?

### Separability is a geometric property

Write the component spectra as rows $s_1, \dots, s_K$ of the matrix $H$. Unmixing a pixel means deciding how much of each spectrum is present in its measured channel vector. That decision is easy when the spectra point in clearly different directions and becomes ambiguous when one spectrum can be imitated by a combination of the others.

The quantity that measures this, per component, is

$$
\eta_k = \sin \angle\!\left( s_k,\ \mathrm{span}\{ s_j \}_{j \neq k} \right)
       = \left\| \hat{s}_k - P_{\mathrm{others}}\, \hat{s}_k \right\|,
$$

where $\hat{s}_k$ is the unit-normalized spectrum and $P_\mathrm{others}$ projects onto the subspace spanned by all other (normalized) spectra. In words: **$\eta_k$ is the fraction of component $k$'s spectral fingerprint that no combination of the other components can imitate.** It ranges from 1 (orthogonal to everything else, trivially separable) to 0 (an exact linear combination of the others, not separable at all).

Note what $\eta$ is *not*: it is not the pairwise similarity between two spectra. A component can be reasonably different from each individual partner and still be almost perfectly imitated by a combination of three of them. $\eta$ tests against the whole set at once, which is the situation the solver actually faces.

### Why $\eta$ sets the reconstruction quality

When the abundances are solved (whether inside NNMF or by fixed-H NNLS [9]), noise in the data is amplified along the poorly separated directions. The factor is not a heuristic: for a least-squares fit with equal noise in every channel, the standard deviation of the fitted coefficient is exactly $\sigma / (\lVert s_k \rVert\, \eta_k)$, a classical regression result known as variance inflation [10]. NNLS inherits it wherever a component is genuinely present, because the non-negativity constraint is then inactive. So the signal-to-noise ratio that matters for the abundance of component $k$ is not the raw image SNR but scales with $\eta_k$:

$$
\mathrm{SNR}^\mathrm{eff}_k = \eta_k \cdot \mathrm{SNR}^\mathrm{raw} .
$$

The reason is the geometry of the fit. Signal along directions that the other spectra can also produce proves nothing about component $k$: the fit could attribute it to either side. The only evidence for $a_k$ lies along the unique remainder of $s_k$, and that remainder has length $\eta_k$. So the usable signal shrinks by $\eta_k$ while the noise along that direction keeps its full strength. For two spectra separated by an angle $\theta$ this can be computed exactly: the noise on the fitted coefficient is $\sigma / \sin\theta$, and $\eta = \sin\theta$. The picture to keep is two nearly parallel lines: move one of them slightly and their intersection point slides far along both, with $1/\sin\theta$ as the lever arm.

A useful rule of thumb: about 10 % relative abundance accuracy requires $\eta_k \cdot \mathrm{SNR} \gtrsim 10$. The **SNR for 10 %** column in the GUI is exactly this relation solved for the raw SNR, $10/\eta_k$. The approximations sit in the ingredients, not in the $1/\eta_k$ itself: the GUI's raw SNR is one global estimate rather than a per-pixel amplitude, the noise is assumed equal across channels, and near zero abundance the non-negativity constraint clips the error one-sidedly. The column therefore ranks components correctly, and its failures are on the safe side.

The same factor amplifies errors in the spectra themselves. Seed spectra are never exact: they come from ROIs, reference measurements, or a previous fit. That calibration error propagates into the abundances as

$$
\frac{\Delta a}{a} \sim \frac{1}{\eta_k} \cdot \frac{\Delta H}{H} .
$$

For a component with $\eta = 0.05$ a 2 % error in its reference spectrum already produces roughly a 40 % abundance error, independent of how good the measurement SNR is. This is why improving a nearly collinear pair by "measuring the references more carefully" does not work; the geometry has to change, which in practice means adding or changing spectral channels.

### The Separability tab

![The Separability tab of the Unmixing Diagnostics window with three ROI seed rows from a lung-cell dataset, all graded marginal in amber. The table lists eta, the amplification factor, the most similar partner, the cosine similarity, the SNR required for ten percent accuracy, and the verdict. The headline reads min eta of 0.139 for ROI 2. The pairwise cosine similarity heatmap on the right shows bright off-diagonal cells.](../assets/images/diagnostics_separability_tab.png)

*Three ROI seeds on the lung-cell CARS stack, all graded marginal. The weakest is ROI 2 (the protein seed): only 14 % of its fingerprint is unique ($\eta = 0.139$), its closest partner is ROI 3, the non-resonant background, at a cosine similarity of 0.972, and 10 % abundance accuracy would need a raw SNR of 72 while the Dataset tab reports about 13. Reading the two tabs together says this seed set will not unmix cleanly as it stands; the next section fixes exactly this pair. The condition number of 15.4 summarizes the same situation in one number.*

The table has one row per component:

| Column | Meaning |
| --- | --- |
| **Component** | The component name from the ROI table, tinted with its display color. |
| **eta** | $\eta_k$ as defined above: the unique fraction of this spectrum. 1 is orthogonal, 0 is not separable. |
| **1/eta** | The noise and calibration-error amplification the solver pays for this component. |
| **Closest to** | The single other component this one resembles most. When a component is in trouble, this column names the culprit. |
| **max cos** | The cosine similarity to that closest partner (1.0 means identical shape). This is the pairwise view; eta is the stricter test against all others combined. |
| **SNR for 10 %** | The raw image SNR needed for roughly 10 % abundance accuracy, $10/\eta_k$. Compare it with the global SNR reported on the Dataset tab. |
| **Verdict** | A coarse grade of eta. **good**: $\eta \geq 0.30$, comfortable. **marginal**: $\eta \geq 0.10$, works with good SNR and clean references. **critical**: below 0.10, expect unreliable abundances. **empty**: the component has no seed spectrum yet (an all-zero row). |

Below the table the dialog prints the condition number of the spectral matrix. That is the one-number summary of the same story: the worst-case factor by which noise and spectral errors get amplified when solving with this set of spectra. Values near 1 are ideal; values in the hundreds mean at least one component is nearly redundant. When applicable, two warnings follow that deserve their own explanation:

**More components than channels.** When $K > C$ the spectra are necessarily linearly dependent, so at least one $\eta_k$ is exactly zero and mixed pixels have no unique solution. This does not make such a configuration useless: spectra can still be *identified* from the data when every component has near-pure pixels somewhere in the image (the assumption behind VCA seeding, see [Suggest spectra (VCA)](../tutorials/03d_suggest_spectra_vca.md) [14]), and pixels containing at most $\lfloor C/2 \rfloor$ overlapping components remain uniquely solvable: a pixel delivers $C$ measured numbers, and as long as no more than half that many components are actually present in it, no two different component combinations can explain the same measurement [11]. But per-pixel abundances in regions where many components overlap are not trustworthy in this regime [12, 13].

> Detection and localization can exceed the channel count. Quantification cannot.

**A component with critical $\eta$.** The warning names the component and states the amplification factor. The productive reaction is usually not a brighter exposure but a change of geometry: an additional spectral channel in which the critical pair differs, or dropping/merging one member of the pair.

> A dim channel that separates the pair is worth more than a bright channel that repeats what the other channels already measure.

## When no pure pixel exists: Purify seed

Seeding methods pick spectra from pixels, so they can only ever return the purest pixel that exists. In many biological samples that pixel is still a mixture: a **nucleus is always covered by cytoplasmic lipid above and below it**, so every "nucleus" ROI you can draw yields nucleus plus lipid. Both spectra are non-negative, which leaves a way out. If the target component has a channel where it is essentially dark while the contaminant emits (the lipid CH₂ band near 2850 cm⁻¹ is the classic case), then the largest multiple of the contaminant that can be subtracted before any channel goes negative,

$$
b^* = \min_c \; \frac{s_\mathrm{mixed}[c]}{s_\mathrm{ref}[c]}
\qquad \text{over channels where } s_\mathrm{ref} \text{ emits,}
$$

lands exactly on the pure target spectrum: $s_\mathrm{pure} = s_\mathrm{mixed} - b^*\, s_\mathrm{ref}$. This is an extrapolation to the non-negativity boundary, not a fit, and it needs no pure pixel of the target anywhere in the image. It does need a pure (or already purified) seed of the *contaminant*, which usually exists: the cytoplasm without the nucleus.

The reference is the one input that has to be trusted, and it fails gracefully in one direction and visibly in the other. If the reference carries some of the *target* itself, the subtraction still lands on the correct target shape and only its amplitude shrinks (the anchor channel is unaffected, so $b^*$ stays right); since seed scale is free anyway, this costs little, and it is the reason a mutually mixed pair can be purified one after the other. If the reference carries a *third* component, that component is subtracted into the result where it does not belong and gets clipped at zero: flat zero stretches in the purified curve, at channels where the third component emits, are the visible tell to pick a cleaner reference region.

The **Purify seed…** button under the ROI table implements this. Pick the mixed row as target and the contaminant row as reference; the dialog shows the mixed spectrum, the scaled reference being subtracted, and the purified result, together with the component's separability before and after. That $\eta$ line is the success indicator: if it does not improve, the chosen reference was not what contaminated the seed. In practice the minimum above is taken as a low quantile of the channel ratios so that a single noisy channel cannot cap the subtraction too early, and channels where the reference is below 5 % of its maximum are excluded from the ratio.

![The Purify seed dialog with ROI 2 selected as mixed target and ROI 3 as the reference to remove, the subtraction slider at 100 percent. The plot shows the gray mixed spectrum, the dashed scaled reference being subtracted, and the green purified result. Below the plot a line reports the component's eta improving from 0.140 to 0.364.](../assets/images/diagnostics_purify_dialog.png)

*Purifying the protein seed from the Separability tab above: target is ROI 2, reference is ROI 3, the non-resonant background that contaminated it. The purified spectrum (green) is the mixed seed (gray) minus the largest admissible multiple of the reference (dashed); the broad background pedestal is gone while the CH-region structure survives. The separability line confirms it worked: $\eta$ rises from 0.140 to 0.364, from marginal across the good threshold.*

Three caveats. First, the subtraction slider exists because the boundary is only exact when the target truly has a reference-free channel; without one, the correct answer lies somewhere between the mixed spectrum (0 %) and the boundary (100 %), and the slider walks that interval. Second, the applied result is added as a new dummy row, and the original row must not keep seeding, because rows sharing a component are averaged and would re-mix what was just separated. By default its H seed is disabled: the row stays in the table grayed out, its ROI, plot, and subtraction role keep working, and a right-click re-enables the seed. Alternatively the dialog deletes the row outright. Third, if two components appear in the *same ratio in every pixel*, no method can separate them, purification included; the data then only ever contains their sum.

### A worked example: the donut artifact

The effect of a contaminated seed is easiest to see on data with known ground truth. The generator script `docs/examples/generate_purify_overlap_data.py` builds a stack for exactly this exercise: cytoplasm blobs with a lipid-like spectrum (peak at 2850 cm⁻¹) whose outer regions contain pure pixels, and one nucleus per cell (peak at 2930 cm⁻¹, dark at 2850) that never occurs without cytoplasm on top of it. The true spectra are written next to the stack for comparison.

The naive seed pair is one ROI on pure cytoplasm and one ROI on a nucleus, which is unavoidably mixed. Note that the separability line is content with this pair ($\eta = 0.75$, good): the mixed seed is still easy to tell apart from the lipid seed. Contamination and collinearity are different problems, and $\eta$ only measures the latter; the contamination shows up in the result instead.

![A two-by-two comparison. Top row, naive seeds: the ROI average plot shows the nucleus seed carrying both the 2850 and the 2930 band, and the fitted cytoplasm component map shows blobs with a black hole at every nucleus, one marked by a red circle. Bottom row, purified seeds: the nucleus seed is a clean single band at 2930, the cytoplasm map shows filled blobs without holes, and the two fitted spectra are cleanly separated single peaks.](../assets/images/purify_example_collage.png)

*Top row: seeded NNMF with the naive pair. The nucleus seed (cyan) carries the lipid band at 2850 cm⁻¹ next to its own 2930 cm⁻¹ band, and the fitted cytoplasm map develops a black hole at every nucleus (red circle): the mixed component already explains all the lipid inside the nuclei, so the solver removes it from the cytoplasm component there. Bottom row: the same analysis after **Purify seed…** with the cytoplasm row as reference. The cyan seed is a clean single band, the holes are gone, and both fitted spectra match the ground truth. The relative error is 3.80 % in both runs; the purified run also converged after 80 iterations instead of hitting the 500-iteration cap.*

That error number is the point of the whole exercise. The two factorizations fit the data equally well, so no residual, iteration count, or solver setting could have picked the right one; the choice was made by the seed. Black holes in a component map where another component lives are the visible signature of this ambiguity, and purifying the seed is the fix.

> When a component map shows holes exactly where another component sits, suspect a contaminated seed, not a solver problem.

## Where the diagnostics appear

**Analysis panel.** The status line under the Components spinbox combines both diagnostics: the effective rank (once computed) with an over-request warning, and the minimum $\eta$ of the current spectra with the name of the weakest component. The line always takes the color of the worst news it contains. The **Diagnostics…** button opens the window on the Dataset tab.

**ROI Manager.** A status line under the ROI table shows the minimum $\eta$ of the current seeds, so the separability of a seed set is visible while it is being built, before any analysis has run. It updates automatically (with a short delay) when ROIs are added, moved, removed, relabeled, or when presets and spectra are loaded. The **Separability…** button opens the window on the Separability tab, and **Purify seed…** next to it opens the dialog from the previous section.

![The full GUI on the lung-cell dataset with two red annotation boxes. One marks the status line in the Analysis panel, reading K_eff of about 60 with 3 requested and min eta of 0.140 for ROI 2. The other marks the matching separability line under the ROI table, next to the Separability and Purify seed buttons. The ROI table contains a grayed-out original row and a purified replacement row.](../assets/images/diagnostics_seed_viewer_badge.png)

*Both status lines at once (red boxes are annotations, not part of the GUI). The Analysis panel combines $K_\mathrm{eff}$ and the minimum $\eta$; the line under the ROI table carries the separability part alone. Both judge the seed spectra exactly as the later analysis will see them, so a poor value here is worth fixing before pressing Run Analysis, not after. In the table the purified replacement row from the workflow above is visible next to its grayed-out original.*

**Seed and result viewer.** The window opened by **Test seeds** (and reused by the result import paths) shows the same status line directly above the H spectra it displays, judging whatever spectra are currently plotted.

The spectra being judged follow a fixed priority: a fitted H from a completed analysis wins, otherwise the live seed spectra from the ROI table, otherwise seeds set programmatically in the analyzer. The window subline states which source is active.

## Reading the numbers in practice

A short checklist for a typical session:

1. Open the diagnostics after loading your data and read $K_\mathrm{eff}$ from the Dataset tab, checking it against the bend of the scree curve; the two should roughly agree, and if they do not, the noise estimate is off. Choose the component count at or below that number; add one extra component only for a dedicated background if the background is not already part of the count.
2. Build seeds and watch the line under the ROI table. **good** verdicts need no attention. For **marginal** components compare the *SNR for 10 %* column with the global SNR from the Dataset tab; if your data has SNR to spare, marginal is fine.
3. For a **critical** component, look at *Closest to*. If the named pair is chemically distinct, your channels simply do not resolve the difference, and the fix is at acquisition: an additional channel where the two differ. If the pair is two seeds of the same substance, merge them.
4. After the analysis the same line judges the fitted H. A fit that returned nearly collinear components (small $\eta$, verdict critical) has effectively split one physical component in two; reduce the component count or seed more distinctly.

## References

1. José M. Bioucas-Dias, Antonio Plaza, Nicolas Dobigeon, Mario Parente, Qian Du, Paul Gader, and Jocelyn Chanussot, "Hyperspectral Unmixing Overview: Geometrical, Statistical, and Sparse Regression-Based Approaches," *IEEE Journal of Selected Topics in Applied Earth Observations and Remote Sensing* 5(2), 354–379, 2012. DOI: [10.1109/JSTARS.2012.2194696](https://doi.org/10.1109/JSTARS.2012.2194696). Umbrella reference for the linear mixing model and the distinction between identification and inversion.
2. Gene H. Golub and Charles F. Van Loan, *Matrix Computations*, 4th ed., Johns Hopkins University Press, 2013. ISBN 978-1-4214-0794-4. Standard reference for the SVD and the numerical-rank concept used by the Dataset tab.
3. Vladimir A. Marchenko and Leonid A. Pastur, "Distribution of eigenvalues for some sets of random matrices," *Mathematics of the USSR-Sbornik* 1(4), 457–483, 1967. DOI: [10.1070/SM1967v001n04ABEH001994](https://doi.org/10.1070/SM1967v001n04ABEH001994). Origin of the noise edge used as the singular-value threshold.
4. Matan Gavish and David L. Donoho, "The Optimal Hard Threshold for Singular Values is $4/\sqrt{3}$," *IEEE Transactions on Information Theory* 60(8), 5040–5053, 2014. DOI: [10.1109/TIT.2014.2323359](https://doi.org/10.1109/TIT.2014.2323359). Modern treatment of singular-value thresholding at a known noise level. The GUI thresholds at the bulk edge itself, the detection criterion (values noise alone cannot produce), rather than at the higher threshold that is optimal for denoising.
5. James R. Janesick, *Photon Transfer: DN → λ*, SPIE Press, 2007. DOI: [10.1117/3.725073](https://doi.org/10.1117/3.725073). The camera noise model (read noise, dark current, shot noise) behind the channel-dependence equation.
6. John Immerkær, "Fast Noise Variance Estimation," *Computer Vision and Image Understanding* 64(2), 300–302, 1996. DOI: [10.1006/cviu.1996.0060](https://doi.org/10.1006/cviu.1996.0060). The Laplacian-based per-channel noise estimator behind the noise floor.
7. Andrew A. Green, Mark Berman, Paul Switzer, and Maurice D. Craig, "A transformation for ordering multispectral data in terms of image quality with implications for noise removal," *IEEE Transactions on Geoscience and Remote Sensing* 26(1), 65–74, 1988. DOI: [10.1109/36.3001](https://doi.org/10.1109/36.3001). The minimum noise fraction transform, the canonical noise-whitened eigenanalysis this page's whitening follows.
8. Raymond B. Cattell, "The Scree Test For The Number Of Factors," *Multivariate Behavioral Research* 1(2), 245–276, 1966. DOI: [10.1207/s15327906mbr0102_10](https://doi.org/10.1207/s15327906mbr0102_10). The elbow criterion for reading the component count off the singular value plot, and the origin of the name scree plot.
9. Charles L. Lawson and Richard J. Hanson, *Solving Least Squares Problems*, Prentice-Hall, 1974 (SIAM Classics reprint 1995). DOI: [10.1137/1.9781611971217](https://doi.org/10.1137/1.9781611971217). The NNLS problem whose conditioning $\eta$ describes.
10. David A. Belsley, Edwin Kuh, and Roy E. Welsch, *Regression Diagnostics: Identifying Influential Data and Sources of Collinearity*, Wiley, 1980. DOI: [10.1002/0471725153](https://doi.org/10.1002/0471725153). The variance-inflation result: the coefficient noise of a least-squares fit grows exactly with $1/\eta$.
11. David L. Donoho and Michael Elad, "Optimally sparse representation in general (nonorthogonal) dictionaries via ℓ¹ minimization," *Proceedings of the National Academy of Sciences* 100(5), 2197–2202, 2003. DOI: [10.1073/pnas.0437847100](https://doi.org/10.1073/pnas.0437847100). Uniqueness of sparse solutions (the spark condition) behind the $\lfloor C/2 \rfloor$ statement.
12. Nicolas Gillis, "The why and how of nonnegative matrix factorization," in *Regularization, Optimization, Kernels, and Support Vector Machines*, Chapman & Hall/CRC, 257–291, 2014. DOI: [10.1201/b17558-15](https://doi.org/10.1201/b17558-15) (preprint [arXiv:1401.5226](https://arxiv.org/abs/1401.5226)). NMF identifiability, including the separability (pure-pixel) condition.
13. Xiao Fu, Kejun Huang, Nicholas D. Sidiropoulos, and Wing-Kin Ma, "Nonnegative Matrix Factorization for Signal and Data Analytics: Identifiability, Algorithms, and Applications," *IEEE Signal Processing Magazine* 36(2), 59–80, 2019. DOI: [10.1109/MSP.2018.2877582](https://doi.org/10.1109/MSP.2018.2877582). Survey of NMF identifiability conditions beyond pure pixels (sufficiently scattered abundances).
14. José M. P. Nascimento and José M. B. Dias, "Vertex Component Analysis: A Fast Algorithm to Unmix Hyperspectral Data," *IEEE Transactions on Geoscience and Remote Sensing* 43(4), 898–910, 2005. DOI: [10.1109/TGRS.2005.844293](https://doi.org/10.1109/TGRS.2005.844293). The pure-pixel assumption under which more components than channels remain identifiable.
