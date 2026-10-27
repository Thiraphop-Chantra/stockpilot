"""Thai business calendar: closures, holiday-block effects and date ranges."""

from datetime import date

import numpy as np
import pytest

from stockpilot.synth.calendar import build_calendar
from stockpilot.synth.config import SynthConfig


@pytest.fixture(scope="module")
def cal():
    return build_calendar(SynthConfig.from_preset("default"))


def day(cal, d):
    return cal.index_of(np.datetime64(d, "D"))


def test_ranges_cover_warmup_history_and_horizon(cal):
    assert cal.dates[0] == np.datetime64("2020-09-03")  # 120 warm-up days before 2021-01-01
    assert cal.dates[cal.history_start] == np.datetime64("2021-01-01")
    assert cal.dates[cal.history_end] == np.datetime64("2025-12-31")
    assert cal.history_end - cal.history_start + 1 == 1826
    assert cal.dates[-1] == np.datetime64("2026-06-30")


def test_sundays_and_songkran_are_closed(cal):
    weekday = (cal.dates.astype("datetime64[D]").view("int64") - 4) % 7  # 0 = Monday
    assert not cal.is_working[weekday == 6].any()
    for year in range(2021, 2026):
        for d in (13, 14, 15):
            assert not cal.is_working[day(cal, f"{year}-04-{d:02d}")]
    assert cal.is_working[day(cal, "2024-04-11")]


def test_demand_profile_is_zero_exactly_on_closed_days(cal):
    profile = cal.weekday_factor * cal.holiday_factor
    assert ((profile == 0) == ~cal.is_working).all()


def test_holiday_block_uplift_before_and_after_songkran_2024(cal):
    # Closed 12-16 Apr 2024 (bridge day, Songkran, Sunday, in-lieu day): block length 5.
    assert cal.holiday_factor[day(cal, "2024-04-10")] == pytest.approx(1.40)
    assert cal.holiday_factor[day(cal, "2024-04-11")] == pytest.approx(1.40)
    assert cal.holiday_factor[day(cal, "2024-04-17")] == pytest.approx(1.25)
    assert cal.holiday_factor[day(cal, "2024-04-18")] == pytest.approx(1.0)


def test_songkran_pre_window_is_seven_working_days(cal):
    flagged = cal.dates[cal.songkran_pre]
    in_2024 = flagged[
        (flagged >= np.datetime64("2024-03-01")) & (flagged < np.datetime64("2024-05-01"))
    ]
    assert len(in_2024) == 7
    assert in_2024.max() == np.datetime64("2024-04-11")
    assert cal.is_working[cal.songkran_pre].all()


def test_month_ends_cover_the_history(cal):
    ends = cal.dates[cal.month_end_idx]
    assert len(ends) == 60
    assert ends[0] == np.datetime64("2021-01-31")
    assert ends[-1] == np.datetime64("2025-12-31")


def test_holiday_names_are_recorded(cal):
    assert "Songkran" in cal.holiday_name[day(cal, "2025-04-14")]
    assert cal.holiday_name[day(cal, "2025-04-17")] == ""
    assert cal.extraction_date == date(2026, 1, 1)
