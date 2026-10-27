"""The fictional company's business calendar.

The company works Monday to Saturday and closes on Sundays and on Thai public holidays taken from
the ``holidays`` package. A *closure block* is a run of consecutive closed days that contains at
least one public holiday; customers order more just before a block (stocking up) and somewhat
more on the first working day after it (catching up).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import holidays
import numpy as np

from stockpilot.synth.config import SynthConfig

# Relative order intake by weekday (Monday first); Saturday is a half day, Sunday is closed.
WEEKDAY_FACTORS = np.array([1.20, 1.10, 1.05, 1.00, 1.00, 0.65, 0.0])
PRE_BLOCK_DAYS = 2  # working days before a closure block that see stocking-up orders
PRE_BLOCK_SLOPE, PRE_BLOCK_CAP = 0.08, 1.5  # uplift = min(cap, 1 + slope * block length)
POST_BLOCK_SLOPE, POST_BLOCK_CAP = 0.05, 1.3
SONGKRAN_PRE_DAYS = 7  # working days before the Songkran block with a festive surge


@dataclass(frozen=True)
class Calendar:
    dates: np.ndarray  # datetime64[D]: warm-up start .. horizon end
    is_working: np.ndarray  # bool
    holiday_name: np.ndarray  # str ("" when not a public holiday)
    weekday: np.ndarray  # 0 = Monday .. 6 = Sunday
    weekday_factor: np.ndarray  # float, 0 on Sundays
    holiday_factor: np.ndarray  # float, 0 on closed days, uplift around closure blocks
    songkran_pre: np.ndarray  # bool, working days just before a Songkran block
    history_start: int  # index of the first history day
    history_end: int  # index of the last history day (inclusive)
    month_end_idx: np.ndarray  # indices of month-end days inside the history
    extraction_date: date

    @property
    def n_days(self) -> int:
        return len(self.dates)

    @property
    def history(self) -> slice:
        return slice(self.history_start, self.history_end + 1)

    @property
    def horizon(self) -> slice:
        return slice(self.history_end + 1, self.n_days)

    def index_of(self, day: np.datetime64 | date) -> int:
        offset = (np.datetime64(day, "D") - self.dates[0]).astype(int)
        if not 0 <= offset < self.n_days:
            raise KeyError(f"{day} is outside the calendar")
        return int(offset)


def build_calendar(cfg: SynthConfig) -> Calendar:
    first = cfg.start - timedelta(days=cfg.warmup_days)
    last = cfg.horizon_end
    dates = np.arange(np.datetime64(first, "D"), np.datetime64(last, "D") + 1)
    n = len(dates)
    weekday = ((dates.view("int64") - 4) % 7).astype(np.int8)  # 1970-01-01 was a Thursday

    public = holidays.Thailand(years=range(first.year - 1, last.year + 2), language="en_US")
    holiday_name = np.array([public.get(d.item(), "") for d in dates], dtype=object)
    is_holiday = holiday_name != ""
    is_working = (weekday != 6) & ~is_holiday

    holiday_factor = np.where(is_working, 1.0, 0.0)
    songkran_pre = np.zeros(n, dtype=bool)
    working_idx = np.flatnonzero(is_working)
    for start, stop in _closed_runs(is_working):
        if not is_holiday[start:stop].any():
            continue  # an ordinary Sunday
        length = stop - start
        before = working_idx[working_idx < start]
        after = working_idx[working_idx >= stop]
        holiday_factor[before[-PRE_BLOCK_DAYS:]] *= min(PRE_BLOCK_CAP, 1 + PRE_BLOCK_SLOPE * length)
        if after.size:
            holiday_factor[after[0]] *= min(POST_BLOCK_CAP, 1 + POST_BLOCK_SLOPE * length)
        if any("Songkran" in name for name in holiday_name[start:stop]):
            songkran_pre[before[-SONGKRAN_PRE_DAYS:]] = True

    history_start = int((np.datetime64(cfg.start, "D") - dates[0]).astype(int))
    history_end = int((np.datetime64(cfg.history_end, "D") - dates[0]).astype(int))
    next_day_month = (dates + 1).astype("datetime64[M]")
    is_month_end = next_day_month != dates.astype("datetime64[M]")
    month_end_idx = np.flatnonzero(is_month_end[: history_end + 1])
    month_end_idx = month_end_idx[month_end_idx >= history_start]

    return Calendar(
        dates=dates,
        is_working=is_working,
        holiday_name=holiday_name,
        weekday=weekday,
        weekday_factor=WEEKDAY_FACTORS[weekday],
        holiday_factor=np.round(holiday_factor, 9),
        songkran_pre=songkran_pre,
        history_start=history_start,
        history_end=history_end,
        month_end_idx=month_end_idx,
        extraction_date=cfg.extraction_date,
    )


def _closed_runs(is_working: np.ndarray) -> list[tuple[int, int]]:
    """Half-open index ranges of consecutive non-working days."""
    closed = np.concatenate([[False], ~is_working, [False]]).astype(np.int8)
    edges = np.flatnonzero(np.diff(closed))
    return list(zip(edges[::2].tolist(), edges[1::2].tolist(), strict=True))
