"""Demand-pattern classification with the Syntetos-Boylan-Croston (SBC) scheme.

ADI (average demand interval) is the number of periods divided by the number of periods with
demand. CV^2 is the squared coefficient of variation (population variance) of the non-zero
demand sizes. The cut-offs ADI = 1.32 and CV^2 = 0.49 come from Syntetos, Boylan & Croston
(2005), "On the categorization of demand patterns", JORS 56(5); a value exactly on a cut-off
belongs to the high side.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

ADI_CUTOFF = 1.32
CV2_CUTOFF = 0.49
MIN_PERIODS = 26
MIN_NONZERO = 4


class Pattern(StrEnum):
    SMOOTH = "smooth"
    ERRATIC = "erratic"
    INTERMITTENT = "intermittent"
    LUMPY = "lumpy"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class SeriesStats:
    adi: float
    cv2: float
    n_periods: int
    n_nonzero: int


def series_stats(values: Sequence[float] | np.ndarray) -> SeriesStats:
    """ADI and CV^2 of one demand series (one value per period, zeros included)."""
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or np.isnan(x).any() or (x < 0).any():
        raise ValueError("demand must be a 1-D series of non-negative numbers")
    nonzero = x[x > 0]
    n_periods, n_nonzero = x.size, nonzero.size
    if n_nonzero == 0:
        return SeriesStats(adi=float("inf"), cv2=float("nan"), n_periods=n_periods, n_nonzero=0)
    return SeriesStats(
        adi=n_periods / n_nonzero,
        cv2=float(nonzero.var() / nonzero.mean() ** 2),
        n_periods=n_periods,
        n_nonzero=n_nonzero,
    )


def classify(adi: float, cv2: float) -> Pattern:
    """Map ADI and CV^2 to one of the four SBC quadrants."""
    if adi < ADI_CUTOFF:
        return Pattern.SMOOTH if cv2 < CV2_CUTOFF else Pattern.ERRATIC
    return Pattern.INTERMITTENT if cv2 < CV2_CUTOFF else Pattern.LUMPY


def classify_series(
    values: Sequence[float] | np.ndarray,
    min_periods: int = MIN_PERIODS,
    min_nonzero: int = MIN_NONZERO,
) -> tuple[SeriesStats, Pattern]:
    """Classify a series, or return INSUFFICIENT when it is too short or too sparse to judge."""
    stats = series_stats(values)
    if stats.n_periods < min_periods or stats.n_nonzero < min_nonzero:
        return stats, Pattern.INSUFFICIENT
    return stats, classify(stats.adi, stats.cv2)
