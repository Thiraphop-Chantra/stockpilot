"""Clean ERP sales records (before any data-quality problem is injected)."""

import numpy as np
import pandas as pd


def test_billing_documents_group_one_customer_day(small_sales):
    s = small_sales
    per_doc = s.groupby("billing_doc").agg(
        customers=("customer_id", "nunique"), days=("posting_date", "nunique")
    )
    assert (per_doc["customers"] == 1).all() and (per_doc["days"] == 1).all()
    assert s[["billing_doc", "item"]].duplicated().sum() == 0
    first_items = s.groupby("billing_doc")["item"].min()
    assert (first_items == 10).all()
    assert s["billing_doc"].str.fullmatch(r"90\d{8}").all()


def test_document_numbers_follow_posting_dates(small_sales):
    docs = small_sales.drop_duplicates("billing_doc").sort_values("billing_doc")
    assert docs["posting_date"].is_monotonic_increasing


def test_quantities_match_the_shipped_pieces(small_master, small_sales, small_inventory):
    units = small_master.materials.set_index("material_code")["units_per_box"]
    per_box = small_sales["material_code"].map(units).to_numpy()
    pieces = small_sales["quantity"].to_numpy() * np.where(small_sales["unit"] == "BOX", per_box, 1)
    d = small_inventory.demand_daily
    assert pieces.sum() == d.loc[~d["in_horizon"], "sales_qty"].sum()
    assert set(small_sales["unit"]) == {"PC", "BOX"}


def test_net_values_reflect_price_channel_and_promotions(small_master, small_sales):
    s = small_sales.merge(
        small_master.materials[["material_code", "list_price_thb", "units_per_box"]]
    )
    pieces = s["quantity"] * np.where(s["unit"] == "BOX", s["units_per_box"], 1)
    unit_price = s["net_value_thb"] / pieces
    ratio = unit_price / s["list_price_thb"]
    # older price lists are lower, channel and promotion discounts cut at most ~40% together
    assert ratio.between(0.5, 1.0 + 1e-9).all()
    assert np.allclose(s["net_value_thb"], s["net_value_thb"].round(2))


def test_sales_cover_only_the_history(small_cfg, small_sales):
    dates = small_sales["posting_date"]
    assert dates.min() >= pd.Timestamp(small_cfg.start)
    assert dates.max() <= pd.Timestamp(small_cfg.history_end)
