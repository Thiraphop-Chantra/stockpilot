"""Measure a written dataset and check it against its manifest and the configured targets.

``dataset_stats`` computes every published statistic from the Parquet files themselves, so the
numbers in ``manifest.json`` (and therefore in the docs) describe exactly what is on disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from stockpilot.synth.calendar import build_calendar
from stockpilot.synth.config import PATTERNS, SynthConfig
from stockpilot.synth.export import sha256
from stockpilot.synth.issues import ENTRY_ERROR_TYPES, ISSUE_TYPES
from stockpilot.synth.measure import measure_patterns, weekly_totals


@dataclass(frozen=True)
class Tolerances:
    pattern_share: float  # max |measured share - target| on true demand
    agreement: float  # min share of SKUs whose measured pattern equals the assigned one
    sales_pattern_share: float  # max |measured share - target| on observed (censored) sales
    fill_rate: tuple[float, float]  # allowed range of the unit fill rate


DEFAULT_TOLERANCES = Tolerances(0.03, 0.95, 0.10, (0.92, 0.98))
TEST_TOLERANCES = Tolerances(0.06, 0.90, 0.15, (0.80, 0.995))  # small presets are noisier


def tolerances_for(preset: str) -> Tolerances:
    return DEFAULT_TOLERANCES if preset == "default" else TEST_TOLERANCES


@dataclass
class ValidationReport:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(passed for _, passed, _ in self.checks)

    def failures(self) -> list[str]:
        return [f"{name}: {detail}" for name, passed, detail in self.checks if not passed]

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append((name, bool(passed), detail))


def _read(data: Path, name: str, columns: list[str] | None = None) -> pa.Table:
    return pq.read_table(data / f"{name}.parquet", columns=columns)


def _days(column: pa.ChunkedArray) -> np.ndarray:
    """date32 column as integer days since 1970-01-01."""
    return column.cast(pa.int32()).to_numpy(zero_copy_only=False)


def _shares(measured: pd.DataFrame) -> dict[str, float]:
    judged = measured[measured["measured"] != "insufficient"]
    counts = judged["measured"].value_counts()
    return {p: round(float(counts.get(p, 0) / max(1, len(judged))), 4) for p in PATTERNS}


def dataset_stats(data_dir: str | Path, cfg: SynthConfig) -> dict:
    """Every statistic the documentation publishes, measured from the files."""
    data = Path(data_dir)
    cal = build_calendar(cfg)
    epoch_first = int(cal.dates[0].astype(int))
    materials = _read(data, "raw/materials").to_pandas()
    codes = pd.Index(materials["material_code"])
    profile = _read(data, "truth/sku_profile").to_pandas().set_index("material_code")

    demand = _read(data, "truth/demand_daily")
    hist = ~demand.column("in_horizon").to_numpy(zero_copy_only=False)
    sku = codes.get_indexer(demand.column("material_code").to_numpy(zero_copy_only=False))[hist]
    day = _days(demand.column("date"))[hist] - epoch_first
    qty = demand.column("demand_qty").to_numpy()[hist]
    weekly, week_start = weekly_totals(sku, day, qty, len(codes), cal)
    true_mix = measure_patterns(materials, weekly, week_start, cal)
    true_mix["assigned"] = profile.loc[true_mix["material_code"], "pattern"].to_numpy()
    judged = true_mix[true_mix["measured"] != "insufficient"]

    clean = _read(data, "truth/sales_clean", ["material_code", "posting_date", "quantity", "unit"])
    units = materials.set_index("material_code")["units_per_box"]
    clean_codes = clean.column("material_code").to_numpy(zero_copy_only=False)
    per_box = pd.Series(clean_codes).map(units).to_numpy()
    boxed = clean.column("unit").to_numpy(zero_copy_only=False) == "BOX"
    pieces = clean.column("quantity").to_numpy() * np.where(boxed, per_box, 1)
    s_weekly, _ = weekly_totals(
        codes.get_indexer(clean_codes),
        _days(clean.column("posting_date")) - epoch_first,
        pieces,
        len(codes),
        cal,
    )
    sales_mix = measure_patterns(materials, s_weekly, week_start, cal)

    demand_hist = demand.filter(pa.array(hist)).to_pandas()
    demand_qty = int(demand_hist["demand_qty"].sum())
    sales_qty = int(demand_hist["sales_qty"].sum())
    with_demand = demand_hist[demand_hist["demand_qty"] > 0]

    issues = _read(data, "truth/issues").to_pandas()
    labels = issues["issue_type"].value_counts()
    entry = issues[issues["issue_type"].isin(ENTRY_ERROR_TYPES)]
    records = entry.groupby("issue_type")["record_key"].nunique()
    raw_files = (
        _read(data, "raw/sales", ["source_file"])
        .column("source_file")
        .to_numpy(zero_copy_only=False)
    )
    truncated = issues.loc[issues["issue_type"] == "truncated_material_code", "detail"]

    events = _read(data, "truth/events").to_pandas()
    loss = events[events["event_type"] == "customer_loss"]
    promotions = _read(data, "raw/promotions").to_pandas()
    po = _read(data, "raw/purchase_orders", ["receipt_date"]).column("receipt_date")
    customers_raw = _read(data, "raw/customers", ["customer_id"]).num_rows

    return {
        "volume": {
            "materials": len(materials),
            "customers": int(_read(data, "truth/customer_profile", ["customer_id"]).num_rows),
            "customer_accounts_raw": int(customers_raw),
            "suppliers": int(_read(data, "raw/suppliers", ["supplier_id"]).num_rows),
            "plants": int(_read(data, "raw/warehouses", ["plant"]).num_rows),
            "history_days": cal.history_end - cal.history_start + 1,
            "working_days": int(cal.is_working[cal.history].sum()),
            "sales_rows_raw": int(raw_files.size),
            "sales_records": int(clean.num_rows),
            "purchase_order_items": len(po),
            "open_purchase_order_items": int(po.null_count),
            "promotions_history": int((promotions["start_date"] <= cfg.history_end).sum()),
            "promotions_horizon": int((promotions["start_date"] > cfg.history_end).sum()),
        },
        "patterns": {
            "target": {p: float(s) for p, s in cfg.pattern_mix},
            "true_demand": _shares(true_mix),
            "observed_sales": _shares(sales_mix),
            "agreement": round(float((judged["measured"] == judged["assigned"]).mean()), 4),
            "insufficient_history": int((true_mix["measured"] == "insufficient").sum()),
        },
        "service": {
            "fill_rate": round(sales_qty / demand_qty, 4) if demand_qty else 1.0,
            "lost_units": demand_qty - sales_qty,
            "stockout_share_of_demand_days": round(float(with_demand["stockout"].mean()), 4),
        },
        "lifecycle": {
            "launched": int((materials["launch_date"] >= cfg.start).sum()),
            "discontinued": int((materials["status"] == "DISCONTINUED").sum()),
            "with_predecessor": int(materials["predecessor_material_code"].notna().sum()),
        },
        "issues": {
            "labels": {t: int(labels.get(t, 0)) for t in ISSUE_TYPES},
            "corrupted_records": {t: int(records.get(t, 0)) for t in ENTRY_ERROR_TYPES},
            "truncated_files": int(truncated.nunique()),
            "rerun_files": int(
                np.unique(raw_files[pd.Series(raw_files).str.endswith("_RERUN")]).size
            ),
        },
        "events": {
            "by_type": {
                k: int(v) for k, v in events["event_type"].value_counts().sort_index().items()
            },
            "key_account_loss_date": loss["start_date"].iloc[0].isoformat() if len(loss) else None,
            "key_account_demand_share": float(loss["magnitude"].iloc[0]) if len(loss) else None,
        },
    }


def validate_dataset(data_dir: str | Path, tol: Tolerances | None = None) -> ValidationReport:
    data = Path(data_dir)
    report = ValidationReport()
    manifest_path = data / "manifest.json"
    if not manifest_path.is_file():
        report.add("manifest present", False, f"{manifest_path} not found")
        return report
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cfg = SynthConfig.from_dict(manifest["config"])
    tol = tol or tolerances_for(manifest["preset"])

    intact = True
    for name, entry in manifest["tables"].items():
        path = data / f"{name}.parquet"
        if not path.is_file():
            report.add(f"{name} present", False, "missing file")
            intact = False
            continue
        meta = pq.read_schema(path).metadata or {}
        report.add(f"{name} marked synthetic", meta.get(b"stockpilot.synthetic") == b"true")
        rows = pq.read_metadata(path).num_rows
        same = rows == entry["rows"] and sha256(path) == entry["sha256"]
        report.add(f"{name} matches manifest", same, f"{rows} rows on disk vs {entry['rows']}")
        intact &= same
    if not intact:
        return report

    stats = dataset_stats(data, cfg)
    report.stats = stats
    report.add("statistics reproduce the manifest", stats == manifest["stats"])
    target, true_mix = stats["patterns"]["target"], stats["patterns"]["true_demand"]
    for pattern in PATTERNS:
        gap = abs(true_mix[pattern] - target[pattern])
        report.add(f"true-demand share of {pattern}", gap <= tol.pattern_share, f"off by {gap:.4f}")
        gap = abs(stats["patterns"]["observed_sales"][pattern] - target[pattern])
        report.add(f"sales share of {pattern}", gap <= tol.sales_pattern_share, f"off by {gap:.4f}")
    agreement = stats["patterns"]["agreement"]
    report.add("pattern agreement", agreement >= tol.agreement, f"{agreement:.4f}")
    fill = stats["service"]["fill_rate"]
    low, high = tol.fill_rate
    report.add("fill rate in range", low <= fill <= high, f"{fill:.4f} not in [{low}, {high}]")
    missing = [t for t, n in stats["issues"]["labels"].items() if n == 0]
    report.add("every issue type injected", not missing, ", ".join(missing))
    _check_references(data, report)
    return report


def _check_references(data: Path, report: ValidationReport) -> None:
    def column(name: str, col: str) -> pd.Series:
        return pd.Series(_read(data, name, [col]).column(col).to_numpy(zero_copy_only=False))

    materials = set(column("raw/materials", "material_code"))
    customers = set(column("raw/customers", "customer_id"))
    plants = set(column("raw/warehouses", "plant"))
    suppliers = set(column("raw/suppliers", "supplier_id"))
    sales_codes = set(column("raw/sales", "material_code").str.zfill(18))
    report.add("sales materials exist (after re-padding)", sales_codes <= materials)
    report.add("sales customers exist", set(column("raw/sales", "customer_id")) <= customers)
    report.add("sales plants exist", set(column("raw/sales", "plant")) <= plants)
    report.add(
        "PO materials exist", set(column("raw/purchase_orders", "material_code")) <= materials
    )
    report.add("PO suppliers exist", set(column("raw/purchase_orders", "supplier_id")) <= suppliers)
    report.add(
        "promoted materials exist", set(column("raw/promotions", "material_code")) <= materials
    )
