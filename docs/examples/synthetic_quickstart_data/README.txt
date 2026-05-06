Synthetic quickstart data

Files:
- synthetic_hs_stack.tif: 3D hyperspectral stack, shape (channel, y, x)
- wavelength.json: spectral axis metadata
- synthetic_reference_spectra.csv: three reference spectra for the ROI Manager

Expected components:
- lipid_like: left rounded region, peak near 2850 cm^-1
- mutated_lipid_like: small bright spot with the same 2850 cm^-1 peak but a different high-wavenumber tail
- protein_like: right elliptical region, main peak near 2930 cm^-1 and weaker overlap near 2850 cm^-1
- broad_background: smooth background gradient
