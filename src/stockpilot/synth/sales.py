"""Clean ERP sales records: what the company invoiced, before any data-quality problem.

Every shipped order line becomes one invoice item. Lines of one customer on one day form one
billing document, numbered in date order and, within a day, in random entry order (items 10, 20,
...). A line shipped in full keeps its order unit; a line cut short by a stockout ships what was
left, invoiced in pieces. Net values use the year's price list, the customer channel's discount
and any promotion discount.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from stockpilot.synth.calendar import Calendar
from stockpilot.synth.config import SynthConfig
from stockpilot.synth.demand import ORDER_UNIT_BOX, Lines
from stockpilot.synth.geo import WAREHOUSES
from stockpilot.synth.inventory import Inventory
from stockpilot.synth.master import CUSTOMER_TYPES, Master
from stockpilot.synth.promotions import Promotions
from stockpilot.synth.rng import stream

# Standard discount off list price by customer channel (CUSTOMER_TYPES order).
CHANNEL_DISCOUNT = (0.08, 0.12, 0.0, 0.03, 0.05)
FIRST_DOCUMENT = 9_000_000_001  # SAP-style 10-digit billing document numbers


def build_sales_clean(
    cfg: SynthConfig,
    cal: Calendar,
    master: Master,
    lines: Lines,
    inv: Inventory,
    promos: Promotions,
) -> pd.DataFrame:
    shipped = np.flatnonzero(
        (inv.filled_qty > 0) & (lines.day >= cal.history_start) & (lines.day <= cal.history_end)
    )
    sku, day = lines.sku[shipped], lines.day[shipped]
    customer = lines.customer[shipped]
    pieces = inv.filled_qty[shipped]
    full = pieces == lines.qty_base[shipped]
    boxed = full & (lines.order_unit[shipped] == ORDER_UNIT_BOX)
    quantity = np.where(full, lines.qty_unit[shipped], pieces)

    materials, customers = master.materials, master.customers
    price = _price_lists(cal, master)[sku, _year_index(cal, day)]
    ctype = customers["customer_type"].map({t: k for k, t in enumerate(CUSTOMER_TYPES)}).to_numpy()
    channel = np.asarray(CHANNEL_DISCOUNT)[ctype[customer]]
    promo = promos.discount[sku, day].astype(np.float64)
    net_value = np.round(pieces * price * (1.0 - channel) * (1.0 - promo), 2)

    frame = pd.DataFrame(
        {
            "posting_date": cal.dates[day].astype("datetime64[s]"),
            "customer_id": customers["customer_id"].to_numpy()[customer],
            "material_code": materials["material_code"].to_numpy()[sku],
            "plant": np.array([w.plant for w in WAREHOUSES])[lines.plant[shipped]],
            "quantity": quantity.astype(np.int64),
            "unit": np.where(boxed, "BOX", "PC"),
            "net_value_thb": net_value,
        }
    )
    # Documents of a day are numbered in (random) entry order, not by customer number.
    rng = stream(cfg.seed, "document-order")
    visit = day.astype(np.int64) * len(customers) + customer
    visits, which = np.unique(visit, return_inverse=True)
    entry = rng.permutation(visits.size)[which]
    frame = frame.iloc[np.lexsort((sku, entry, day))].reset_index(drop=True)
    new_doc = (frame["posting_date"] != frame["posting_date"].shift()) | (
        frame["customer_id"] != frame["customer_id"].shift()
    )
    frame.insert(0, "billing_doc", [f"{FIRST_DOCUMENT - 1 + k:010d}" for k in new_doc.cumsum()])
    frame.insert(1, "item", ((frame.groupby("billing_doc").cumcount() + 1) * 10).astype(np.int64))
    return frame


def _year_index(cal: Calendar, day: np.ndarray) -> np.ndarray:
    years = cal.dates.astype("datetime64[Y]").astype(int) + 1970
    return years[day] - years[cal.history_start]


def _price_lists(cal: Calendar, master: Master) -> np.ndarray:
    """Price per piece by SKU and history year: the current list price, deflated yearly."""
    first_year = int(str(cal.dates[cal.history_start])[:4])
    last_year = int(str(cal.dates[cal.history_end])[:4])
    prices = master.materials["list_price_thb"].to_numpy()
    growth = master.sku_profile["price_growth_per_year"].to_numpy()
    table = np.empty((len(prices), last_year - first_year + 1))
    for i in range(len(prices)):
        for k, year in enumerate(range(first_year, last_year + 1)):
            table[i, k] = round(prices[i] / math.pow(1.0 + growth[i], last_year - year), 2)
    return table
