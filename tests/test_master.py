"""Master data: materials, suppliers, customers and warehouses."""

import re
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from stockpilot.synth.calendar import build_calendar
from stockpilot.synth.catalog import CATEGORIES
from stockpilot.synth.config import SynthConfig
from stockpilot.synth.master import build_master
from stockpilot.synth.names import BRAND_STEMS

THAI = re.compile("[\\u0e00-\\u0e7f]")


@pytest.fixture(scope="module")
def cfg():
    return SynthConfig.from_preset("small")


@pytest.fixture(scope="module")
def master(cfg):
    return build_master(cfg, build_calendar(cfg))


def test_material_codes_are_unique_18_digit_strings_with_leading_zeros(master):
    codes = master.materials["material_code"]
    assert codes.is_unique
    assert codes.str.fullmatch(r"0\d{17}").all()


def test_prices_exceed_costs_and_are_rounded_to_satang(master):
    m = master.materials
    assert (m["standard_cost_thb"] > 0).all()
    assert (m["list_price_thb"] > m["standard_cost_thb"]).all()
    for col in ("list_price_thb", "standard_cost_thb"):
        assert np.allclose(m[col], m[col].round(2), rtol=0, atol=1e-9)


def test_list_prices_follow_the_product_type_price_band(master):
    bands = {name: (lo, hi) for cat in CATEGORIES for name, lo, hi, _ in cat.products}
    product = master.materials["description"].str.split(" ", n=1).str[1]
    lo = product.map(lambda name: bands[name][0])
    hi = product.map(lambda name: bands[name][1])
    assert master.materials["list_price_thb"].between(lo, hi).all()


def test_brands_come_from_the_curated_stem_list(master):
    assert set(master.materials["brand"]) <= set(BRAND_STEMS)
    stems = {name.removeprefix("PT ").split(" ")[0] for name in master.suppliers["supplier_name"]}
    assert stems <= set(BRAND_STEMS)


def test_moq_is_a_positive_whole_number_of_boxes(master):
    m = master.materials
    assert (m["moq"] >= m["units_per_box"]).all()
    assert (m["moq"] % m["units_per_box"] == 0).all()
    assert set(m["base_unit"]) == {"PC"}
    assert set(m["sales_unit"]) <= {"PC", "BOX"}


def test_pattern_counts_follow_the_configured_mix_exactly(master):
    # small preset: 240 SKUs x (0.35, 0.15, 0.30, 0.20)
    counts = master.sku_profile["pattern"].value_counts().to_dict()
    assert counts == {"smooth": 84, "intermittent": 72, "lumpy": 48, "erratic": 36}


def test_supplier_lead_times_depend_on_origin(master):
    s = master.suppliers
    domestic = s["country"] == "TH"
    assert s.loc[domestic, "planned_lead_time_days"].between(3, 10).all()
    assert s.loc[~domestic, "planned_lead_time_days"].between(21, 49).all()
    assert set(s.loc[domestic, "order_cycle_days"]) == {7}
    assert set(s.loc[~domestic, "order_cycle_days"]) <= {14, 28}
    assert s["order_weekday"].between(0, 4).all()
    assert set(master.materials["supplier_id"]) <= set(s["supplier_id"])


def test_customers_are_in_thailand_and_served_by_their_regional_dc(master):
    c = master.customers
    assert c["latitude"].between(5.6, 20.5).all()
    assert c["longitude"].between(97.3, 105.7).all()
    expected = {"Bangkok": "1100", "Chiang Mai": "1100", "Khon Kaen": "1200", "Songkhla": "1300"}
    for province, plant in expected.items():
        served = c.loc[c["province"] == province, "delivering_plant"]
        assert (served == plant).all()
    assert set(c["delivering_plant"]) == {"1100", "1200", "1300"}
    assert c["customer_id"].str.fullmatch(r"\d{10}").all()
    assert c["customer_id"].is_unique


def test_customer_names_mix_thai_and_english(master):
    thai_share = master.customers["customer_name"].map(lambda s: bool(THAI.search(s))).mean()
    assert 0.3 <= thai_share <= 0.95


def test_lifecycle_dates_are_consistent_and_inside_the_history(cfg, master):
    m = master.materials
    disc = m["status"] == "DISCONTINUED"
    assert m.loc[disc, "discontinued_date"].notna().all()
    assert m.loc[~disc, "discontinued_date"].isna().all()
    assert (m.loc[disc, "discontinued_date"] <= cfg.history_end).all()
    assert (m.loc[disc, "launch_date"] < m.loc[disc, "discontinued_date"]).all()
    launched = m["launch_date"] >= cfg.start
    assert launched.any() and disc.any()
    assert (m.loc[launched, "launch_date"] <= cfg.history_end - timedelta(days=182)).all()
    profile = master.sku_profile.set_index("material_code")
    assert set(profile.loc[m.loc[launched, "material_code"], "pattern"]) <= {"smooth", "erratic"}


def test_predecessors_are_discontinued_skus(master):
    m = master.materials.set_index("material_code")
    successors = m[m["predecessor_material_code"].notna()]
    assert len(successors) > 0
    preds = m.loc[successors["predecessor_material_code"]]
    assert (preds["status"] == "DISCONTINUED").all()


def test_one_key_account_is_lost_during_the_history(cfg, master):
    p = master.customer_profile
    lost = p[p["major_loss"]]
    assert len(lost) == 1
    assert lost["customer_type"].iloc[0] in {"MT", "WHOLESALE"}
    assert lost["customer_id"].iloc[0] in set(p.nlargest(10, "size_weight")["customer_id"])
    assert cfg.start + timedelta(days=365) < lost["active_to"].iloc[0] < cfg.history_end


def test_key_accounts_hold_most_of_the_purchasing_weight(master):
    # MT chains and wholesalers are 20% of customers but should buy well over half the volume.
    p = master.customer_profile
    key = p["customer_type"].isin(["MT", "WHOLESALE"])
    assert key.mean() == pytest.approx(0.20, abs=0.01)
    assert p.loc[key, "size_weight"].sum() / p["size_weight"].sum() > 0.5


def test_blocked_flag_only_marks_customers_that_stopped_buying(master):
    c = master.customers.merge(master.customer_profile, on="customer_id")
    assert c.loc[c["blocked"], "active_to"].notna().all()
    assert not c.loc[c["active_to"].isna(), "blocked"].any()


def test_three_warehouses(master):
    w = master.warehouses
    assert list(w["plant"]) == ["1100", "1200", "1300"]


def test_master_data_is_deterministic(cfg):
    a = build_master(cfg, build_calendar(cfg))
    b = build_master(cfg, build_calendar(cfg))
    for name in ("materials", "suppliers", "customers", "sku_profile", "customer_profile"):
        pd.testing.assert_frame_equal(getattr(a, name), getattr(b, name))


def test_dates_are_python_dates(master):
    assert isinstance(master.materials["launch_date"].iloc[0], date)
