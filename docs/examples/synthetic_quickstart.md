# Synthetic quickstart

This example creates a small hyperspectral TIFF stack that can be used to test installation and the basic GUI workflow without experimental data.

Use it when:

- you want to confirm that TIFF loading works,
- you want a safe dataset for learning ROIs, seeds, NNMF, NNLS, and export,
- you need a repeatable dataset for screenshots or GIFs.

## Files generated

Run the generator script from an environment where the application dependencies are installed:

```bash
python docs/examples/generate_synthetic_quickstart.py --output synthetic_quickstart_data
```

On Windows, if `python` is not available but the Python launcher is installed:

```bash
py docs/examples/generate_synthetic_quickstart.py --output synthetic_quickstart_data
```

The output folder contains:

| File | Purpose |
|---|---|
| `synthetic_hs_stack.tif` | 3D hyperspectral stack with shape `(channel, y, x)`. |
| `wavelength.json` | Spectral-axis metadata loaded automatically by the GUI. |
| `synthetic_reference_spectra.csv` | Four reference spectra that can be imported with **Load Spectrum from File**. |
| `README.txt` | Short description of the generated data. |

## What the dataset contains

The stack has four synthetic components:

| Component | Spatial pattern | Spectrum |
|---|---|---|
| Lipid-like | Bright rounded region on the left | Narrow peak near 2850 cm^-1 |
| Mutated lipid-like | Small bright spot in the upper-right region | Same main 2850 cm^-1 peak as lipid-like, but with a different high-wavenumber tail |
| Protein-like | Elliptical region on the right | Main peak near 2930 cm^-1 plus a weaker overlapping peak near 2850 cm^-1 |
| Broad background | Smooth gradient over the field | Broad low-frequency spectral background |

The data are intentionally simple but not perfectly separated. The lipid-like, mutated lipid-like, and protein-like spectra all contribute around 2850 cm^-1, so inspecting only that channel is ambiguous. The mutated lipid-like spot is a deliberately artificial case: it shares the lipid peak but has a different tail. This makes it useful for demonstrating why full-spectrum NNMF/NNLS can distinguish signals that look similar in one channel.

A good multivariate analysis should recover the left lipid-like region, the small mutated lipid-like spot, the right protein-like region, and one smooth background-like component.

## Why seeded NNMF or fixed-H NNLS is useful here

This dataset is designed so that a single bright channel is not enough. Around 2850 cm^-1, several components light up at the same time:

- the ordinary lipid-like region,
- the mutated lipid-like spot,
- part of the protein-like signal.

The separation comes from the full spectral shape. The mutated lipid-like spot has the same main lipid peak, but a different tail. The protein-like signal partly overlaps with lipid at 2850 cm^-1, but its strongest information is closer to 2930 cm^-1. Seeded NNMF and fixed-H NNLS use these full-spectrum differences instead of treating one channel as one component.

Use **Fixed-H NNLS mode** first if you want a reference result: load the provided spectra and keep them fixed. This shows what the GUI can recover when the spectra are already known.

Then experiment with seeded NNMF by disabling **Fixed-H NNLS mode** while keeping **NNMF** and **Custom initialization** enabled. In this mode, seeds are starting points rather than fixed rules. The result can adapt, which is useful when real reference spectra are approximate or when the sample spectrum differs from the library spectrum.

## Seed experiments to try

| Seed strategy | What to do | What it teaches |
|---|---|---|
| Reference spectra | Load `synthetic_reference_spectra.csv` with **Load Spectrum from File**. | Best controlled starting point; useful for checking the expected separation. |
| Spatial ROIs | Draw ROIs on the left lipid-like blob, the small mutated lipid-like spot, the right protein-like blob, and a background region. | Shows how well ROI-derived mean spectra work when you choose representative regions. |
| Gaussian models | Add resonance settings near 2850 cm^-1, 2930 cm^-1, and the mutated lipid tail region near 3010 cm^-1. | Shows how approximate peak knowledge can guide analysis without external spectra. |
| Mixed strategy | Use loaded spectra for known components, then draw or model only the uncertain component. | Mirrors real workflows where some components are known and others need exploration. |
| No seeds / random NNMF | Disable **Custom initialization** and run NNMF. | Shows why unguided NNMF can be less stable when components overlap. |

The goal is not only to get one correct answer. Use this dataset to see how seed quality, component count, and fixed-vs-adaptive spectra change the result.

## GUI workflow

1. Start the GUI.
2. In the **Single HS Image** tab, load `synthetic_hs_stack.tif`.
3. Confirm that the spectral axis is loaded from `wavelength.json`.
4. Set **Components** to `4`.
5. Click **Load Spectrum from File** in the ROI Manager and select `synthetic_reference_spectra.csv`.
6. Assign the loaded spectra to components 1, 2, 3, and 4 if prompted.
7. In the **Analysis** panel, select **NNMF**, keep **Custom initialization** enabled, and enable **Fixed-H NNLS mode** for the first reproducible test.
8. Click **Run Analysis**.
9. Inspect the result viewer:
   - component 1 should map the left rounded region,
   - component 2 should map the small mutated lipid-like spot,
   - component 3 should map the right elliptical region,
   - component 4 should look like a smooth background.

For a more exploratory test, disable **Fixed-H NNLS mode** and run seeded NNMF with the same spectra. The H spectra may adapt slightly because seeded NNMF treats seeds as starting points rather than fixed spectra.

To demonstrate the point of the synthetic data, compare the raw channel around 2850 cm^-1 with the NNMF/NNLS component maps. The raw channel lights up multiple regions at once, while the multivariate result separates the ordinary lipid-like region from the mutated lipid-like spot by using the different spectral tail.

## Expected outcome

| Check | Expected result |
|---|---|
| TIFF loading | First channel appears in the raw image viewer. |
| Spectral axis | The x-axis uses Raman-shift values from `wavelength.json`. |
| Spectrum import | Four dummy ROI rows appear after loading the CSV. |
| Fixed-H NNLS | H spectra stay equal to the imported references. |
| Seeded NNMF | Maps remain similar, but H spectra may adapt. |
| Overlap demonstration | The 2850 cm^-1 channel is ambiguous, but the separated component maps distinguish ordinary lipid-like signal, mutated lipid-like signal, and protein-like signal. |
| Export | **Save H as CSV** and **Export Composite** should both produce usable files. |

The overlap near 2850 cm^-1 is deliberate. It makes the example useful for teaching why the GUI uses full-spectrum fitting instead of assigning components from one bright channel. The mutated lipid-like spot is especially useful for screenshots because it is small, bright, and spectrally similar enough to the ordinary lipid-like region that a single-channel view cannot explain it cleanly.

## Media to add

This is a good first GIF target because it is deterministic and does not require private data:

1. generate the dataset,
2. load the TIFF,
3. load the reference spectra,
4. show the ambiguous 2850 cm^-1 raw channel,
5. run fixed-H NNLS or seeded NNMF,
6. show that the ordinary lipid-like region and mutated lipid-like spot are separated,
7. export the composite and H spectra.
