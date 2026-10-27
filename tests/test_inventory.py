"""Replenishment simulation: purchase orders, stockouts and stock levels."""

from datetime import timedelta

import numpy as np
import pandas as pd

from stockpilot.synth.inventory import review_schedule


def test_sales_never_exceed_true_demand(small_inventory):
    d = small_inventory.demand_daily
    hist = d[~d["in_horizon"]]
    assert (hist["sales_qty"] <= hist["demand_qty"]).all()
    assert (hist["lost_qty"] == hist["demand_qty"] - hist["sales_qty"]).all()
    assert hist["stockout"].any()


def test_fill_rate_is_realistic_but_imperfect(small_inventory):
    assert 0.80 < small_inventory.fill_rate < 0.995


def test_line_fills_add_up_to_daily_sales(small_cal, small_lines, small_inventory):
    filled = small_inventory.filled_qty
    assert ((filled >= 0) & (filled <= small_lines.qty_base)).all()
    history = (small_lines.day >= small_cal.history_start) & (
        small_lines.day <= small_cal.history_end
    )
    assert filled[~history & (small_lines.day > small_cal.history_end)].sum() == 0
    total_sales = small_inventory.demand_daily.loc[lambda d: ~d["in_horizon"], "sales_qty"].sum()
    assert filled[history].sum() == total_sales


def test_receipts_follow_orders_on_working_days(small_cal, small_inventory):
    po = small_inventory.purchase_orders
    received = po[po["receipt_date"].notna()]
    assert (received["receipt_date"] >= received["order_date"]).all()
    days = np.array(received["receipt_date"].tolist(), dtype="datetime64[D]")
    assert small_cal.is_working[[small_cal.index_of(d) for d in days]].all()
    assert (po["quantity"] > 0).all()
    assert po[["po_number", "po_item"]].duplicated().sum() == 0


def test_observed_lead_times_vary_per_supplier(small_inventory):
    po = small_inventory.purchase_orders
    received = po[po["receipt_date"].notna()].copy()
    received["lead_days"] = [
        (r - o).days for r, o in zip(received["receipt_date"], received["order_date"], strict=True)
    ]
    spread = received.groupby("supplier_id")["lead_days"].agg(["count", "std"])
    busy = spread[spread["count"] >= 5]
    assert len(busy) >= 3
    assert (busy["std"] > 0).all()


def test_open_orders_are_received_after_the_extraction(small_cfg, small_inventory):
    po = small_inventory.purchase_orders
    open_po = po[po["receipt_date"].isna()]
    assert len(open_po) > 0
    actual = open_po.merge(small_inventory.open_po_receipts, on=["po_number", "po_item"])
    assert len(actual) == len(open_po)
    assert (actual["actual_receipt_date"] >= small_cfg.extraction_date).all()
    assert (po["order_date"] <= small_cfg.history_end).all()


def test_month_end_stock_reconciles_with_receipts_and_sales(small_cal, small_inventory):
    stock = small_inventory.stock_month_end
    assert (stock["on_hand_qty"] >= 0).all()
    po = small_inventory.purchase_orders
    d = small_inventory.demand_daily
    ends = sorted(stock["snapshot_date"].unique())
    first, last = ends[0], ends[-1]
    key = ["material_code", "plant"]
    start = stock[stock["snapshot_date"] == first].set_index(key)["on_hand_qty"]
    finish = stock[stock["snapshot_date"] == last].set_index(key)["on_hand_qty"]
    got = po[po["receipt_date"].notna()]
    got = got[(got["receipt_date"] > first) & (got["receipt_date"] <= last)]
    receipts = got.groupby(key)["quantity"].sum()
    in_window = (d["date"] > pd.Timestamp(first)) & (d["date"] <= pd.Timestamp(last))
    sales = d[~d["in_horizon"] & in_window].groupby(key)["sales_qty"].sum()
    both = pd.concat(
        {"start": start, "finish": finish, "in": receipts, "out": sales}, axis=1
    ).fillna(0)
    assert (both["start"] + both["in"] - both["out"] == both["finish"]).all()


def test_every_supplier_reviews_at_least_once_per_cycle(small_cfg, small_cal, small_master):
    # A review that falls on a closure moves to the next working day (at most ~6 days later);
    # it must never be dropped, which would double the gap.
    review = review_schedule(small_cfg, small_cal, small_master.suppliers)
    hist = slice(small_cal.history_start, small_cal.history_end + 1)
    for j, cycle in enumerate(small_master.suppliers["order_cycle_days"]):
        days = np.flatnonzero(review[j, hist])
        assert np.diff(days).max() <= cycle + 6
        assert small_cal.is_working[hist][days].all()


def test_stocked_out_series_are_replenished_afterwards(small_cfg, small_master, small_inventory):
    d = small_inventory.demand_daily
    discontinued = set(
        small_master.materials.loc[lambda m: m["status"] == "DISCONTINUED", "material_code"]
    )
    cutoff = pd.Timestamp(small_cfg.history_end - timedelta(days=150))
    out = d[~d["in_horizon"] & d["stockout"].fillna(False).astype(bool) & (d["date"] <= cutoff)]
    out = out[~out["material_code"].isin(discontinued)]
    first_out = out.groupby(["material_code", "plant"])["date"].min()
    assert len(first_out) > 20
    po = small_inventory.purchase_orders
    later = po["receipt_date"].isna() | (po["receipt_date"] > small_cfg.start)
    receipts = po[later].groupby(["material_code", "plant"])["receipt_date"]
    last_receipt = receipts.apply(lambda s: s.dropna().max() if s.notna().any() else None)
    has_open = po[po["receipt_date"].isna()].groupby(["material_code", "plant"]).size()
    missing = []
    for k, when in first_out.items():
        received_after = (
            k in last_receipt.index
            and last_receipt[k] is not None
            and pd.Timestamp(last_receipt[k]) > when
        )
        if not received_after and k not in has_open.index:
            missing.append(k)
    assert missing == []
