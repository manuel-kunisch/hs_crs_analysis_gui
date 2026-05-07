Synthetic quickstart data

Files:
- synthetic_hs_stack.tif: 3D hyperspectral stack, shape (channel, y, x)
- wavelength.json: spectral axis metadata
- synthetic_reference_spectra.csv: one reference spectrum per synthetic component

Generator settings:
- seed: 7
- beads_per_class: 12
- mutant_variants: 2
- mutant_beads_per_variant: 4
- noise: 280.0

Expected components:
- lipid_like: 12 beads with a peak near 2850 cm^-1
- mutated_lipid_like_1: 4 small beads with the same 2850 cm^-1 peak and a variant-specific tail
- mutated_lipid_like_2: 4 small beads with the same 2850 cm^-1 peak and a variant-specific tail
- protein_like: 12 beads with a main peak near 2930 cm^-1 and weaker overlap near 2850 cm^-1
- broad_background: smooth background gradient
