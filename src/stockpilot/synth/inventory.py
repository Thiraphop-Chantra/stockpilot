"""Replenishment of every SKU at every warehouse under the company's current (naive) policy.

The fictional company reviews stock on each supplier's order day and orders up to a target level
S = avg * promo_factor * (planned lead time + review period) + z * sd * sqrt(lead + review),
where avg and sd come from the last 91 days of *sales* (refreshed monthly) and z differs from
SKU to SKU. The policy ignores lead-time variability and stockout censoring, so stockouts happen
naturally, mostly for volatile items and late suppliers. Sales are true demand capped by stock;
the unfilled rest is lost.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from stockpilot.synth.calendar import Calendar
from stockpilot.synth.config import SynthConfig
from stockpilot.synth.demand import Lines, _iso_week
from stockpilot.synth.geo import TRANSIT_DAYS, WAREHOUSES
from stockpilot.synth.master import Master
from stockpilot.synth.rng import stream

WINDOW_DAYS = 91  # trailing sales window of the planner
LONG_WINDOW_DAYS = 365
LONG_FLOOR = 0.7  # planner never plans below 70% of the trailing-year average
SERVICE_FACTOR = (1.3, 2.8)  # z, drawn per SKU and warehouse
FORECAST_NOISE = 0.3  # lognormal spread of the planner's launch/initial estimates
MAX_LEAD_DAYS = 400
RING = 512  # arrival ring buffer, longer than any lead time


@dataclass(frozen=True)
class Inventory:
    filled_qty: np.ndarray  # int64 per order line: pieces shipped (0 = lost or not simulated)
    demand_daily: pd.DataFrame  # truth
    purchase_orders: pd.DataFrame  # observable
    open_po_receipts: pd.DataFrame  # truth: actual receipt of orders open at extraction
    stock_month_end: pd.DataFrame  # observable
    policy: pd.DataFrame  # truth: service factor per SKU and warehouse
    fill_rate: float  # units shipped / units demanded over the history


def simulate(
    cfg: SynthConfig, cal: Calendar, master: Master, lines: Lines, planning: np.ndarray
) -> Inventory:
    rng = stream(cfg.seed, "inventory")
    materials, profile = master.materials, master.sku_profile
    n_sim = cal.history_end + 1  # warm-up + history; the horizon is never simulated

    # Series = (SKU, plant) pairs that ever receive an order line.
    key = lines.sku.astype(np.int64) * len(WAREHOUSES) + lines.plant
    series_key, line_series = np.unique(key, return_inverse=True)
    sku = (series_key // len(WAREHOUSES)).astype(np.int64)
    plant = (series_key % len(WAREHOUSES)).astype(np.int64)
    n = series_key.size
    in_sim = lines.day < n_sim
    demand = np.bincount(
        line_series[in_sim] * n_sim + lines.day[in_sim], lines.qty_base[in_sim], n * n_sim
    ).reshape(n, n_sim)

    suppliers = master.suppliers.reset_index(drop=True)
    sup_index = {s: k for k, s in enumerate(suppliers["supplier_id"])}
    sup = materials["supplier_id"].map(sup_index).to_numpy()[sku]
    transit = np.array([TRANSIT_DAYS[w.plant] for w in WAREHOUSES])[plant]
    planned = suppliers["planned_lead_time_days"].to_numpy()[sup]
    review_period = suppliers["order_cycle_days"].to_numpy()[sup]
    cover = (planned + transit + review_period).astype(float)
    units = materials["units_per_box"].to_numpy()[sku]
    moq = materials["moq"].to_numpy()[sku].astype(float)
    z = np.round(rng.uniform(*SERVICE_FACTOR, size=n), 6)

    launch, phase_out, alive = _series_windows(cal, materials, profile, sku, n_sim)
    next_working = _next_working(cal)
    launch_receipt = np.array([_last_working_on_or_before(cal, d) for d in launch])
    review = review_schedule(cfg, cal, suppliers)[:, :n_sim]
    lead_bias, lead_sigma, disruption = _lead_time_truth(cal, master, suppliers)

    # Planner's initial estimates: realised demand of the first 91 days, blurred.
    avg = np.empty(n)
    sd = np.empty(n)
    for s in range(n):
        window = demand[s, launch[s] : launch[s] + WINDOW_DAYS]
        avg[s] = window.mean() if window.size else 0.0
        sd[s] = window.std() if window.size else 0.0
    avg *= rng.lognormal(0.0, FORECAST_NOISE, size=n)
    sd *= rng.lognormal(0.0, FORECAST_NOISE, size=n)

    def target(rows: np.ndarray, t: int) -> np.ndarray:
        level = avg[rows] * planning[sku[rows], t] * cover[rows]
        level += z[rows] * sd[rows] * np.sqrt(cover[rows])
        return np.maximum(moq[rows], level)

    on_hand = np.zeros(n)
    on_order = np.zeros(n)
    arrivals = np.zeros((RING, n))
    sales = np.zeros((n, n_sim))
    empty = np.zeros((n, n_sim), dtype=bool)
    orders: list[tuple[np.ndarray, int, np.ndarray, np.ndarray]] = []
    month_start = cal.dates.astype("datetime64[M]").astype("datetime64[D]") == cal.dates
    snapshots: list[tuple[int, np.ndarray, np.ndarray]] = []
    month_ends = set(cal.month_end_idx.tolist())

    start_rows = np.flatnonzero(launch_receipt <= 0)
    on_hand[start_rows] = np.round(
        target(start_rows, 0) * rng.uniform(0.5, 1.0, size=start_rows.size)
    )
    launches: dict[int, list[int]] = {}
    for s in np.flatnonzero(launch_receipt > 0):
        launches.setdefault(int(launch_receipt[s]), []).append(int(s))

    for t in range(n_sim):
        slot = t % RING
        on_hand += arrivals[slot]
        on_order -= arrivals[slot]
        arrivals[slot] = 0.0
        if t in launches:
            rows = np.array(launches[t])
            qty = np.ceil(target(rows, t) / units[rows]) * units[rows]
            on_hand[rows] += qty
            order_day = np.maximum(0, t - planned[rows] - transit[rows])
            orders.append((rows, -1, qty, np.stack([order_day, np.full(rows.size, t)])))

        sold = np.minimum(demand[:, t], on_hand)
        on_hand -= sold
        sales[:, t] = sold
        empty[:, t] = (on_hand == 0) & alive[:, t]

        if month_start[t] and t >= WINDOW_DAYS:
            ripe = (t - launch) >= WINDOW_DAYS
            recent = sales[:, t - WINDOW_DAYS : t]
            long_avg = sales[:, max(0, t - LONG_WINDOW_DAYS) : t].mean(axis=1)
            avg = np.where(ripe, np.maximum(recent.mean(axis=1), LONG_FLOOR * long_avg), avg)
            sd = np.where(ripe, recent.std(axis=1), sd)

        reviewing = np.flatnonzero(review[sup, t] & (t >= launch_receipt) & (t < phase_out))
        if reviewing.size:
            need = target(reviewing, t) - on_hand[reviewing] - on_order[reviewing]
            rows = reviewing[need > 0]
            if rows.size:
                qty = np.maximum(need[need > 0], moq[rows])
                qty = np.ceil(qty / units[rows]) * units[rows]
                group = sup[rows] * len(WAREHOUSES) + plant[rows]
                groups, which = np.unique(group, return_inverse=True)
                gsup = groups // len(WAREHOUSES)
                noise = rng.standard_normal(groups.size)
                lead = (
                    suppliers["planned_lead_time_days"].to_numpy()[gsup]
                    * lead_bias[gsup]
                    * np.exp(lead_sigma[gsup] * noise - lead_sigma[gsup] ** 2 / 2)
                    * disruption[gsup, t]
                )
                lead = np.minimum(MAX_LEAD_DAYS, np.maximum(1, np.round(lead))).astype(int)
                arrive = t + lead[which] + transit[rows]
                arrive = np.where(
                    arrive < next_working.size,
                    next_working[np.minimum(arrive, next_working.size - 1)],
                    arrive,
                )
                due = arrive < n_sim
                np.add.at(arrivals, (arrive[due] % RING, rows[due]), qty[due])
                on_order[rows] += qty
                orders.append((rows, t, qty, arrive))

        if t in month_ends:
            keep = (t >= launch_receipt) & (alive[:, t] | (on_hand > 0))
            snapshots.append((t, np.flatnonzero(keep), on_hand[keep].copy()))

    if (on_hand < 0).any():  # pragma: no cover - invariant
        raise AssertionError("negative stock")

    codes = materials["material_code"].to_numpy()
    plants = np.array([w.plant for w in WAREHOUSES])
    filled = _allocate(rng, lines, line_series, sales, n_sim)
    hist = slice(cal.history_start, cal.history_end + 1)
    total_demand = demand[:, hist].sum()
    fill_rate = float(sales[:, hist].sum() / total_demand) if total_demand else 1.0

    purchase_orders, open_receipts = _purchase_orders(
        cfg, cal, orders, sku, plant, sup, suppliers, codes, plants, planned, transit, next_working
    )
    return Inventory(
        filled_qty=filled,
        demand_daily=_demand_daily(
            cal, lines, line_series, demand, sales, empty, sku, plant, codes, plants
        ),
        purchase_orders=purchase_orders,
        open_po_receipts=open_receipts,
        stock_month_end=_snapshots(cal, snapshots, sku, plant, codes, plants),
        policy=pd.DataFrame(
            {"material_code": codes[sku], "plant": plants[plant], "service_factor": z}
        ),
        fill_rate=round(fill_rate, 9),
    )


def _series_windows(cal, materials, profile, sku, n_sim):
    """First demand day, first day without replenishment, and alive mask per series."""
    first = cal.dates[0]
    launch_day = np.array(
        [max(0, int((np.datetime64(d, "D") - first).astype(int))) for d in materials["launch_date"]]
    )
    stop_day = np.full(len(materials), n_sim)
    phase = np.full(len(materials), n_sim)
    for i, d in enumerate(materials["discontinued_date"]):
        if d is not None and not pd.isna(d):
            stop_day[i] = int((np.datetime64(d, "D") - first).astype(int))
            phase[i] = stop_day[i] - int(profile.at[i, "decline_weeks"]) * 7
    day = np.arange(n_sim)
    alive = (day[None, :] >= launch_day[sku][:, None]) & (day[None, :] < stop_day[sku][:, None])
    return launch_day[sku], phase[sku], alive


def _next_working(cal: Calendar) -> np.ndarray:
    """For each calendar day, the first working day on or after it (len(cal) when none)."""
    nxt = np.full(cal.n_days, cal.n_days)
    upcoming = cal.n_days
    for t in range(cal.n_days - 1, -1, -1):
        if cal.is_working[t]:
            upcoming = t
        nxt[t] = upcoming
    return nxt


def _last_working_on_or_before(cal: Calendar, day: int) -> int:
    while day > 0 and not cal.is_working[day]:
        day -= 1
    return day


def review_schedule(cfg: SynthConfig, cal: Calendar, suppliers: pd.DataFrame) -> np.ndarray:
    """Supplier order days; a review falling on a closed day moves to the next working day."""
    rng = stream(cfg.seed, "review-schedule")
    week = _iso_week(cal)
    nxt = _next_working(cal)
    review = np.zeros((len(suppliers), cal.n_days), dtype=bool)
    for j, row in enumerate(suppliers.itertuples(index=False)):
        every = row.order_cycle_days // 7
        phase = int(rng.integers(every))
        nominal = np.flatnonzero((cal.weekday == row.order_weekday) & ((week - phase) % every == 0))
        moved = nxt[nominal]
        review[j, moved[moved < cal.n_days]] = True
    return review


def _lead_time_truth(cal: Calendar, master: Master, suppliers: pd.DataFrame):
    truth = master.supplier_lead_time.set_index("supplier_id").loc[suppliers["supplier_id"]]
    disruption = np.ones((len(suppliers), cal.n_days))
    index = {s: k for k, s in enumerate(suppliers["supplier_id"])}
    for row in master.disruptions.itertuples(index=False):
        a = cal.index_of(np.datetime64(row.start_date, "D"))
        b = cal.index_of(np.datetime64(row.end_date, "D"))
        disruption[index[row.supplier_id], a : b + 1] = row.lead_time_factor
    return truth["lead_time_bias"].to_numpy(), truth["lead_time_sigma"].to_numpy(), disruption


def _allocate(rng, lines: Lines, line_series: np.ndarray, sales: np.ndarray, n_sim: int):
    """Ship each day's sales to that day's order lines in random arrival order."""
    filled = np.zeros(len(lines), dtype=np.int64)
    idx = np.flatnonzero(lines.day < n_sim)
    order = idx[np.lexsort((rng.random(idx.size), lines.day[idx], line_series[idx]))]
    cell = line_series[order].astype(np.int64) * n_sim + lines.day[order]
    qty = lines.qty_base[order]
    starts = np.r_[0, np.flatnonzero(np.diff(cell)) + 1]
    before = np.cumsum(qty) - qty
    before -= np.repeat(before[starts], np.diff(np.r_[starts, cell.size]))
    available = sales.ravel()[cell]
    filled[order] = np.clip(available - before, 0, qty).astype(np.int64)
    return filled


def _purchase_orders(
    cfg, cal, orders, sku, plant, sup, suppliers, codes, plants, planned, transit, nxt
):
    rows, order_day, qty, arrive = [], [], [], []
    for r, t, q, a in orders:
        if t == -1:  # launch stock: a[0] = order day, a[1] = receipt day
            order_day.append(a[0])
            arrive.append(a[1])
        else:
            order_day.append(np.full(r.size, t))
            arrive.append(a)
        rows.append(r)
        qty.append(q)
    rows = np.concatenate(rows) if rows else np.array([], dtype=int)
    order_day = np.concatenate(order_day).astype(int) if order_day else np.array([], dtype=int)
    arrive = np.concatenate(arrive).astype(int) if arrive else np.array([], dtype=int)
    qty = np.concatenate(qty).astype(np.int64) if qty else np.array([], dtype=np.int64)

    relevant = arrive >= cal.history_start
    rows, order_day, arrive, qty = (
        rows[relevant],
        order_day[relevant],
        arrive[relevant],
        qty[relevant],
    )
    supplier_ids = suppliers["supplier_id"].to_numpy()[sup[rows]]
    frame = pd.DataFrame(
        {
            "supplier_id": supplier_ids,
            "material_code": codes[sku[rows]],
            "plant": plants[plant[rows]],
            "order_day": order_day,
            "arrive": arrive,
            "planned_day": np.minimum(
                nxt[np.minimum(order_day + planned[rows] + transit[rows], cal.n_days - 1)],
                cal.n_days - 1,
            ),
            "quantity": qty,
        }
    )
    frame = frame.sort_values(
        ["order_day", "supplier_id", "plant", "material_code"], kind="stable"
    ).reset_index(drop=True)
    po_key = frame["order_day"].astype(str) + "|" + frame["supplier_id"] + "|" + frame["plant"]
    first_of_po = po_key.ne(po_key.shift())
    frame["po_number"] = [f"45{k:08d}" for k in first_of_po.cumsum()]
    frame["po_item"] = (frame.groupby("po_number").cumcount() + 1) * 10

    dates = cal.dates
    open_mask = frame["arrive"].to_numpy() > cal.history_end
    receipt = [
        None if o else dates[a].item() for a, o in zip(frame["arrive"], open_mask, strict=True)
    ]
    purchase_orders = pd.DataFrame(
        {
            "po_number": frame["po_number"],
            "po_item": frame["po_item"].astype(np.int64),
            "supplier_id": frame["supplier_id"],
            "material_code": frame["material_code"],
            "plant": frame["plant"],
            "order_date": [dates[d].item() for d in frame["order_day"]],
            "planned_delivery_date": [dates[d].item() for d in frame["planned_day"]],
            "receipt_date": receipt,
            "quantity": frame["quantity"].astype(np.int64),
            "unit": "PC",
        }
    )
    actual_day = frame.loc[open_mask, "arrive"].to_numpy()
    first = dates[0]
    open_receipts = pd.DataFrame(
        {
            "po_number": frame.loc[open_mask, "po_number"].to_numpy(),
            "po_item": frame.loc[open_mask, "po_item"].to_numpy().astype(np.int64),
            "actual_receipt_date": [(first + int(d)).item() for d in actual_day],
        }
    )
    return purchase_orders, open_receipts


def _demand_daily(cal, lines, line_series, demand, sales, empty, sku, plant, codes, plants):
    hist = slice(cal.history_start, cal.history_end + 1)
    d, s, e = demand[:, hist], sales[:, hist], empty[:, hist]
    rows, cols = np.nonzero((d > 0) | e)
    history = pd.DataFrame(
        {
            "date": cal.dates[hist][cols],
            "material_code": codes[sku[rows]],
            "plant": plants[plant[rows]],
            "demand_qty": d[rows, cols].astype(np.int64),
            "sales_qty": pd.array(s[rows, cols].astype(np.int64), dtype="Int64"),
            "lost_qty": pd.array((d[rows, cols] - s[rows, cols]).astype(np.int64), dtype="Int64"),
            "stockout": pd.array(e[rows, cols] | (d[rows, cols] > s[rows, cols]), dtype="boolean"),
            "in_horizon": False,
        }
    )
    future = lines.day > cal.history_end
    cell = line_series[future].astype(np.int64) * cal.n_days + lines.day[future]
    uniq, total = np.unique(cell, return_inverse=True)
    qty = np.bincount(total, lines.qty_base[future])
    series, day = uniq // cal.n_days, uniq % cal.n_days
    horizon = pd.DataFrame(
        {
            "date": cal.dates[day],
            "material_code": codes[sku[series]],
            "plant": plants[plant[series]],
            "demand_qty": qty.astype(np.int64),
            "sales_qty": pd.array([pd.NA] * len(uniq), dtype="Int64"),
            "lost_qty": pd.array([pd.NA] * len(uniq), dtype="Int64"),
            "stockout": pd.array([pd.NA] * len(uniq), dtype="boolean"),
            "in_horizon": True,
        }
    )
    out = pd.concat([history, horizon], ignore_index=True)
    return out.sort_values(["date", "material_code", "plant"], kind="stable").reset_index(drop=True)


def _snapshots(cal, snapshots, sku, plant, codes, plants):
    parts = [
        pd.DataFrame(
            {
                "snapshot_date": cal.dates[t].item(),
                "material_code": codes[sku[rows]],
                "plant": plants[plant[rows]],
                "on_hand_qty": qty.astype(np.int64),
            }
        )
        for t, rows, qty in snapshots
    ]
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values(["snapshot_date", "material_code", "plant"], kind="stable").reset_index(
        drop=True
    )
