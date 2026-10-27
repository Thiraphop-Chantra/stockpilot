"""Injected data-quality problems: counts, labels and the absence of unlabelled corruption."""

import pandas as pd
import pytest

from stockpilot.synth.issues import ENTRY_ERROR_TYPES, ISSUE_TYPES

COLUMNS_CHANGED_BY = {
    "truncated_material_code": {"material_code"},
    "extra_zero": {"quantity", "net_value_thb"},
    "unit_mismatch": {"unit"},
    "missing_net_value": {"net_value_thb"},
    "future_date": {"posting_date"},
}
COMPARED = ["posting_date", "material_code", "plant", "quantity", "unit", "net_value_thb"]


def labels(injected, kind):
    issues = injected.issues
    return issues[issues["issue_type"] == kind]


def test_every_issue_type_is_present_even_at_tiny_scale(tiny_injected):
    assert set(tiny_injected.issues["issue_type"]) == set(ISSUE_TYPES)


def test_injected_record_counts_follow_the_configured_rates(
    small_cfg, small_master, small_sales, small_injected
):
    rates = small_cfg.issues
    n = len(small_sales)
    boxed = small_sales["material_code"].map(
        small_master.materials.set_index("material_code")["units_per_box"]
    )
    expected = {
        "extra_zero": max(1, round(rates.extra_zero * n)),
        "unit_mismatch": max(1, round(rates.unit_mismatch * int((boxed > 1).sum()))),
        "missing_net_value": max(1, round(rates.missing_net_value * n)),
        "future_date": max(1, round(rates.future_date * n)),
    }
    issues = small_injected.issues
    for kind, count in expected.items():
        records = issues.loc[issues["issue_type"] == kind, "record_key"].nunique()
        assert records == count, kind
    assert len(labels(small_injected, "missing_list_price")) == max(
        1, round(rates.missing_list_price * small_cfg.n_skus)
    )
    assert len(labels(small_injected, "duplicate_customer")) == max(
        1, round(rates.duplicate_customer * small_cfg.n_customers)
    )


def test_truncated_codes_are_exactly_the_labelled_rows(small_injected):
    raw = small_injected.raw_sales
    short = set(raw.loc[raw["material_code"].str.len() != 18, "row_id"])
    lab = labels(small_injected, "truncated_material_code")
    assert short == set(lab["row_id"]) and short
    assert (lab["observed_value"] == lab["true_value"].str.lstrip("0")).all()
    files = raw.loc[raw["row_id"].isin(short), "source_file"].unique()
    in_files = raw[raw["source_file"].isin(files)]
    assert (in_files["material_code"].str.len() != 18).all()  # whole export files are affected


def test_duplicate_rows_are_exactly_the_labelled_repeats(small_injected):
    raw = small_injected.raw_sales.sort_values("row_id")
    repeated = raw[raw.duplicated(["billing_doc", "item"], keep="first")]
    lab = labels(small_injected, "duplicate_row")
    assert set(repeated["row_id"]) == set(lab["row_id"]) and len(lab) > 0
    first = raw.drop_duplicates(["billing_doc", "item"]).set_index(["billing_doc", "item"])[
        "row_id"
    ]
    expected_first = repeated.set_index(["billing_doc", "item"]).index.map(first)
    assert dict(zip(repeated["row_id"], expected_first, strict=True)) == dict(
        zip(lab["row_id"], lab["related_row_id"], strict=True)
    )
    assert raw["source_file"].str.endswith("_RERUN").any()


def test_future_dates_are_exactly_the_labelled_rows(small_cfg, small_injected):
    raw = small_injected.raw_sales
    future = set(raw.loc[raw["posting_date"] > pd.Timestamp(small_cfg.history_end), "row_id"])
    lab = labels(small_injected, "future_date")
    assert future == set(lab["row_id"]) and future
    true = pd.to_datetime(lab["true_value"])
    observed = raw.set_index("row_id").loc[lab["row_id"], "posting_date"]
    years = observed.dt.year.to_numpy() - true.dt.year.to_numpy()
    assert set(years) <= {543, 1}
    assert (years == 543).any()


