# Stitching and preprocessing example

This example will show how tiled data is stitched and prepared before multivariate analysis.

This page is intentionally workflow-oriented. For the detailed meaning of every stitch setting, see [01b Stitching tile folders](../tutorials/01b_stitching_tile_folders.md). For the detailed meaning of physical-units and rolling-ball settings, see [04 Physical units and rolling-ball correction](../tutorials/04_physical_units_and_rolling_ball.md).

## Planned workflow

1. Select a tile folder.
2. Configure filename parsing.
3. Set overlap and scan direction.
4. Choose grid or correlation-assisted stitching.
5. Inspect the stitched image.
6. Apply physical units and optional background correction.
7. Save the stitched TIFF.
8. Run analysis on the stitched result.

## Points to highlight

- Tile filename parsing.
- Variable overlap.
- Scan direction correction.
- Correlation-assisted alignment.
- Physical pixel size.
- Rolling-ball or background handling.
- Export of stitched and analyzed data.

## Decision guide

Use this workflow when the main question is not only "how do I stitch tiles?" but also "which preprocessing choices should I commit to before analysis?".

Typical decisions are:

- whether the tile folder is geometrically reliable enough for grid placement alone,
- whether correlation should refine the tile positions,
- whether broad background should be removed as preprocessing or kept for later modeling,
- and whether the stitched result should already carry correct physical scale information for export.

Recommended defaults:

- start with the correct filename parsing and preview table first,
- use the microscope overlap values before tuning them manually,
- try correlation when small seams remain after a grid stitch,
- prefer `reference` illumination correction when many similar tiles share one stable shading pattern,
- and verify physical units before exporting or placing publication scale bars.

> Placeholder: insert tiled example dataset.

> GIF placeholder: stitch tiles, correct scan direction, and run analysis.
