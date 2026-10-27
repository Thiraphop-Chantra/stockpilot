"""Demand generation: patterns, calendar effects, promotions, lifecycle and customers."""

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from stockpilot.synth.calendar import build_calendar
from stockpilot.synth.config import SynthConfig
from stockpilot.synth.demand import build_rates, customer_bases, generate_lines
from stockpilot.synth.master import build_master
from stockpilot.synth.measure import measure_patterns, weekly_totals
from stockpilot.synth.promotions import build_promotions


def day_index(cal, d):
    return cal.index_of(np.datetime64(d, "D"))


def test_measured_pattern_mix_matches_the_target(small_cfg, small_cal, small_master, small_lines):
    lines = small_lines
    weekly, week_start = weekly_totals(
        lines.sku, lines.day, lines.qty_base, len(small_master.materials), small_cal
    )
    measured = measure_patterns(small_master.materials, weekly, week_start, small_cal)
    measured = measured.merge(small_master.sku_profile[["material_code", "pattern"]])
    judged = measured[measured["measured"] != "insufficient"]
    assert len(judged) >= 0.9 * len(measured)
    shares = judged["measured"].value_counts(normalize=True)
    for pattern, target in small_cfg.pattern_mix:
        assert shares.get(pattern, 0.0) == pytest.approx(target, abs=0.06), pattern
    assert (judged["measured"] == judged["pattern"]).mean() >= 0.90


def test_no_demand_on_closed_days(small_cal, small_lines):
    assert small_cal.is_working[small_lines.day].all()


def test_lines_are_sorted_and_consistent(small_master, small_lines):
    lines = small_lines
    key = lines.sku.astype(np.int64) * 100_000 + lines.day
    assert (np.diff(key) >= 0).all()
    units = small_master.materials["units_per_box"].to_numpy()[lines.sku]
    assert (lines.qty_base == lines.qty_unit * np.where(lines.order_unit == 1, units, 1)).all()
    assert (lines.qty_unit >= 1).all()
    plant_of_customer = small_master.customers["delivering_plant"].map(
        {"1100": 0, "1200": 1, "1300": 2}
    )
    assert (lines.plant == plant_of_customer.to_numpy()[lines.customer]).all()


def test_lifecycle_zero_outside_active_window(small_cal, small_master, small_lines):
    m = small_master.materials
    line_dates = small_cal.dates[small_lines.day]
    launch = np.array(m["launch_date"].tolist(), dtype="datetime64[D]")[small_lines.sku]
    assert (line_dates >= launch).all()
    disc = m["discontinued_date"].map(lambda d: d or small_cal.dates[-1].item() + timedelta(1))
    disc = np.array(disc.tolist(), dtype="datetime64[D]")[small_lines.sku]
    assert (line_dates < disc).all()
    launched = m.index[m["launch_date"] >= small_cal.dates[small_cal.history_start].item()]
    assert np.isin(small_lines.sku, launched).any()


def test_lost_key_account_buys_nothing_after_the_loss(small_cal, small_master, small_lines):
    p = small_master.customer_profile
    lost = p.index[p["major_loss"]][0]
    loss_day = day_index(small_cal, p.loc[lost, "active_to"])
    days = small_lines.day[small_lines.customer == lost]
    assert days.size > 0 and days.min() < loss_day
    assert days.max() <= loss_day


def test_promotions_lift_demand_and_are_followed_by_a_dip(small_cal, small_promos, small_lines):
    truth = small_promos.truth
    sku_day = np.zeros((small_promos.uplift.shape[0], small_cal.n_days))
    np.add.at(sku_day, (small_lines.sku, small_lines.day), small_lines.qty_base)
    work = small_cal.is_working
    lifts, dips = [], []
    for row in truth.itertuples():
        start, end = day_index(small_cal, row.start_date), day_index(small_cal, row.end_date)
        dip_end = day_index(small_cal, row.dip_end_date)
        before = slice(max(0, start - 56), start)
        clean = (small_promos.uplift[row.sku, before] == 1.0) & work[before]
        if clean.sum() < 20:
            continue
        base = sku_day[row.sku, before][clean].mean()
        if base == 0:
            continue
        during = work[start : end + 1]
        after = work[end + 1 : dip_end + 1]
        lifts.append(sku_day[row.sku, start : end + 1][during].mean() / base)
        if after.any():
            dips.append(sku_day[row.sku, end + 1 : dip_end + 1][after].mean() / base)
    assert len(lifts) > 50
    assert np.median(lifts) > 1.3
    assert np.median(dips) < 0.95