def test_missing_values_are_exactly_the_labelled_rows(small_injected):
    raw = small_injected.raw_sales
    assert set(raw.loc[raw["net_value_thb"].isna(), "row_id"]) == set(
        labels(small_injected, "missing_net_value")["row_id"]
    )
    mats = small_injected.raw_materials
    assert set(mats.loc[mats["list_price_thb"].isna(), "material_code"]) == set(
        labels(small_injected, "missing_list_price")["record_key"]
    )


def test_quantity_and_unit_errors_change_what_the_labels_say(small_injected):
    raw = small_injected.raw_sales.set_index("row_id")
    clean = small_injected.sales_clean.set_index(["billing_doc", "item"])
    ez = labels(small_injected, "extra_zero")
    got = raw.loc[ez["row_id"]]
    true = clean.loc[list(zip(got["billing_doc"], got["item"], strict=True))]
    factor = got["quantity"].to_numpy() / true["quantity"].to_numpy()
    assert set(factor) <= {10, 100}
    um = labels(small_injected, "unit_mismatch")
    got = raw.loc[um["row_id"]]
    true = clean.loc[list(zip(got["billing_doc"], got["item"], strict=True))]
    assert (got["quantity"].to_numpy() == true["quantity"].to_numpy()).all()
    assert (got["unit"].to_numpy() != true["unit"].to_numpy()).all()


def test_each_record_has_at_most_one_entry_error(small_injected):
    issues = small_injected.issues
    entry = issues[issues["issue_type"].isin(ENTRY_ERROR_TYPES)]
    per_record = entry.groupby("record_key")["issue_type"].nunique()
    assert (per_record == 1).all()


def test_no_unlabelled_corruption(small_injected):
    raw = small_injected.raw_sales
    clean = small_injected.sales_clean
    merged = raw.merge(clean, on=["billing_doc", "item"], suffixes=("", "_true"), validate="m:1")
    assert len(merged) == len(raw)
    allowed = set()
    for row in small_injected.issues.dropna(subset=["row_id"]).itertuples():
        for column in COLUMNS_CHANGED_BY.get(row.issue_type, ()):
            allowed.add((int(row.row_id), column))
    for column in COMPARED:
        a, b = merged[column], merged[f"{column}_true"]
        differs = ~((a == b) | (a.isna() & b.isna()))
        changed = {(int(r), column) for r in merged.loc[differs, "row_id"]}
        assert changed <= allowed, column
    dup = labels(small_injected, "duplicate_customer").set_index("record_key")["related_key"]
    moved = merged["customer_id"] != merged["customer_id_true"]
    assert (
        merged.loc[moved, "customer_id"].map(dup) == merged.loc[moved, "customer_id_true"]
    ).all()
    assert moved.any()


def test_duplicate_customers_are_plausible_second_entries(small_master, small_injected):
    lab = labels(small_injected, "duplicate_customer")
    raw = small_injected.raw_customers.set_index("customer_id")
    dup, orig = raw.loc[lab["record_key"]], raw.loc[lab["related_key"]]
    assert (dup["customer_name"].to_numpy() != orig["customer_name"].to_numpy()).all()
    assert (dup["province"].to_numpy() == orig["province"].to_numpy()).all()
    assert (dup["delivering_plant"].to_numpy() == orig["delivering_plant"].to_numpy()).all()
    assert (dup["created_date"].to_numpy() > orig["created_date"].to_numpy()).all()
    assert not set(lab["record_key"]) & set(small_master.customers["customer_id"])
    assert set(lab["detail"]) <= {"th_to_en", "en_to_th", "romanization"}


def test_clean_truth_points_at_the_first_raw_copy(small_injected):
    raw = small_injected.raw_sales
    first = raw.sort_values("row_id").drop_duplicates(["billing_doc", "item"])
    clean = small_injected.sales_clean
    assert len(clean) == len(first)
    assert set(clean["row_id"]) == set(first["row_id"])


@pytest.mark.parametrize(
    "kind", ["extra_zero", "unit_mismatch", "missing_net_value", "future_date"]
)
def test_entry_errors_are_inherited_by_duplicate_copies(small_injected, kind):
    raw = small_injected.raw_sales.set_index("row_id")
    lab = labels(small_injected, kind)
    keys = raw.loc[lab["row_id"], ["billing_doc", "item"]].apply(tuple, axis=1)
    copies = raw.reset_index().merge(pd.DataFrame(list(set(keys)), columns=["billing_doc", "item"]))
    assert set(copies["row_id"]) == set(lab["row_id"])
