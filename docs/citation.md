# Citation

If you use HS-MOSAIC in published work, please cite the Zenodo record and include the exact release tag or commit you used. This makes the exact analysis workflow traceable, especially while the project is still under active development.

## Software

```
HS MOSAIC - A GUI for fast reconstruction and unmixing of hyperspectral imaging data
https://github.com/manuel-kunisch/hs_crs_analysis_gui
https://doi.org/10.5281/zenodo.20273076
```

If you use this software in published work, please include:

- the repository URL,
- the DOI: `10.5281/zenodo.20273076`,
- the release tag or commit hash used,
- the analysis mode (PCA / Random NNMF / Seeded NNMF / Fixed-H NNLS) and main settings.

The repository includes a top-level `CITATION.cff` file so GitHub and citation managers can generate citation metadata.

## BibTeX

```bibtex
@software{kunisch_hs_mosaic,
  author    = {Kunisch, Manuel},
  title     = {{HS MOSAIC} - A GUI for fast reconstruction and unmixing of hyperspectral imaging data},
  doi       = {10.5281/zenodo.20273076},
  url       = {https://github.com/manuel-kunisch/hs_crs_analysis_gui},
  year      = {2026},
  note      = {Please cite the exact release tag or commit hash used.}
}
```

If a more specific version DOI, preprint, or paper becomes available, prefer that citation and include the software version used.

## Related references

The multivariate analysis methods implemented in this software draw on the following published work:

1. Lee, D. D. & Seung, H. S. (2001). Algorithms for non-negative matrix factorization. *Advances in Neural Information Processing Systems*, 13.
2. Paatero, P., Tapper, U., Aalto, P. & Kulmala, M. (1991). Matrix factorization methods for analysing diffusion battery data. *Journal of Aerosol Science*, 22, S273–S276.

For the CRS/CARS/SRS microscopy context, see the references listed in [NNMF and NNLS modes](methods/nnmf_nnls_modes.md).