def test_promotion_table_matches_the_effects(small_cfg, small_promos):
    table = small_promos.table
    assert table["promo_id"].is_unique
    assert table["discount_pct"].between(5, 30).all()
    assert (table["end_date"] >= table["start_date"]).all()
    assert (table["end_date"] >= small_cfg.start).all()
    assert (table["start_date"] <= small_cfg.horizon_end).all()
    assert (table["start_date"] > small_cfg.history_end).any()  # planned promotions are known


def test_songkran_surge_only_for_festive_categories(small_cal, small_master, small_rates):
    cats = small_master.materials["category"].to_numpy()
    pre = np.flatnonzero(small_cal.songkran_pre)
    ratio = small_rates[:, pre] / np.maximum(small_rates[:, pre - 7], 1e-12)
    valid = (small_rates[:, pre] > 0) & (small_rates[:, pre - 7] > 0)
    mean_ratio = {c: np.median(ratio[cats == c][valid[cats == c]]) for c in ("BEV", "GRO")}
    assert mean_ratio["BEV"] > 1.15 * mean_ratio["GRO"]


def test_weekly_order_lines_follow_the_configured_rate(small_cal, small_master, small_lines):
    profile = small_master.sku_profile
    mature = (profile["lifecycle"] == "mature") & (profile["pattern"] == "smooth")
    mature &= ~profile["promo_eligible"]
    history = (small_lines.day >= small_cal.history_start) & (
        small_lines.day <= small_cal.history_end
    )
    counts = np.bincount(small_lines.sku[history], minlength=len(profile))
    weeks = (small_cal.history_end - small_cal.history_start + 1) / 7
    ratio = counts[mature.to_numpy()] / weeks / profile.loc[mature, "lines_per_week"].to_numpy()
    assert mature.sum() >= 5
    assert 0.85 <= np.median(ratio) <= 1.15


def test_lines_are_deterministic():
    cfg = SynthConfig.from_preset("tiny")
    cal = build_calendar(cfg)
    master = build_master(cfg, cal)
    rates = build_rates(cfg, cal, master, build_promotions(cfg, cal, master))
    a = generate_lines(cfg, cal, master, rates)
    b = generate_lines(cfg, cal, master, rates)
    for field in ("sku", "day", "customer", "plant", "qty_base", "order_unit", "qty_unit"):
        assert np.array_equal(getattr(a, field), getattr(b, field)), field


def test_late_launches_ramp_up_without_numeric_warnings():
    # A five-year history puts some launches years after the calendar start; the ramp-up
    # logistic must not overflow (pytest turns stockpilot warnings into errors).
    cfg = SynthConfig.from_preset("tiny", history_years=5)
    cal = build_calendar(cfg)
    master = build_master(cfg, cal)
    rates = build_rates(cfg, cal, master, build_promotions(cfg, cal, master))
    assert np.isfinite(rates).all()


def test_successors_inherit_their_predecessors_customer_base(small_cfg, small_cal, small_master):
    bases = customer_bases(small_cfg, small_cal, small_master)
    m = small_master.materials
    row = {code: i for i, code in enumerate(m["material_code"])}
    pairs = [
        (row[code], row[pred])
        for code, pred in zip(m["material_code"], m["predecessor_material_code"], strict=True)
        if pred is not None and not pd.isna(pred)
    ]
    assert pairs
    for successor, predecessor in pairs:
        assert np.array_equal(bases.weights[successor], bases.weights[predecessor])
