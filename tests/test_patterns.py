"""ADI/CV-squared demand-pattern classification (Syntetos-Boylan-Croston cut-offs)."""

import numpy as np
import pytest

from stockpilot.patterns import Pattern, classify, classify_series, series_stats


def test_constant_demand_is_smooth():
    stats, pattern = classify_series(np.full(30, 4.0))
    assert (stats.adi, stats.cv2, stats.n_periods, stats.n_nonzero) == (1.0, 0.0, 30, 30)
    assert pattern is Pattern.SMOOTH


def test_regular_gaps_with_stable_size_are_intermittent():
    stats, pattern = classify_series([5, 0, 0] * 20)
    assert stats.adi == pytest.approx(3.0)
    assert stats.cv2 == pytest.approx(0.0)
    assert pattern is Pattern.INTERMITTENT


def test_every_period_with_volatile_size_is_erratic():
    # sizes 1 and 9: mean 5, population std 4 -> CV^2 = 0.64
    stats, pattern = classify_series([1, 9] * 20)
    assert stats.adi == pytest.approx(1.0)
    assert stats.cv2 == pytest.approx(0.64)
    assert pattern is Pattern.ERRATIC


def test_gaps_with_volatile_size_are_lumpy():
    # 20 demands in 60 periods (ADI 3); sizes 1 and 20: mean 10.5, std 9.5 -> CV^2 = 0.8186
    stats, pattern = classify_series([1, 0, 0, 20, 0, 0] * 10)
    assert stats.adi == pytest.approx(3.0)
    assert stats.cv2 == pytest.approx((9.5 / 10.5) ** 2)
    assert pattern is Pattern.LUMPY


def test_cutoffs_belong_to_the_high_side():
    assert classify(1.32, 0.1) is Pattern.INTERMITTENT
    assert classify(1.0, 0.49) is Pattern.ERRATIC
    assert classify(1.3199, 0.4899) is Pattern.SMOOTH
    assert classify(1.32, 0.49) is Pattern.LUMPY


def test_cv2_uses_population_variance():
    # sizes 2 and 4: population variance 1, mean 3 -> 1/9 (sample variance would give 0.1156)
    stats = series_stats([2, 4] * 13)
    assert stats.cv2 == pytest.approx(1 / 9)


@pytest.mark.parametrize(
    "values",
    [
        np.zeros(30),  # never any demand
        [0] * 27 + [1, 1, 1],  # only 3 demand periods
        np.ones(25),  # shorter than 26 periods
    ],
)
def test_short_or_sparse_history_is_insufficient(values):
    _, pattern = classify_series(values)
    assert pattern is Pattern.INSUFFICIENT


@pytest.mark.parametrize("bad", [[1.0, -2.0, 3.0], [1.0, float("nan"), 3.0]])
def test_negative_or_missing_demand_is_rejected(bad):
    with pytest.raises(ValueError, match="non-negative"):
        series_stats(bad)
