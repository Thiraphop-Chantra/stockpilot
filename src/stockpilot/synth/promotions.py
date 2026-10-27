"""Trade promotions: a planned price discount lifts demand, and forward buying causes a dip after.

The observable promotion calendar (what the company planned) covers the history and the hidden
horizon; the true uplift and dip of each promotion are ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from stockpilot.synth.calendar import Calendar
from stockpilot.synth.config import SynthConfig
from stockpilot.synth.master import Master
from stockpilot.synth.rng import stream

PROMOS_PER_YEAR, MAX_PROMOS_PER_YEAR = 2.5, 6
DURATIONS = (7, 14, 21, 28)  # calendar days
DISCOUNTS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
MAX_UPLIFT = 3.5
MIN_GAP_DAYS = 21  # between the end of one promotion's dip and the next promotion
MAX_DIP_DAYS = 14
DIP_PER_UPLIFT, MIN_DIP = 0.25, 0.5  # dip = max(MIN_DIP, 1 - DIP_PER_UPLIFT * (uplift - 1))
PLANNER_ANTICIPATION = 0.6  # share of the true uplift the planner adds to stock targets


@dataclass(frozen=True)
class Promotions:
    table: pd.DataFrame  # observable promotion calendar
    uplift: np.ndarray  # float32 [sku, day]: demand multiplier (uplift, dip, else 1)
    discount: np.ndarray  # float32 [sku, day]: price discount fraction on promotion days
    planning: np.ndarray  # float32 [sku, day]: planner's multiplier on stock targets
    truth: pd.DataFrame  # true uplift and dip per promotion (column ``sku`` is in-memory only)


def build_promotions(cfg: SynthConfig, cal: Calendar, master: Master) -> Promotions:
    rng = stream(cfg.seed, "promotions")
    materials, profile = master.materials, master.sku_profile
    n_sku = len(materials)
    uplift = np.ones((n_sku, cal.n_days), dtype=np.float32)
    discount = np.zeros((n_sku, cal.n_days), dtype=np.float32)
    planning = np.ones((n_sku, cal.n_days), dtype=np.float32)

    suppliers = master.suppliers.set_index("supplier_id")
    cover = (
        suppliers.loc[materials["supplier_id"], "planned_lead_time_days"].to_numpy()
        + suppliers.loc[materials["supplier_id"], "order_cycle_days"].to_numpy()
    )
    first_year = int(str(cal.dates[0])[:4])
    last_year = int(str(cal.dates[-1])[:4])
    rows = []
    for i in np.flatnonzero(profile["promo_eligible"].to_numpy()):
        active_from = _index(cal, max(materials.at[i, "launch_date"], cal.dates[0].item()))
        active_to = cal.n_days - 1
        if pd.notna(materials.at[i, "discontinued_date"]):
            decline_days = int(profile.at[i, "decline_weeks"]) * 7
            stop = _index(cal, materials.at[i, "discontinued_date"]) - decline_days
            active_to = min(active_to, stop - 1)
        elasticity = float(profile.at[i, "promo_elasticity"])
        busy_until = -1
        for year in range(first_year, last_year + 1):
            k = min(MAX_PROMOS_PER_YEAR, int(rng.poisson(PROMOS_PER_YEAR)))
            year_start = max(0, _index_clamped(cal, date(year, 1, 1)))
            year_end = min(cal.n_days - 1, _index_clamped(cal, date(year, 12, 31)))
            starts = np.sort(rng.integers(year_start, year_end + 1, size=k), kind="stable")
            for start in starts.tolist():
                duration = int(rng.choice(DURATIONS))
                disc = float(rng.choice(DISCOUNTS))
                end = start + duration - 1
                if start <= busy_until + MIN_GAP_DAYS or start < active_from or end > active_to:
                    continue
                lift = round(min(MAX_UPLIFT, (1.0 - disc) ** (-elasticity)), 6)
                dip = round(max(MIN_DIP, 1.0 - DIP_PER_UPLIFT * (lift - 1.0)), 6)
                dip_end = min(cal.n_days - 1, end + min(MAX_DIP_DAYS, duration))
                uplift[i, start : end + 1] = lift
                uplift[i, end + 1 : dip_end + 1] = dip
                discount[i, start : end + 1] = disc
                lead_in = max(0, start - int(cover[i]))
                planning[i, lead_in : end + 1] = 1.0 + PLANNER_ANTICIPATION * (lift - 1.0)
                busy_until = dip_end
                rows.append((i, start, end, dip_end, disc, lift, dip))

    truth = pd.DataFrame(
        rows, columns=["sku", "start", "end", "dip_end", "discount", "uplift", "dip_factor"]
    )
    codes = materials["material_code"].to_numpy()
    truth = pd.DataFrame(
        {
            "sku": truth["sku"].to_numpy(),
            "material_code": codes[truth["sku"].to_numpy()],
            "start_date": [cal.dates[k].item() for k in truth["start"]],
            "end_date": [cal.dates[k].item() for k in truth["end"]],
            "dip_end_date": [cal.dates[k].item() for k in truth["dip_end"]],
            "discount_pct": np.round(truth["discount"].to_numpy() * 100, 6),
            "uplift": truth["uplift"].to_numpy(),
            "dip_factor": truth["dip_factor"].to_numpy(),
        }
    )
    truth = truth.sort_values(["start_date", "material_code"], kind="stable").reset_index(drop=True)
    truth.insert(0, "promo_id", [f"PR{k + 1:06d}" for k in range(len(truth))])
    visible = (truth["end_date"] >= cfg.start) & (truth["start_date"] <= cfg.horizon_end)
    table = truth.loc[visible, ["promo_id", "material_code", "start_date", "end_date"]].copy()
    table["discount_pct"] = truth.loc[visible, "discount_pct"].round(0).astype(int)
    return Promotions(
        table=table.reset_index(drop=True),
        uplift=uplift,
        discount=discount,
        planning=planning,
        truth=truth,
    )


def _index(cal: Calendar, day: date) -> int:
    return cal.index_of(np.datetime64(day, "D"))


def _index_clamped(cal: Calendar, day: date) -> int:
    return int((np.datetime64(day, "D") - cal.dates[0]).astype(int))
