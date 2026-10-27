"""Measure demand patterns on generated data the way an analyst would.

Demand is summed per SKU over all warehouses into full ISO weeks (Monday to Sunday) of the
history and classified with ADI/CV^2 over each SKU's active window, taken from the observable
master data (launch date, discontinued date).
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from stockpilot.patterns import classify_series
from stockpilot.synth.calendar import Calendar


def weekly_totals(
    sku: np.ndarray, day: np.ndarray, qty: np.ndarray, n_skus: int, cal: Calendar
) -> tuple[np.ndarray, np.ndarray]:
    """Quantity per SKU and full history week, and the Monday each week starts on."""
    history = np.arange(cal.history_start, cal.history_end + 1)
    first_monday = history[cal.weekday[history] == 0][0]
    last_sunday = history[cal.weekday[history] == 6][-1]
    n_weeks = (last_sunday - first_monday + 1) // 7
    inside = (day >= first_monday) & (day <= last_sunday)
    cell = sku[inside].astype(np.int64) * n_weeks + (day[inside] - first_monday) // 7
    weekly = np.bincount(cell, weights=qty[inside], minlength=n_skus * n_weeks)
    week_start = cal.dates[first_monday] + 7 * np.arange(n_weeks)
    return weekly.reshape(n_skus, n_weeks), week_start


def measure_patterns(
    materials: pd.DataFrame, weekly: np.ndarray, week_start: np.ndarray, cal: Calendar
) -> pd.DataFrame:
    """ADI, CV^2 and measured pattern per SKU over its active window."""
    history_start = cal.dates[cal.history_start].item()
    history_end = cal.dates[cal.history_end].item()
    rows = []
    for i, m in enumerate(materials.itertuples(index=False)):
        start = max(history_start, m.launch_date)
        end = history_end
        if m.discontinued_date is not None and not pd.isna(m.discontinued_date):
            end = min(end, m.discontinued_date - timedelta(days=1))
        inside = (week_start >= np.datetime64(start, "D")) & (
            week_start + 6 <= np.datetime64(end, "D")
        )
        stats, pattern = classify_series(weekly[i, inside])
        rows.append(
            (m.material_code, stats.n_periods, stats.n_nonzero, stats.adi, stats.cv2, str(pattern))
        )
    return pd.DataFrame(
        rows, columns=["material_code", "n_weeks", "n_nonzero", "adi", "cv2", "measured"]
    )
