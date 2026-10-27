"""True customer demand: one order line per customer, SKU and day.

The expected number of order lines of a SKU on a day is its weekly base rate (set by the SKU's
demand pattern) times multiplicative effects: weekday and holiday closures, category seasonality,
trend, promotions, the pre-Songkran surge, product lifecycle, the share of its customer base
that is still active, and (for erratic SKUs) a bursty weekly intensity. The number of lines is
Poisson; each line is placed by a customer of the SKU's customer base and has a lognormal size.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from stockpilot.synth.calendar import Calendar
from stockpilot.synth.catalog import CATEGORIES, CATEGORY_INDEX
from stockpilot.synth.config import SynthConfig
from stockpilot.synth.geo import WAREHOUSES
from stockpilot.synth.master import CUSTOMER_TYPES, Master
from stockpilot.synth.promotions import Promotions
from stockpilot.synth.rng import stream

SONGKRAN_SURGE = 1.25
BASE_SIZE = {"smooth": (60, 240), "erratic": (20, 90), "intermittent": (3, 20), "lumpy": (3, 20)}
MAX_BASE_SHARE = 0.6  # a customer base never exceeds this share of all customers
BASE_SIZE_EXPONENT = 0.8  # larger customers carry more SKUs
RETAIL_PIECE_SHARE = 0.3  # retail lines for fast boxed SKUs that are ordered in pieces
PIECE_ORDER_SHARE_OF_BOX = 0.4  # a piece order is about 40% of the usual box order in pieces
CUSTOMER_SIZE_EFFECT = 0.2  # line size grows with customer size ** this (fast movers only)

# Relative interest of each customer type in each category (rows: CUSTOMER_TYPES order,
# columns: CATEGORIES order).
TYPE_CATEGORY_AFFINITY = np.array(
    [
        [1.0, 1.0, 1.0, 1.0, 1.0, 0.6, 0.8, 0.5, 1.0],  # MT
        [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.2, 0.8],  # WHOLESALE
        [1.2, 1.2, 1.0, 1.0, 1.0, 0.8, 0.6, 1.0, 0.5],  # RETAIL
        [1.2, 0.5, 1.2, 0.6, 1.0, 0.3, 0.3, 0.3, 0.5],  # HORECA
        [0.6, 0.4, 0.8, 0.8, 1.2, 1.5, 0.6, 0.6, 0.3],  # INSTITUTION
    ]
)

ORDER_UNIT_PC, ORDER_UNIT_BOX = 0, 1


@dataclass(frozen=True)
class Lines:
    """True order lines, sorted by (sku, day); indices refer to master tables."""

    sku: np.ndarray  # int32, row of master.materials
    day: np.ndarray  # int32, index into cal.dates
    customer: np.ndarray  # int32, row of master.customers
    plant: np.ndarray  # int8, index into geo.WAREHOUSES
    order_unit: np.ndarray  # int8, ORDER_UNIT_PC or ORDER_UNIT_BOX
    qty_unit: np.ndarray  # int64, quantity in the order unit
    qty_base: np.ndarray  # int64, quantity in pieces

    def __len__(self) -> int:
        return int(self.sku.size)


@dataclass(frozen=True)
class CustomerBases:
    weights: np.ndarray  # float64 [sku, customer], 0 outside the SKU's customer base
    active: np.ndarray  # bool [customer, day]


def build_rates(cfg: SynthConfig, cal: Calendar, master: Master, promos: Promotions) -> np.ndarray:
    """Expected order lines per SKU and day (float64 [sku, day])."""
    materials, profile = master.materials, master.sku_profile
    n_sku = len(materials)
    base = cal.weekday_factor * cal.holiday_factor
    rates = np.outer(profile["lines_per_week"].to_numpy() / 7.0, base / base[cal.history].mean())

    category = materials["category"].map(CATEGORY_INDEX).to_numpy()
    kappa = profile["season_kappa"].to_numpy()
    season = _category_seasonality(cal)[category] ** kappa[:, None]
    rates *= season / season[:, cal.history].mean(axis=1, keepdims=True)

    years = (np.arange(cal.n_days) - cal.history_start) / 365.25 - cfg.history_years / 2
    rates *= np.exp(np.outer(profile["trend_per_year"].to_numpy(), years))
    rates *= promos.uplift

    festive = np.array([CATEGORIES[c].songkran_surge for c in category])
    rates[np.ix_(festive, cal.songkran_pre)] *= SONGKRAN_SURGE

    rates *= _lifecycle(cal, master)
    bases = customer_bases(cfg, cal, master)
    rates *= (bases.weights @ bases.active) / bases.weights.sum(axis=1, keepdims=True)

    erratic = np.flatnonzero(profile["pattern"].to_numpy() == "erratic")
    if erratic.size:
        rng = stream(cfg.seed, "erratic-intensity")
        week = _iso_week(cal)
        shape = profile["gamma_shape"].to_numpy()[erratic][:, None]
        intensity = rng.gamma(shape, 1.0 / shape, size=(erratic.size, week.max() + 1))
        rates[erratic] *= intensity[:, week]
    assert rates.shape == (n_sku, cal.n_days)
    return rates


def customer_bases(cfg: SynthConfig, cal: Calendar, master: Master) -> CustomerBases:
    """Which customers buy each SKU, how much each contributes, and when customers are active."""
    rng = stream(cfg.seed, "customer-bases")
    customers, cprofile = master.customers, master.customer_profile
    n_cust = len(customers)
    ctype = customers["customer_type"].map({t: k for k, t in enumerate(CUSTOMER_TYPES)}).to_numpy()
    size = cprofile["size_weight"].to_numpy()
    category = master.materials["category"].map(CATEGORY_INDEX).to_numpy()
    pattern = master.sku_profile["pattern"].to_numpy()

    weights = np.zeros((len(category), n_cust))
    cap = max(1, round(MAX_BASE_SHARE * n_cust))
    for i in range(len(category)):
        lo, hi = BASE_SIZE[pattern[i]]
        k = min(int(rng.integers(lo, hi + 1)), cap)
        pick = size**BASE_SIZE_EXPONENT * TYPE_CATEGORY_AFFINITY[ctype, category[i]]
        chosen = rng.choice(n_cust, size=k, replace=False, p=pick / pick.sum())
        weights[i, chosen] = np.round(size[chosen] * rng.lognormal(0.0, 0.5, size=k), 9)
    row = {code: i for i, code in enumerate(master.materials["material_code"])}
    for i, pred in enumerate(master.materials["predecessor_material_code"]):
        if pred is not None and not pd.isna(pred):
            weights[i] = weights[row[pred]]  # a successor is bought by its predecessor's customers

    first = cal.dates[0]
    start = np.array(cprofile["active_from"].tolist(), dtype="datetime64[D]")
    end = np.array(
        [
            d if d is not None and not pd.isna(d) else cal.dates[-1].item()
            for d in cprofile["active_to"]
        ],
        dtype="datetime64[D]",
    )
    day = np.arange(cal.n_days)
    active = (day[None, :] >= (start - first).astype(int)[:, None]) & (
        day[None, :] <= (end - first).astype(int)[:, None]
    )
    return CustomerBases(weights=weights, active=active)


def generate_lines(cfg: SynthConfig, cal: Calendar, master: Master, rates: np.ndarray) -> Lines:
    rng = stream(cfg.seed, "order-lines")
    counts = rng.poisson(rates).ravel()
    cell = np.repeat(np.arange(counts.size), counts)
    sku = (cell // cal.n_days).astype(np.int32)
    day = (cell % cal.n_days).astype(np.int32)

    bases = customer_bases(cfg, cal, master)
    customer = _assign_customers(rng, sku, day, bases)

    materials, profile, customers = master.materials, master.sku_profile, master.customers
    units = materials["units_per_box"].to_numpy()[sku]
    boxed = (materials["sales_unit"].to_numpy() == "BOX")[sku]
    fast = np.isin(profile["pattern"].to_numpy(), ("smooth", "erratic"))[sku]
    retail = (customers["customer_type"].to_numpy() == "RETAIL")[customer]
    piece_line = boxed & fast & retail & (rng.random(sku.size) < RETAIL_PIECE_SHARE)
    order_unit = np.where(boxed & ~piece_line, ORDER_UNIT_BOX, ORDER_UNIT_PC).astype(np.int8)

    median = profile["median_order_qty"].to_numpy()[sku]
    median = np.where(
        piece_line, np.maximum(1.0, median * units * PIECE_ORDER_SHARE_OF_BOX), median
    )
    size = master.customer_profile["size_weight"].to_numpy()
    relative = np.clip((size / np.median(size)) ** CUSTOMER_SIZE_EFFECT, 0.5, 2.5)
    median = np.where(fast, median * relative[customer], median)
    sigma = profile["size_sigma"].to_numpy()[sku]
    qty_unit = np.maximum(1, np.round(median * np.exp(sigma * rng.standard_normal(sku.size))))
    qty_unit = qty_unit.astype(np.int64)
    qty_base = qty_unit * np.where(order_unit == ORDER_UNIT_BOX, units, 1)

    plant_index = {w.plant: k for k, w in enumerate(WAREHOUSES)}
    plant = customers["delivering_plant"].map(plant_index).to_numpy().astype(np.int8)[customer]
    return Lines(
        sku=sku,
        day=day,
        customer=customer,
        plant=plant,
        order_unit=order_unit,
        qty_unit=qty_unit,
        qty_base=qty_base.astype(np.int64),
    )


def _assign_customers(rng, sku: np.ndarray, day: np.ndarray, bases: CustomerBases) -> np.ndarray:
    """Draw each line's customer from its SKU's base, among customers active on that day."""
    customer = np.empty(sku.size, dtype=np.int32)
    bounds = np.searchsorted(sku, np.arange(bases.weights.shape[0] + 1))
    for i in range(bases.weights.shape[0]):
        lo, hi = bounds[i], bounds[i + 1]
        if lo == hi:
            continue
        members = np.flatnonzero(bases.weights[i])
        cdf = np.cumsum(bases.weights[i, members])
        cdf /= cdf[-1]
        todo = np.arange(lo, hi)
        for _ in range(1000):
            pick = members[np.searchsorted(cdf, rng.random(todo.size), side="right")]
            customer[todo] = pick
            todo = todo[~bases.active[pick, day[todo]]]
            if todo.size == 0:
                break
        else:  # pragma: no cover - only reachable if a line was generated on an inactive base
            raise RuntimeError(f"no active customer for SKU row {i}")
    return customer


def _category_seasonality(cal: Calendar) -> np.ndarray:
    """Daily seasonal factor per category, interpolated between mid-month profile values."""
    month = cal.dates.astype("datetime64[M]")
    day_in_month = (cal.dates - month.astype("datetime64[D]")).astype(int)
    month_len = ((month + 1).astype("datetime64[D]") - month.astype("datetime64[D]")).astype(int)
    position = (month.astype(int) % 12) + (day_in_month + 0.5) / month_len
    anchors = np.arange(-1, 13) + 0.5
    out = np.empty((len(CATEGORIES), cal.n_days))
    for c, cat in enumerate(CATEGORIES):
        profile = np.asarray(cat.monthly_profile)
        values = np.concatenate([[profile[-1]], profile, [profile[0]]])
        out[c] = np.interp(position, anchors, values)
    return out


def _lifecycle(cal: Calendar, master: Master) -> np.ndarray:
    """0 before launch and from discontinuation on; logistic ramp-up; linear decline to 0.4."""
    materials, profile = master.materials, master.sku_profile
    factor = np.ones((len(materials), cal.n_days))
    day = np.arange(cal.n_days)
    first = cal.dates[0]
    for i in range(len(materials)):
        if profile.at[i, "lifecycle"] == "new":
            launch = int((np.datetime64(materials.at[i, "launch_date"], "D") - first).astype(int))
            ramp = float(profile.at[i, "ramp_weeks"]) * 7.0
            since = day[launch:] - launch
            factor[i, launch:] = 1.0 / (1.0 + np.exp(-(since - ramp / 2.0) / (ramp / 6.0)))
            factor[i, :launch] = 0.0
        stop = materials.at[i, "discontinued_date"]
        if stop is not None and not pd.isna(stop):
            stop = int((np.datetime64(stop, "D") - first).astype(int))
            decline = int(profile.at[i, "decline_weeks"]) * 7
            factor[i, stop - decline : stop] *= np.linspace(1.0, 0.4, decline)
            factor[i, stop:] = 0.0
    return factor


def _iso_week(cal: Calendar) -> np.ndarray:
    """Monday-based week number of each calendar day, starting at 0."""
    week = (cal.dates.view("int64") + 3) // 7  # 1970-01-01 was a Thursday
    return (week - week[0]).astype(int)
