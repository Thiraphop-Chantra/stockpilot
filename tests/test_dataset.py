"""The written dataset: layout, metadata, manifest integrity, validation and CLI."""

import json
import shutil
from datetime import date

import pandas as pd
import pyarrow.parquet as pq
import pytest

from stockpilot.cli import main
from stockpilot.synth import generate, write
from stockpilot.synth.validate import TEST_TOLERANCES, validate_dataset

RAW = {"materials", "suppliers", "customers", "warehouses", "calendar", "promotions", "sales",
       "purchase_orders", "stock_month_end"}  # fmt: skip
TRUTH = {"issues", "sales_clean", "demand_daily", "sku_profile", "customer_profile",
         "supplier_lead_time", "supplier_disruptions", "events", "promotion_effects",
         "inventory_policy", "open_po_receipts"}  # fmt: skip


@pytest.fixture(scope="module")
def small_data(tmp_path_factory, small_cfg):
    out = tmp_path_factory.mktemp("small-data")
    return out, write(generate(small_cfg), out)


def test_raw_and_truth_tables_are_written_to_separate_directories(small_data):
    out, manifest = small_data
    assert {p.stem for p in (out / "raw").glob("*.parquet")} == RAW
    assert {p.stem for p in (out / "truth").glob("*.parquet")} == TRUTH
    assert set(manifest["tables"]) == {f"raw/{t}" for t in RAW} | {f"truth/{t}" for t in TRUTH}
    assert (out / "run_info.json").is_file()


def test_every_file_is_marked_synthetic(small_data):
    out, _ = small_data
    for path in out.glob("*/*.parquet"):
        meta = pq.read_schema(path).metadata
        assert meta[b"stockpilot.synthetic"] == b"true", path.name
        assert meta[b"stockpilot.table"] == f"{path.parent.name}/{path.stem}".encode()
    assert json.loads((out / "manifest.json").read_text())["synthetic"] is True


def test_manifest_row_counts_match_the_files(small_data):
    out, manifest = small_data
    for name, entry in manifest["tables"].items():
        assert pq.read_metadata(out / f"{name}.parquet").num_rows == entry["rows"], name


def test_buddhist_era_dates_survive_the_parquet_round_trip(small_cfg, small_data):
    out, _ = small_data
    sales = pd.read_parquet(out / "raw" / "sales.parquet")
    issues = pd.read_parquet(out / "truth" / "issues.parquet")
    dates = sales["posting_date"]
    years = dates.map(lambda d: d.year)
    assert (years >= 2564).any()
    future = (dates.map(lambda d: d > small_cfg.history_end)).sum()
    assert future == (issues["issue_type"] == "future_date").sum()
    assert isinstance(dates.iloc[0], date)


def test_material_codes_stay_strings(small_data):
    out, _ = small_data
    schema = pq.read_schema(out / "raw" / "materials.parquet")
    assert str(schema.field("material_code").type) == "string"


def test_validation_passes_and_reproduces_the_manifest_statistics(small_data):
    out, manifest = small_data
    report = validate_dataset(out, TEST_TOLERANCES)
    assert report.ok, report.failures()
    assert report.stats == manifest["stats"]


def test_validation_detects_a_tampered_file(tmp_path, small_data):
    out, _ = small_data
    copy = tmp_path / "copy"
    shutil.copytree(out, copy)
    sales = pq.read_table(copy / "raw" / "sales.parquet")
    pq.write_table(sales.slice(0, sales.num_rows - 1), copy / "raw" / "sales.parquet")
    report = validate_dataset(copy, TEST_TOLERANCES)
    assert not report.ok
    assert any("raw/sales" in f for f in report.failures())


def test_cli_generates_and_validates_a_dataset(tmp_path, capsys):
    assert main(["synth", "--preset", "tiny", "--out", str(tmp_path)]) == 0
    assert main(["validate", "--data", str(tmp_path)]) == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["preset"] == "tiny" and manifest["seed"] == 42
    assert "synthetic" in capsys.readouterr().out.lower()


def test_cli_refuses_to_overwrite_a_foreign_directory(tmp_path):
    (tmp_path / "notes.txt").write_text("not a dataset", encoding="utf-8")
    assert main(["synth", "--preset", "tiny", "--out", str(tmp_path)]) == 2
    assert (tmp_path / "notes.txt").exists()
