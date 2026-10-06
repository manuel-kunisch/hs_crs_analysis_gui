"""Regression tests for the pre-run NNMF seed check.

Non-finite entries must be fatal: NaN/Inf are invisible to the sign
comparisons the check is built on, and a seed that reaches the solvers
poisons the run silently (scikit-learn returns an all-NaN result with no
error, the torch backend zeroes the seed to the eps floor). All-zero
components stay warnings — that is deliberate (the run works, the component
comes out empty).
"""
from __future__ import annotations

import numpy as np
import pytest

from hs_mosaic.widgets.multivariate_analyzer import MultivariateAnalyzer


def _analyzer_with_seeds(n_bands: int = 8, side: int = 6, k: int = 2) -> MultivariateAnalyzer:
    rng = np.random.default_rng(0)
    cube = rng.gamma(2.0, 1.0, size=(n_bands, side, side)).astype(np.float32)
    analyzer = MultivariateAnalyzer(cube, k, np.arange(n_bands), method="NNMF")
    analyzer.seed_W = rng.random((side * side, k)).astype(np.float32)
    analyzer.seed_H = rng.random((k, n_bands)).astype(np.float32) + 0.1
    return analyzer


def test_clean_seeds_pass():
    analyzer = _analyzer_with_seeds()
    analyzer._check_seeds_or_raise()  # must not raise
    fatal, warnings = analyzer._seed_problem_report()
    assert fatal == [] and warnings == []


def test_all_nan_h_row_is_fatal_not_an_all_zeros_warning():
    analyzer = _analyzer_with_seeds()
    analyzer.seed_H[1, :] = np.nan
    fatal, warnings = analyzer._seed_problem_report()
    assert any("component 2" in msg and "non-finite" in msg for msg in fatal)
    assert warnings == []  # must not be mislabelled "all zeros"
    with pytest.raises(ValueError, match="non-finite"):
        analyzer._check_seeds_or_raise()


def test_single_nan_in_w_is_fatal():
    analyzer = _analyzer_with_seeds()
    analyzer.seed_W[3, 0] = np.nan
    with pytest.raises(ValueError, match="W seed of component 1.*non-finite"):
        analyzer._check_seeds_or_raise()


def test_inf_in_h_is_fatal():
    analyzer = _analyzer_with_seeds()
    analyzer.seed_H[0, 2] = np.inf
    with pytest.raises(ValueError, match="H seed of component 1.*non-finite"):
        analyzer._check_seeds_or_raise()


def test_negative_seed_stays_fatal():
    analyzer = _analyzer_with_seeds()
    analyzer.seed_H[0, 4] = -0.5
    with pytest.raises(ValueError, match="negative"):
        analyzer._check_seeds_or_raise()


def test_all_zero_component_stays_a_warning():
    analyzer = _analyzer_with_seeds()
    analyzer.seed_W[:, 1] = 0.0
    analyzer.seed_H[1, :] = 0.0
    fatal, warnings = analyzer._seed_problem_report()
    assert fatal == []
    assert any("W seed of component 2" in msg and "all zeros" in msg for msg in warnings)
    assert any("H seed of component 2" in msg and "all zeros" in msg for msg in warnings)
    analyzer._check_seeds_or_raise()  # warnings only, must not raise
